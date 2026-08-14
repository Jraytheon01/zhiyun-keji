from contextlib import asynccontextmanager
from types import SimpleNamespace

from zhiyun_learning_mcp.ingest_contracts import UpstreamMeetingSnapshot
from zhiyun_learning_mcp.ingest_worker import process_job, validate_worker_capacity


class FakeUpstream:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    async def fetch(self, phone, recording_id):
        assert phone == "13800000000"
        assert recording_id == "42"
        return self.snapshot


class FakeJobs:
    def __init__(self, processed):
        self.processed = processed
        self.done = []
        self.failed = []

    async def was_processed(self, recording_id, source_hash):
        return self.processed

    async def mark_done(self, job_id, source_hash, outcome):
        self.done.append((job_id, source_hash, outcome))

    async def mark_failed(self, *args):
        self.failed.append(args)


@asynccontextmanager
async def fake_recording_lock(*_args, **_kwargs):
    yield


def snapshot():
    return UpstreamMeetingSnapshot.model_validate({
        "meetingId": "42",
        "phone": "13800000000",
        "content": "逐字稿",
        "abstractContent": "摘要",
    })


async def test_worker_skips_same_successful_source(monkeypatch):
    calls = []

    async def fake_ingest(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("zhiyun_learning_mcp.ingest_worker.ingest", fake_ingest)
    monkeypatch.setattr("zhiyun_learning_mcp.ingest_worker.db.recording_lock", fake_recording_lock)
    jobs = FakeJobs(processed=True)
    job = SimpleNamespace(id=7, phone="13800000000", recording_id="42", attempts=1)
    await process_job(
        job, SimpleNamespace(ingest_max_attempts=5), jobs,
        FakeUpstream(snapshot()), None, None, None, None,
    )
    assert calls == []
    assert jobs.done[0][2] == "unchanged"
    assert jobs.failed == []


async def test_worker_processes_changed_source(monkeypatch):
    calls = []

    async def fake_ingest(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("zhiyun_learning_mcp.ingest_worker.ingest", fake_ingest)
    monkeypatch.setattr("zhiyun_learning_mcp.ingest_worker.db.recording_lock", fake_recording_lock)
    jobs = FakeJobs(processed=False)
    job = SimpleNamespace(id=8, phone="13800000000", recording_id="42", attempts=1)
    await process_job(
        job, SimpleNamespace(ingest_max_attempts=5), jobs,
        FakeUpstream(snapshot()), "embedder", "vector-store", "extractor", "judge",
    )
    assert len(calls) == 1
    assert jobs.done[0][2] == "processed"
    assert jobs.failed == []


async def test_worker_deletes_without_reading_upstream(monkeypatch):
    calls = []

    async def fake_delete(*args, **kwargs):
        calls.append((args, kwargs))

    class SourceMustNotBeRead:
        async def fetch(self, *_args):
            raise AssertionError("delete notification must not query deleted source rows")

    monkeypatch.setattr(
        "zhiyun_learning_mcp.ingest_worker.delete_ingested", fake_delete)
    monkeypatch.setattr(
        "zhiyun_learning_mcp.ingest_worker.db.recording_lock", fake_recording_lock)
    jobs = FakeJobs(processed=False)
    job = SimpleNamespace(
        id=9, phone="13800000000", recording_id="42", attempts=1,
        payload={"operation": "delete"},
    )
    await process_job(
        job, SimpleNamespace(ingest_max_attempts=5), jobs,
        SourceMustNotBeRead(), None, "vector-store", None, None,
    )
    assert len(calls) == 1
    assert calls[0][0][1] == "42"
    assert calls[0][1]["lock_already_held"] is True
    assert jobs.done[0][2] == "deleted"
    assert len(jobs.done[0][1]) == 64
    assert jobs.failed == []


async def test_worker_force_rebuild_bypasses_processed_hash(monkeypatch):
    calls = []

    async def fake_ingest(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("zhiyun_learning_mcp.ingest_worker.ingest", fake_ingest)
    monkeypatch.setattr(
        "zhiyun_learning_mcp.ingest_worker.db.recording_lock", fake_recording_lock)
    jobs = FakeJobs(processed=True)
    job = SimpleNamespace(
        id=10, phone="13800000000", recording_id="42", attempts=1,
        payload={"operation": "upsert", "force_rebuild": True})
    await process_job(
        job, SimpleNamespace(ingest_max_attempts=5), jobs,
        FakeUpstream(snapshot()), "embedder", "vector-store", "extractor", "judge")
    assert len(calls) == 1
    assert jobs.done[0][2] == "processed"


def test_worker_rejects_pool_too_small_for_nested_locks():
    settings = SimpleNamespace(
        ingest_worker_concurrency=4, db_pool_size=8,
        ingest_job_heartbeat_seconds=60, ingest_job_lease_seconds=600)
    try:
        validate_worker_capacity(settings)
    except ValueError as exc:
        assert "minimum is 9" in str(exc)
    else:
        raise AssertionError("unsafe pool sizing must fail at worker startup")


def test_worker_accepts_safe_pool_and_lease_sizing():
    validate_worker_capacity(SimpleNamespace(
        ingest_worker_concurrency=4, db_pool_size=14,
        ingest_job_heartbeat_seconds=60, ingest_job_lease_seconds=600))
