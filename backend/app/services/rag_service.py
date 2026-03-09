import json
import logging
import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_cohere import CohereRerank
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import BadRequestError
from openai import OpenAI
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import get_settings
from app.services.chunker import chunk_text
from app.services.clip_service import ClipService
from app.services.document_loader import IMAGE_EXTENSIONS, load_document

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self) -> None:
        init_start = perf_counter()
        settings = get_settings()
        self.settings = settings
        logger.info(
            'RagService init started model=%s embedding=%s text_collection=%s image_collection=%s',
            settings.openai_model,
            settings.embedding_model,
            settings.qdrant_collection,
            settings.qdrant_image_collection,
        )

        self.chat_llm = self._build_chat_llm(use_default_temperature=False)
        self.chat_llm_default_temp = self._build_chat_llm(use_default_temperature=True)
        self.openai_client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self.embedding_model = OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.embedding_model,
        )
        self.clip_service = ClipService(settings.clip_model_name)

        self.qdrant_client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )
        logger.info('Qdrant client initialized url=%s', settings.qdrant_url)
        self._ensure_collections()

        self.vector_store = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=settings.qdrant_collection,
            embedding=self.embedding_model,
        )

        self.reranker = None
        if settings.cohere_api_key:
            self.reranker = CohereRerank(
                cohere_api_key=settings.cohere_api_key,
                model=settings.cohere_rerank_model,
                top_n=settings.rerank_top_k,
            )
            logger.info('Cohere reranker enabled model=%s top_n=%s', settings.cohere_rerank_model, settings.rerank_top_k)
        else:
            logger.info('Cohere reranker disabled: missing COHERE_API_KEY')
        logger.info('RagService init completed elapsed_ms=%s', int((perf_counter() - init_start) * 1000))

    def _build_chat_llm(self, use_default_temperature: bool) -> ChatOpenAI:
        model_name = self.settings.openai_model.lower().strip()
        kwargs = {
            'api_key': self.settings.openai_api_key,
            'base_url': self.settings.openai_base_url,
            'model': self.settings.openai_model,
        }
        if not use_default_temperature:
            # GPT-5 family models reject custom temperature values.
            if model_name.startswith('gpt-5'):
                logger.info('Skipping custom temperature for GPT-5 model=%s', self.settings.openai_model)
            else:
                kwargs['temperature'] = self.settings.temperature
        return ChatOpenAI(**kwargs)

    def _invoke_chat(self, payload):
        try:
            return self.chat_llm.invoke(payload)
        except BadRequestError as exc:
            msg = str(exc)
            if 'temperature' in msg and 'Only the default (1) value is supported' in msg:
                logger.warning('Provider rejected custom temperature; retrying with model default temperature')
                return self.chat_llm_default_temp.invoke(payload)
            raise

    def _ensure_collections(self) -> None:
        text_exists = self.qdrant_client.collection_exists(self.settings.qdrant_collection)
        if text_exists:
            logger.info('Qdrant text collection exists name=%s', self.settings.qdrant_collection)
        else:
            logger.info('Qdrant text collection missing, creating name=%s', self.settings.qdrant_collection)
            text_dim = len(self.embedding_model.embed_query('dimension probe'))
            self.qdrant_client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(size=text_dim, distance=qmodels.Distance.COSINE),
            )
            logger.info('Qdrant text collection created name=%s dim=%s', self.settings.qdrant_collection, text_dim)

        image_exists = self.qdrant_client.collection_exists(self.settings.qdrant_image_collection)
        if image_exists:
            logger.info('Qdrant image collection exists name=%s', self.settings.qdrant_image_collection)
        else:
            logger.info('Qdrant image collection missing, creating name=%s', self.settings.qdrant_image_collection)
            self.qdrant_client.create_collection(
                collection_name=self.settings.qdrant_image_collection,
                vectors_config=qmodels.VectorParams(size=self.clip_service.dim, distance=qmodels.Distance.COSINE),
            )
            logger.info('Qdrant image collection created name=%s dim=%s', self.settings.qdrant_image_collection, self.clip_service.dim)

    def _expand_query(self, question: str) -> list[str]:
        logger.info('Query expansion started')
        prompt = (
            f'Generate {self.settings.query_expansion_count} alternate phrasings for this query. '
            'Return strictly JSON array of strings only. No markdown.'
        )
        response = self._invoke_chat(f'{prompt}\n\nQuery: {question}')
        content = str(response.content).strip()

        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                variations = [str(item).strip() for item in parsed if str(item).strip()]
                selected = variations[: self.settings.query_expansion_count]
                logger.info('Query expansion completed variations=%s', len(selected))
                return selected
        except json.JSONDecodeError:
            logger.warning('Query expansion parse failed; using original query only')

        return []

    @staticmethod
    def _dedupe_docs(documents: list[Document]) -> list[Document]:
        deduped: list[Document] = []
        seen = set()
        for doc in documents:
            key = (doc.metadata.get('source', ''), doc.page_content)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(doc)
        return deduped

    @staticmethod
    def _build_qdrant_filter(filters: dict | None) -> qmodels.Filter | None:
        if not filters:
            return None
        must: list[qmodels.FieldCondition] = []
        owner_id = filters.get('owner_id')
        tenant_id = filters.get('tenant_id')
        file_type = filters.get('file_type')
        tags = filters.get('tags')

        if owner_id:
            must.append(qmodels.FieldCondition(key='owner_id', match=qmodels.MatchValue(value=str(owner_id))))
        if tenant_id:
            must.append(qmodels.FieldCondition(key='tenant_id', match=qmodels.MatchValue(value=str(tenant_id))))
        if file_type:
            must.append(qmodels.FieldCondition(key='file_type', match=qmodels.MatchValue(value=str(file_type))))
        if tags:
            for tag in tags:
                must.append(qmodels.FieldCondition(key='tags', match=qmodels.MatchValue(value=str(tag))))

        if not must:
            return None
        return qmodels.Filter(must=must)

    @staticmethod
    def _auto_tags(text: str, source_name: str, max_tags: int = 8) -> list[str]:
        tokens = []
        for raw in (source_name.replace('.', ' ') + ' ' + text[:3000]).lower().split():
            cleaned = ''.join(ch for ch in raw if ch.isalnum() or ch in {'_', '-'})
            if len(cleaned) < 3:
                continue
            if cleaned in {
                'the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'your', 'have',
                'are', 'was', 'were', 'not', 'you', 'has', 'had', 'will', 'shall', 'can', 'its',
                'pdf', 'doc', 'docx', 'txt', 'csv', 'png', 'jpg', 'jpeg', 'webp'
            }:
                continue
            tokens.append(cleaned)

        seen = set()
        tags: list[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            tags.append(token)
            if len(tags) >= max_tags:
                break
        return tags

    def _ingest_image(self, file_path: Path, metadata: dict) -> int:
        logger.info('Image ingest started source=%s', file_path.name)
        vector = self.clip_service.embed_image(file_path)
        point = qmodels.PointStruct(
            id=uuid4().hex,
            vector=vector,
            payload={
                'source': file_path.name,
                'type': 'image',
                'text': f'Image file: {file_path.name}',
                **metadata,
            },
        )
        self.qdrant_client.upsert(
            collection_name=self.settings.qdrant_image_collection,
            points=[point],
            wait=True,
        )
        logger.info('Image ingest completed source=%s', file_path.name)
        return 1

    def ingest_file(self, file_path: Path, metadata: dict | None = None, raw_bytes: bytes | None = None) -> int:
        ingest_start = perf_counter()
        logger.info('Ingest started source=%s', file_path.name)
        metadata = dict(metadata or {})
        if raw_bytes:
            metadata['content_hash'] = hashlib.sha256(raw_bytes).hexdigest()

        if file_path.suffix.lower() in IMAGE_EXTENSIONS:
            if not metadata.get('tags'):
                metadata['tags'] = self._auto_tags('', file_path.name)
            indexed = self._ingest_image(file_path, metadata)
            logger.info(
                'Ingest completed source=%s chunks=%s elapsed_ms=%s',
                file_path.name,
                indexed,
                int((perf_counter() - ingest_start) * 1000),
            )
            return indexed

        text = load_document(file_path)
        chunks = chunk_text(
            text,
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            logger.info('Ingest completed source=%s chunks=0 elapsed_ms=%s', file_path.name, int((perf_counter() - ingest_start) * 1000))
            return 0

        if not metadata.get('tags'):
            metadata['tags'] = self._auto_tags(text, file_path.name)

        docs = []
        for idx, chunk in enumerate(chunks):
            chunk_meta = {
                'source': file_path.name,
                'type': 'text',
                'chunk_id': f"{metadata.get('doc_id', file_path.stem)}:{idx}",
                **metadata,
            }
            docs.append(Document(page_content=chunk, metadata=chunk_meta))
        logger.info('Vector store add started source=%s docs=%s', file_path.name, len(docs))
        self.vector_store.add_documents(docs)
        logger.info('Ingest completed source=%s chunks=%s elapsed_ms=%s', file_path.name, len(docs), int((perf_counter() - ingest_start) * 1000))
        return len(docs)

    def _retrieve_image_candidates(self, queries: list[str], k: int, filters: dict | None = None) -> list[Document]:
        docs: list[Document] = []
        qdrant_filter = self._build_qdrant_filter(filters)
        vectors = self.clip_service.embed_texts(queries)

        def _search(query: str, query_vector: list[float]) -> list[Document]:
            results = self.qdrant_client.search(
                collection_name=self.settings.qdrant_image_collection,
                query_vector=query_vector,
                limit=k,
                with_payload=True,
                query_filter=qdrant_filter,
            )
            logger.info('Image retrieval query="%s" hits=%s', query[:120], len(results))
            found: list[Document] = []
            for point in results:
                payload = point.payload or {}
                source = str(payload.get('source', 'unknown'))
                found.append(
                    Document(
                        page_content=f"Image match from {source}. Similarity score: {float(point.score or 0.0):.4f}",
                        metadata={
                            'source': source,
                            'type': 'image',
                            'score': float(point.score or 0.0),
                            'doc_id': payload.get('doc_id'),
                            'chunk_id': payload.get('chunk_id'),
                            'owner_id': payload.get('owner_id'),
                            'tenant_id': payload.get('tenant_id'),
                            'uploaded_at': payload.get('uploaded_at'),
                            'file_type': payload.get('file_type'),
                            'page_no': payload.get('page_no'),
                            'content_hash': payload.get('content_hash'),
                            'tags': payload.get('tags'),
                        },
                    )
                )
            return found

        max_workers = min(len(queries), 4) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_search, query, vec) for query, vec in zip(queries, vectors)]
            for f in as_completed(futures):
                docs.extend(f.result())
        return docs

    def _add_ephemeral_image_point(self, file_path: Path) -> str:
        point_id = str(uuid4())
        vector = self.clip_service.embed_image(file_path)
        payload = {
            'source': file_path.name,
            'type': 'image',
            'text': f'Ephemeral ad-hoc image: {file_path.name}',
            'doc_id': f'ephemeral:{point_id}',
            'chunk_id': f'{point_id}:0',
            'owner_id': None,
            'tenant_id': None,
            'uploaded_at': None,
            'file_type': file_path.suffix.lstrip('.'),
            'content_hash': None,
            'tags': self._auto_tags('', file_path.name),
            'page_no': None,
            'ephemeral': True,
        }
        self.qdrant_client.upsert(
            collection_name=self.settings.qdrant_image_collection,
            points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload)],
            wait=True,
        )
        logger.info('Ephemeral image indexed point_id=%s source=%s', point_id, file_path.name)
        return point_id

    def _remove_ephemeral_image_point(self, point_id: str) -> None:
        try:
            self.qdrant_client.delete(
                collection_name=self.settings.qdrant_image_collection,
                points_selector=qmodels.PointIdsList(points=[point_id]),
                wait=True,
            )
            logger.info('Ephemeral image removed point_id=%s', point_id)
        except Exception as exc:
            logger.warning('Failed to remove ephemeral image point_id=%s error=%s', point_id, exc)

    def _retrieve_candidates(self, queries: list[str], retrieve_k: int, filters: dict | None = None) -> list[Document]:
        qdrant_filter = self._build_qdrant_filter(filters)
        text_candidates: list[Document] = []

        embedding_start = perf_counter()
        query_vectors = self.embedding_model.embed_documents(queries)
        logger.info(
            'Text query embeddings completed queries=%s elapsed_ms=%s',
            len(queries),
            int((perf_counter() - embedding_start) * 1000),
        )

        def _search_text(query: str, query_vector: list[float]) -> list[Document]:
            logger.info('Text retrieval started query="%s"', query[:120])
            result = self.qdrant_client.query_points(
                collection_name=self.settings.qdrant_collection,
                query=query_vector,
                limit=retrieve_k,
                with_payload=True,
                query_filter=qdrant_filter,
            )
            points = result.points or []
            found: list[Document] = []
            for point in points:
                payload = point.payload or {}
                found.append(
                    Document(
                        page_content=str(payload.get('page_content', payload.get('text', ''))),
                        metadata={
                            'source': payload.get('source'),
                            'type': payload.get('type'),
                            'score': float(point.score or 0.0),
                            'doc_id': payload.get('doc_id'),
                            'chunk_id': payload.get('chunk_id'),
                            'owner_id': payload.get('owner_id'),
                            'tenant_id': payload.get('tenant_id'),
                            'uploaded_at': payload.get('uploaded_at'),
                            'file_type': payload.get('file_type'),
                            'page_no': payload.get('page_no'),
                            'content_hash': payload.get('content_hash'),
                            'tags': payload.get('tags'),
                        },
                    )
                )
            return found

        max_workers = min(len(queries), 4) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_search_text, query, vec) for query, vec in zip(queries, query_vectors)]
            for f in as_completed(futures):
                text_candidates.extend(f.result())

        image_candidates = self._retrieve_image_candidates(queries, self.settings.image_retrieval_top_k, filters=filters)
        candidates = self._dedupe_docs(text_candidates + image_candidates)
        logger.info(
            'Retrieval completed text_docs=%s image_docs=%s total=%s',
            len(text_candidates),
            len(image_candidates),
            len(candidates),
        )
        return candidates

    def _answer_from_documents(self, question: str, selected_docs: list[Document], history: list[dict] | None = None) -> tuple[str, list[dict]]:
        history = history or []
        history_text = '\n'.join([f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history[-8:]])
        context_text = '\n\n'.join(
            [
                f"Source: {doc.metadata.get('source', 'unknown')}\nType: {doc.metadata.get('type', 'text')}\nContent: {doc.page_content}"
                for doc in selected_docs
            ]
        )

        answer_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    'system',
                    'You are a precise multimodal RAG assistant. Use only context below. If missing info, say it clearly.',
                ),
                (
                    'human',
                    'Conversation history:\n{history}\n\nQuestion:\n{question}\n\nContext:\n{context}\n\nAnswer directly and end with sources used.',
                ),
            ]
        )
        answer = self._invoke_chat(answer_prompt.format_messages(question=question, history=history_text, context=context_text))
        logger.info('Answer generation completed')

        source_scores: dict[str, dict] = {}
        total = max(len(selected_docs), 1)
        for rank, doc in enumerate(selected_docs, start=1):
            source = str(doc.metadata.get('source', 'unknown'))
            score = float(total - rank + 1) / float(total)
            existing = source_scores.get(source)
            if existing is None or score > float(existing.get('score', 0.0)):
                source_scores[source] = {
                    'source': source,
                    'score': score,
                    'doc_id': doc.metadata.get('doc_id'),
                    'chunk_id': doc.metadata.get('chunk_id'),
                    'owner_id': doc.metadata.get('owner_id'),
                    'tenant_id': doc.metadata.get('tenant_id'),
                    'uploaded_at': doc.metadata.get('uploaded_at'),
                    'file_type': doc.metadata.get('file_type'),
                    'page_no': doc.metadata.get('page_no'),
                    'content_hash': doc.metadata.get('content_hash'),
                    'tags': doc.metadata.get('tags'),
                    'type': doc.metadata.get('type'),
                }

        sources = list(source_scores.values())
        return str(answer.content), sources

    def _analyze_image_with_llm(self, image_path: Path, question: str) -> str:
        mime = 'image/png'
        suffix = image_path.suffix.lower().lstrip('.')
        if suffix in {'jpg', 'jpeg'}:
            mime = 'image/jpeg'
        elif suffix == 'webp':
            mime = 'image/webp'

        encoded = base64.b64encode(image_path.read_bytes()).decode('utf-8')
        image_url = f'data:{mime};base64,{encoded}'
        response = self.openai_client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {
                    'role': 'system',
                    'content': 'You analyze images for RAG and extract relevant facts as concise text.',
                },
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': f'Question: {question}\nDescribe key details and visible text.'},
                        {'type': 'image_url', 'image_url': {'url': image_url}},
                    ],
                },
            ],
        )
        return response.choices[0].message.content or ''

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        history: list[dict] | None = None,
        filters: dict | None = None,
    ) -> tuple[str, list[dict]]:
        ask_start = perf_counter()
        retrieve_k = top_k or self.settings.retrieval_top_k
        logger.info('Ask pipeline started question_len=%s retrieve_k=%s', len(question), retrieve_k)
        expand_start = perf_counter()
        queries = [question]
        queries.extend([q for q in self._expand_query(question) if q.lower() != question.lower()])
        logger.info('Expansion elapsed_ms=%s', int((perf_counter() - expand_start) * 1000))
        logger.info('Retrieval queries prepared count=%s', len(queries))

        retrieval_start = perf_counter()
        candidates = self._retrieve_candidates(queries, retrieve_k, filters=filters)
        logger.info('Retrieval elapsed_ms=%s', int((perf_counter() - retrieval_start) * 1000))
        if not candidates:
            logger.info('Ask pipeline completed: no candidates elapsed_ms=%s', int((perf_counter() - ask_start) * 1000))
            return 'No indexed documents found. Upload files first.', []

        if self.reranker is not None:
            logger.info('Rerank started candidate_docs=%s', len(candidates))
            rerank_start = perf_counter()
            selected_docs = self.reranker.compress_documents(candidates, query=question)
            logger.info('Rerank completed selected_docs=%s elapsed_ms=%s', len(selected_docs), int((perf_counter() - rerank_start) * 1000))
        else:
            selected_docs = candidates[: self.settings.rerank_top_k]
            logger.info('Rerank skipped using top docs selected_docs=%s', len(selected_docs))

        answer_text, sources = self._answer_from_documents(question, selected_docs, history=history)
        logger.info('Ask pipeline completed sources=%s elapsed_ms=%s', len(sources), int((perf_counter() - ask_start) * 1000))
        return answer_text, sources

    def ask_with_file(
        self,
        question: str,
        file_path: Path,
        top_k: int | None = None,
        history: list[dict] | None = None,
        filters: dict | None = None,
    ) -> tuple[str, list[dict]]:
        ask_start = perf_counter()
        logger.info('Ask-with-file started question_len=%s file=%s', len(question), file_path.name)

        retrieve_k = top_k or self.settings.retrieval_top_k
        expand_start = perf_counter()
        queries = [question]
        queries.extend([q for q in self._expand_query(question) if q.lower() != question.lower()])
        logger.info('Ask-with-file expansion elapsed_ms=%s', int((perf_counter() - expand_start) * 1000))

        file_docs: list[Document] = []
        ext = file_path.suffix.lower()
        ephemeral_point_id: str | None = None
        try:
            if ext in IMAGE_EXTENSIONS:
                # Temporary index this uploaded image so retrieval can include it.
                ephemeral_point_id = self._add_ephemeral_image_point(file_path)

            retrieval_start = perf_counter()
            candidates = self._retrieve_candidates(queries, retrieve_k, filters=filters)
            logger.info('Ask-with-file retrieval elapsed_ms=%s', int((perf_counter() - retrieval_start) * 1000))

            if ext in IMAGE_EXTENSIONS:
                vision_text = self._analyze_image_with_llm(file_path, question)
                if vision_text.strip():
                    file_docs.append(
                        Document(
                            page_content=vision_text,
                            metadata={'source': file_path.name, 'type': 'image_vision', 'file_type': file_path.suffix.lstrip('.')},
                        )
                    )
                    logger.info('Ask-with-file image analysis completed file=%s chars=%s', file_path.name, len(vision_text))
            else:
                file_text = load_document(file_path)
                chunks = chunk_text(file_text, chunk_size=self.settings.chunk_size, overlap=self.settings.chunk_overlap)
                for idx, chunk in enumerate(chunks[: self.settings.rerank_top_k]):
                    file_docs.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                'source': file_path.name,
                                'type': 'ad_hoc_file',
                                'file_type': file_path.suffix.lstrip('.'),
                                'chunk_id': f'adhoc:{idx}',
                            },
                        )
                    )
                logger.info('Ask-with-file text extraction completed file=%s chunks=%s', file_path.name, len(file_docs))

            candidates = self._dedupe_docs(file_docs + candidates)
            if not candidates:
                logger.info('Ask-with-file completed: no candidates elapsed_ms=%s', int((perf_counter() - ask_start) * 1000))
                return 'No useful context found for this uploaded file and index.', []

            if self.reranker is not None:
                rerank_start = perf_counter()
                selected_docs = self.reranker.compress_documents(candidates, query=question)
                logger.info('Ask-with-file rerank elapsed_ms=%s', int((perf_counter() - rerank_start) * 1000))
            else:
                selected_docs = candidates[: self.settings.rerank_top_k]

            answer_text, sources = self._answer_from_documents(question, selected_docs, history=history)
            logger.info('Ask-with-file completed sources=%s elapsed_ms=%s', len(sources), int((perf_counter() - ask_start) * 1000))
            return answer_text, sources
        finally:
            if ephemeral_point_id is not None:
                self._remove_ephemeral_image_point(ephemeral_point_id)

    def chat(
        self,
        question: str,
        top_k: int | None = None,
        history: list[dict] | None = None,
        file_path: Path | None = None,
        filters: dict | None = None,
    ) -> tuple[str, list[dict]]:
        # Chat upload is ad-hoc only and never indexed into persistent collections.
        if file_path is not None:
            return self.ask_with_file(question=question, file_path=file_path, top_k=top_k, history=history, filters=filters)
        return self.ask(question=question, top_k=top_k, history=history, filters=filters)
