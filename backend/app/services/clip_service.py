import logging
from pathlib import Path

from PIL import Image
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ClipService:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        probe = self.model.encode(['dimension probe'], convert_to_numpy=True)
        self.dim = int(probe.shape[1])
        logger.info('CLIP service initialized model=%s dim=%s', model_name, self.dim)

    def embed_image(self, image_path: Path) -> list[float]:
        image = Image.open(image_path).convert('RGB')
        vec = self.model.encode([image], convert_to_numpy=True, normalize_embeddings=True)[0]
        return [float(x) for x in vec]

    def embed_text(self, text: str) -> list[float]:
        vec = self.model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
        return [float(x) for x in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [[float(x) for x in row] for row in vectors]
