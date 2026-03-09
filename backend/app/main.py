from functools import lru_cache
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_config import setup_logging
from app.schemas import AskRequest, AskResponse, AskWithFileResponse, ChatResponse, HealthResponse, UploadResponse
from app.services.document_loader import SUPPORTED_EXTENSIONS

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@lru_cache(maxsize=1)
def get_rag_service():
    from app.services.rag_service import RagService

    logger.info('Initializing RagService')
    return RagService()


@app.on_event('startup')
def warmup_on_startup() -> None:
    start = perf_counter()
    logger.info('Startup warmup started')
    get_rag_service()
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info('Startup warmup completed elapsed_ms=%s', elapsed_ms)


@app.get('/health', response_model=HealthResponse)
def health() -> HealthResponse:
    logger.info('Health check requested')
    return HealthResponse(status='ok')


@app.post('/upload', response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...),
) -> UploadResponse:
    start = perf_counter()
    if not file.filename:
        logger.warning('Upload rejected: missing filename')
        raise HTTPException(status_code=400, detail='Missing filename.')

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        logger.warning('Upload rejected: unsupported extension filename=%s ext=%s', file.filename, ext)
        raise HTTPException(
            status_code=400,
            detail=f'Unsupported file type. Supported: {sorted(SUPPORTED_EXTENSIONS)}',
        )

    payload = await file.read()
    logger.info('Upload received filename=%s bytes=%s', file.filename, len(payload))
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(payload) > max_bytes:
        logger.warning('Upload rejected: file too large filename=%s bytes=%s max=%s', file.filename, len(payload), max_bytes)
        raise HTTPException(status_code=413, detail='File too large.')

    output_path = settings.upload_dir / file.filename
    output_path.write_bytes(payload)
    logger.info('Upload saved path=%s', output_path)

    resolved_doc_id = uuid4().hex
    metadata = {
        'doc_id': resolved_doc_id,
        'owner_id': None,
        'tenant_id': None,
        'tags': [],
        'uploaded_at': datetime.now(timezone.utc).isoformat(),
        'file_type': ext.lstrip('.'),
        'content_hash': None,
        'page_no': None,
    }
    indexed = get_rag_service().ingest_file(output_path, metadata=metadata, raw_bytes=payload)
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info('Upload indexed filename=%s chunks=%s elapsed_ms=%s', file.filename, indexed, elapsed_ms)
    return UploadResponse(filename=file.filename, chunks_indexed=indexed, doc_id=resolved_doc_id)


@app.post('/ask', response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    start = perf_counter()
    logger.info('Ask requested question_len=%s top_k=%s history_turns=%s', len(req.question), req.top_k, len(req.history))
    answer, sources = get_rag_service().ask(
        req.question,
        top_k=req.top_k,
        history=req.history,
        filters=req.filters.model_dump(exclude_none=True) if req.filters else None,
    )
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info('Ask completed sources=%s elapsed_ms=%s', len(sources), elapsed_ms)
    return AskResponse(answer=answer, sources=sources)


@app.post('/ask-with-file', response_model=AskWithFileResponse)
async def ask_with_file(
    question: str = Form(...),
    file: UploadFile = File(...),
    top_k: int | None = Form(default=None),
    history_json: str | None = Form(default=None),
    filters_json: str | None = Form(default=None),
) -> AskWithFileResponse:
    start = perf_counter()
    if not file.filename:
        raise HTTPException(status_code=400, detail='Missing filename.')

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f'Unsupported file type. Supported: {sorted(SUPPORTED_EXTENSIONS)}',
        )

    payload = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail='File too large.')

    history = []
    filters = None
    if history_json:
        try:
            history = json.loads(history_json)
        except json.JSONDecodeError:
            history = []
    if filters_json:
        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            filters = None

    temp_name = f'adhoc_{file.filename}'
    output_path = settings.upload_dir / temp_name
    output_path.write_bytes(payload)
    logger.info('Ask-with-file uploaded temp file path=%s question_len=%s history_turns=%s', output_path, len(question), len(history))

    answer, sources = get_rag_service().ask_with_file(
        question=question,
        file_path=output_path,
        top_k=top_k,
        history=history,
        filters=filters,
    )
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info('Ask-with-file completed sources=%s elapsed_ms=%s', len(sources), elapsed_ms)
    return AskWithFileResponse(answer=answer, sources=sources)


@app.post('/chat', response_model=ChatResponse)
async def chat(
    question: str = Form(...),
    top_k: int | None = Form(default=None),
    history_json: str | None = Form(default=None),
    filters_json: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> ChatResponse:
    start = perf_counter()
    history = []
    filters = None
    if history_json:
        try:
            history = json.loads(history_json)
        except json.JSONDecodeError:
            history = []
    if filters_json:
        try:
            filters = json.loads(filters_json)
        except json.JSONDecodeError:
            filters = None

    file_path = None
    if file is not None and file.filename:
        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f'Unsupported file type. Supported: {sorted(SUPPORTED_EXTENSIONS)}',
            )
        payload = await file.read()
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(payload) > max_bytes:
            raise HTTPException(status_code=413, detail='File too large.')
        file_path = settings.upload_dir / f'chat_{file.filename}'
        file_path.write_bytes(payload)
        logger.info('Chat received ad-hoc file path=%s bytes=%s', file_path, len(payload))

    answer, sources = get_rag_service().chat(
        question=question,
        top_k=top_k,
        history=history,
        file_path=file_path,
        filters=filters,
    )
    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info('Chat completed sources=%s elapsed_ms=%s', len(sources), elapsed_ms)
    return ChatResponse(answer=answer, sources=sources)
