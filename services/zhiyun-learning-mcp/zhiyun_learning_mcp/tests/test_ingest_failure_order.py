from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from zhiyun_learning_mcp.ingest import FactReconcileBatchError, _reconcile_extracted, ingest


class FakeRecordingsRepo:
    statuses = []

    def __init__(self, _settings):
        pass

    async def upsert(self, *_args, **_kwargs):
        pass

    async def set_ingestion(self, _rid, status, **_kwargs):
        self.statuses.append(status)


class FakeChunksRepo:
    replace_called = False

    def __init__(self, _settings, _vector_store):
        pass

    async def replace_for(self, *_args, **_kwargs):
        self.replace_called = True


class FailingEmbedder:
    model = "failing"

    async def embed_batch(self, _texts):
        raise RuntimeError("embedding unavailable")


@asynccontextmanager
async def fake_lock(*_args, **_kwargs):
    yield


async def test_embedding_failure_does_not_replace_existing_chunks(monkeypatch):
    FakeRecordingsRepo.statuses = []
    FakeChunksRepo.replace_called = False
    monkeypatch.setattr("zhiyun_learning_mcp.ingest.RecordingsRepo", FakeRecordingsRepo)
    monkeypatch.setattr("zhiyun_learning_mcp.ingest.ChunksRepo", FakeChunksRepo)
    monkeypatch.setattr("zhiyun_learning_mcp.ingest.db.recording_lock", fake_lock)

    settings = SimpleNamespace(ingest_recording_lock_timeout_seconds=1)
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await ingest(settings, "42", "13800000000", "张三：逐字稿", "摘要",
                     embedder=FailingEmbedder(), vector_store=object())

    assert FakeChunksRepo.replace_called is False
    assert FakeRecordingsRepo.statuses == ["running", "failed"]


async def test_judge_failure_does_not_delete_existing_facts_or_todos():
    class Facts:
        deleted = False

        async def candidates(self, *_args, **_kwargs):
            return []

        async def delete_for(self, _rid):
            self.deleted = True

    class Todos:
        deleted = False

        async def delete_for(self, _rid):
            self.deleted = True

    class Embedder:
        async def embed_batch(self, texts):
            return [[0.0] for _ in texts]

    async def failing_judge(_candidates, _fact):
        raise RuntimeError("judge unavailable")

    facts = Facts()
    todos = Todos()
    data = {
        "projects": [{"name": "项目A"}], "people": [], "decisions": [],
        "relationships": [], "preferences": [], "insights": [], "todos": [],
    }
    with pytest.raises(FactReconcileBatchError):
        await _reconcile_extracted(
            "42", "13800000000", "2026-08-11", data, None,
            Embedder(), facts, todos, failing_judge)

    assert facts.deleted is False
    assert todos.deleted is False
