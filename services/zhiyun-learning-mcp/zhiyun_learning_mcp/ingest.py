# meeting_assistant/ingest.py
"""Ingest one recording into the vector/structured index (async)。

数据源直接传入文本（调用方聚合 user_meeting_content，并读取 abstract_content）。
多租户：phone 贯穿 chunks/facts/todos。fact reconcile 用 asyncio.gather 并发。
"""
import asyncio
import logging

from .config import Settings
from . import db
from .repos.recordings_repo import RecordingsRepo
from .repos.chunks_repo import ChunksRepo
from .chunking import chunk_transcript, chunk_summary

logger = logging.getLogger(__name__)


class FactReconcileBatchError(RuntimeError):
    """At least one fact reconcile operation failed; the ingest must be retried."""


async def ingest(settings: Settings, rid: str, phone: str, transcript: str, summary: str,
                 embedder=None, vector_store=None, extractor=None, judge=None,
                 meeting_date=None, lock_already_held: bool = False):
    if not lock_already_held:
        timeout = getattr(settings, "ingest_recording_lock_timeout_seconds", 1)
        async with db.recording_lock(rid, timeout):
            return await ingest(
                settings, rid, phone, transcript, summary,
                embedder=embedder, vector_store=vector_store,
                extractor=extractor, judge=judge, meeting_date=meeting_date,
                lock_already_held=True,
            )
    repo = RecordingsRepo(settings)
    await repo.upsert(rid, {
        "phone": phone,
        "has_audio": True,
        "has_transcript": bool(transcript),
        "has_summary": bool(summary),
    })
    await repo.set_ingestion(rid, status="running")

    try:
        if embedder is None:
            from .embeddings import make_embedder
            embedder = make_embedder(settings)
        if vector_store is None:
            from .vector_store import make_vector_store
            vector_store = make_vector_store(settings)

        chunks_repo = ChunksRepo(settings, vector_store)
        all_chunks = []
        if transcript:
            all_chunks += chunk_transcript(transcript)
        if summary:
            all_chunks += chunk_summary(summary)

        vectors = await embedder.embed_batch([c["text"] for c in all_chunks])
        for c, v in zip(all_chunks, vectors):
            c["embedding"] = v
        await chunks_repo.replace_for(rid, phone, all_chunks)

        fact_count = todo_count = 0
        if extractor is not None:
            fact_count, todo_count = await _extract_and_reconcile(
                settings, rid, phone, transcript, summary, meeting_date,
                extractor, embedder, vector_store, judge)

        await repo.set_ingestion(rid, status="done", chunk_count=len(all_chunks),
                                 fact_count=fact_count, todo_count=todo_count,
                                 embed_model=getattr(embedder, "model", "fake"),
                                 extract_model=getattr(extractor, "model", None))
        return len(all_chunks), fact_count, todo_count
    except Exception:
        await repo.set_ingestion(rid, status="failed")
        raise


async def delete_ingested(settings: Settings, rid: str, vector_store=None,
                          lock_already_held: bool = False):
    """Delete all MCP-derived data for one globally unique meeting id.

    The upstream-owned ``user_meeting_info`` and ``user_meeting_content`` rows are
    deliberately untouched. Every operation is idempotent so a failed job can retry.
    """
    if not lock_already_held:
        timeout = getattr(settings, "ingest_recording_lock_timeout_seconds", 1)
        async with db.recording_lock(rid, timeout):
            return await delete_ingested(
                settings, rid, vector_store=vector_store, lock_already_held=True)

    if vector_store is None:
        from .vector_store import make_vector_store
        vector_store = make_vector_store(settings)

    from .repos.facts_repo import FactsRepo
    from .repos.todos_repo import TodosRepo

    # Repositories remove their MySQL rows and the Milvus rows sharing those IDs.
    # Keep this sequential: a retry safely continues after any partial failure.
    await ChunksRepo(settings, vector_store).delete_for(rid)
    await FactsRepo(settings, vector_store).delete_for(rid)
    await TodosRepo(settings).delete_for(rid)
    await RecordingsRepo(settings).delete(rid)


async def _extract_and_reconcile(settings, rid, phone, transcript, summary, meeting_date,
                                 extractor, embedder, vector_store, judge):
    from .repos.facts_repo import FactsRepo
    from .repos.todos_repo import TodosRepo

    data = await extractor.extract(transcript or "", summary or "", meeting_date)
    fr = FactsRepo(settings, vector_store)
    tr = TodosRepo(settings)

    fact_lock_timeout = getattr(settings, "ingest_fact_lock_timeout_seconds", 120)
    async with db.fact_reconcile_lock(phone, fact_lock_timeout):
        return await _reconcile_extracted(
            rid, phone, meeting_date, data, extractor, embedder, fr, tr, judge)


async def _reconcile_extracted(rid, phone, meeting_date, data, extractor,
                               embedder, fr, tr, judge):
    from .reconcile import apply_fact_reconcile, plan_fact_reconcile

    # 1) 收集所有 fact（kind, subject, detail, date）
    raw = []
    for p in data["projects"]:
        raw.append(("entity", p["name"], p, None))
    for p in data["people"]:
        raw.append(("entity", p["name"], p, None))
    for d in data["decisions"]:
        subj = d.get("about") or (d.get("decision") or "")[:20]
        raw.append(("decision", subj, d, _parse_date(d.get("date"), default=meeting_date)))
    for r in data["relationships"]:
        raw.append(("relationship", f"{r['a']}->{r['b']}", r, None))
    for p in data["preferences"]:
        raw.append(("preference", p["about"], p, None))
    for ins in data["insights"]:
        text = (ins.get("text") or "").strip()
        if text:
            raw.append(("insight", text[:200], ins, None))  # subject=text[:200] (NOT NULL + Milvus VARCHAR(256))

    # 2) 并发 embed 所有 subject（embed_batch 内部已 gather 子批次）
    subjects = [s for (_, s, _, _) in raw]
    vectors = await embedder.embed_batch(subjects) if subjects else []
    facts = [
        {"recording_id": rid, "phone": phone, "kind": k, "subject": s,
         "detail": d, "embedding": v, "date": dt}
        for (k, s, d, dt), v in zip(raw, vectors)
    ]

    # 3) 先并发完成所有只读 judge；任何模型失败都发生在删除旧数据之前。
    plans = await asyncio.gather(
        *[plan_fact_reconcile(fr, f, judge, exclude_recording_id=rid) for f in facts],
        return_exceptions=True,
    )
    failures = [plan for plan in plans if isinstance(plan, Exception)]
    for failure in failures:
        logger.error("reconcile 规划失败: %s: %s", type(failure).__name__, failure)

    if failures:
        raise FactReconcileBatchError(
            f"{len(failures)}/{len(plans)} 个 fact reconcile 子任务失败"
        ) from failures[0]

    # 4) 所有外部模型调用成功后，再替换本会议的派生事实/待办。
    await fr.delete_for(rid)
    await tr.delete_for(rid)
    results = []
    for fact, plan in zip(facts, plans):
        results.append(await apply_fact_reconcile(fr, fact, plan))
    fact_count = sum(result is not None for result in results)

    todos = [{"task": t["task"], "owner": t.get("owner"),
              "due": _parse_date(t.get("due"))} for t in data["todos"]]
    if todos:
        await tr.insert_many(rid, phone, todos)
    return fact_count, len(todos)


def _parse_date(s, default=None):
    """Coerce an LLM-produced date string to ISO YYYY-MM-DD, else `default`."""
    import re
    from datetime import datetime
    if not s or not isinstance(s, str):
        return default
    s = s.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    m = re.search(r"(\d{4})\D(\d{1,2})\D(\d{1,2})", s)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])).date().isoformat()
        except ValueError:
            pass
    return default
