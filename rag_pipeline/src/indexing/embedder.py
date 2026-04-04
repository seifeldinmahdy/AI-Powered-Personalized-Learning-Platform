"""Sentence-transformer embedding wrapper.

Uses sentence-transformers/all-MiniLM-L6-v2 by default.  Provides
single-text and batch embedding with structured logging.
"""

from __future__ import annotations

import structlog
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger(__name__)


class ChunkEmbedder:
    """Wraps a SentenceTransformer model for chunk embedding."""

    def __init__(self, model_name: str) -> None:
        logger.info("embedder_loading", model=model_name)
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        logger.info("embedder_ready", model=model_name)

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text string and return the vector."""
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return a list of vectors.

        Uses the model's internal batching for GPU efficiency.
        """
        logger.info("embedding_batch", count=len(texts))
        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True,
            batch_size=64,
        )
        logger.info("embedding_batch_complete", count=len(texts))
        return embeddings.tolist()
