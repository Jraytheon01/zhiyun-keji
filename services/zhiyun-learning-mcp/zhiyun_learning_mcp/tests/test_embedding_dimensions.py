from types import SimpleNamespace

import pytest

from zhiyun_learning_mcp.embeddings import AsyncEmbedder, EmbeddingDimensionError
from zhiyun_learning_mcp.vector_store import (
    AsyncMilvusVectorStore,
    FakeAsyncVectorStore,
    VectorDimensionMismatch,
    VectorSchemaMismatch,
)


class FakeEmbeddingsEndpoint:
    async def create(self, **kwargs):
        return SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=[0.0, 1.0, 2.0])
            for index, _ in enumerate(kwargs["input"])
        ])


async def test_embedder_rejects_unexpected_model_dimension(monkeypatch):
    async def direct_call(endpoint, **kwargs):
        return await endpoint.create(**kwargs)

    monkeypatch.setattr("zhiyun_learning_mcp.embeddings.call_llm", direct_call)
    embedder = AsyncEmbedder(
        SimpleNamespace(embeddings=FakeEmbeddingsEndpoint()), "model", dim=4)
    with pytest.raises(EmbeddingDimensionError, match="actual=3"):
        await embedder.embed("test")


async def test_vector_store_rejects_existing_dimension_mismatch():
    store = FakeAsyncVectorStore()
    await store.ensure_collection("chunks", dim=3, scalar_fields={})
    with pytest.raises(VectorDimensionMismatch, match="configured=4, actual=3"):
        await store.ensure_collection("chunks", dim=4, scalar_fields={})


async def test_milvus_store_rejects_existing_collection_without_phone():
    store = object.__new__(AsyncMilvusVectorStore)
    store.client = SimpleNamespace(describe_collection=lambda name: None)

    async def describe_collection(name):
        return {
            "fields": [
                {"name": "id"},
                {"name": "user_id"},
                {"name": "vector", "params": {"dim": 3}},
            ]
        }

    store.client.describe_collection = describe_collection
    with pytest.raises(VectorSchemaMismatch, match="phone"):
        await store._validate_collection("ma_chunks", 3, {"phone": "str"})
