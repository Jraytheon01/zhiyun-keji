# meeting_assistant/embeddings.py
import asyncio
import hashlib

from .concurrency import call_llm


class EmbeddingDimensionError(RuntimeError):
    pass


class AsyncEmbedder:
    """Wrap an async OpenAI-compatible embedding endpoint with dimension checks."""
    def __init__(self, client, model: str, dim: int = 1024):
        self.client = client; self.model = model; self.dim = dim

    async def embed_batch(self, texts: list[str], batch_size: int = 10) -> list[list[float]]:
        if not texts:
            return []
        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        resps = await asyncio.gather(*[
            call_llm(self.client.embeddings, model=self.model, input=b) for b in batches
        ])
        out = []
        for r, b in zip(resps, batches):
            vectors = [d.embedding for d in sorted(r.data, key=lambda x: x.index)]
            if len(vectors) != len(b):
                raise RuntimeError(
                    f"embedding response count mismatch: expected={len(b)}, actual={len(vectors)}")
            for vector in vectors:
                if len(vector) != self.dim:
                    raise EmbeddingDimensionError(
                        f"embedding dimension mismatch: model={self.model}, "
                        f"configured={self.dim}, actual={len(vector)}; "
                        "set EMBEDDING_DIM to the model output dimension before writing Milvus")
            out.extend(vectors)
        return out

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]


class FakeAsyncEmbedder:
    def __init__(self, dim=1024): self.dim = dim
    def _vec(self, text):
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [((h[i % len(h)] / 255.0) * 2) - 1 for i in range(self.dim)]
    async def embed(self, text): return self._vec(text)
    async def embed_batch(self, texts): return [self._vec(t) for t in texts]


def make_embedder(settings, client=None):
    if client is None:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url,
                             timeout=settings.llm_timeout_seconds, max_retries=0)
    return AsyncEmbedder(client, settings.embed_model, dim=settings.embedding_dim)
