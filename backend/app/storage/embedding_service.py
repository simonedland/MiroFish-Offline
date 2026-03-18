"""
EmbeddingService — Azure OpenAI embeddings

Uses Azure OpenAI text-embedding-3-small (1536 dimensions).
"""

import logging
from typing import List, Optional

from openai import AzureOpenAI

from ..config import Config

logger = logging.getLogger('mirofish.embedding')

_EMBEDDING_DIM = 1536


class EmbeddingService:
    """Generate embeddings using Azure OpenAI."""

    def __init__(
        self,
        model: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.model = model or Config.AZURE_OPENAI_EMBED_DEPLOYMENT
        self.client = AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
            max_retries=max_retries,
            timeout=timeout,
        )

        # Simple in-memory cache (text -> embedding vector)
        self._cache: dict[str, List[float]] = {}
        self._cache_max_size = 2000

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text. Returns 1536-dimensional vector."""
        if not text or not text.strip():
            raise EmbeddingError("Cannot embed empty text")

        text = text.strip()
        if text in self._cache:
            return self._cache[text]

        vectors = self._request_embeddings([text])
        self._cache_put(text, vectors[0])
        return vectors[0]

    def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        for i, text in enumerate(texts):
            text = text.strip() if text else ""
            if text in self._cache:
                results[i] = self._cache[text]
            elif text:
                uncached_indices.append(i)
                uncached_texts.append(text)
            else:
                results[i] = [0.0] * _EMBEDDING_DIM

        if uncached_texts:
            all_vectors: List[List[float]] = []
            for start in range(0, len(uncached_texts), batch_size):
                batch = uncached_texts[start:start + batch_size]
                all_vectors.extend(self._request_embeddings(batch))

            for idx, vec, text in zip(uncached_indices, all_vectors, uncached_texts):
                results[idx] = vec
                self._cache_put(text, vec)

        return results  # type: ignore

    def _request_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Call Azure OpenAI embeddings API."""
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
            # Sort by index to preserve order
            items = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in items]
        except Exception as e:
            raise EmbeddingError(f"Azure OpenAI embedding failed: {e}") from e

    def _cache_put(self, text: str, vector: List[float]) -> None:
        """Add to cache, evicting oldest entries if full."""
        if len(self._cache) >= self._cache_max_size:
            keys_to_remove = list(self._cache.keys())[:self._cache_max_size // 10]
            for key in keys_to_remove:
                del self._cache[key]
        self._cache[text] = vector

    def health_check(self) -> bool:
        """Check if Azure OpenAI embedding endpoint is reachable."""
        try:
            vec = self.embed("health check")
            return len(vec) > 0
        except Exception:
            return False


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""
    pass
