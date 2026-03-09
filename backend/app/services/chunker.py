import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> list[str]:
    clean_text = (text or '').strip()
    if not clean_text:
        logger.info('Chunking skipped: empty text')
        return []

    logger.info('Chunking started chars=%s chunk_size=%s overlap=%s', len(clean_text), chunk_size, overlap)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=['\n\n', '\n', ' ', ''],
    )
    chunks = splitter.split_text(clean_text)
    logger.info('Chunking completed chunks=%s', len(chunks))
    return chunks
