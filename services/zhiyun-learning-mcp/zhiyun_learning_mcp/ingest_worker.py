"""Persistent ingest worker: notification -> direct MySQL snapshot -> derived data."""
import asyncio
import hashlib
import logging
import random
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from openai import AsyncOpenAI

from . import db
from .concurrency import init_llm_sem
from .config import Settings
from .embeddings import make_embedder
from .extractor import make_extractor
from .ingest import delete_ingested, ingest
from .reconcile import make_judge
from .repos.ingest_jobs_repo import IngestJobsRepo
from .meeting_source_repo import MeetingSourceRepo
from .vector_store import make_vector_store

logger = logging.getLogger(__name__)


def validate_worker_capacity(settings) -> None:
    """Prevent pool deadlocks caused by nested recording and fact locks."""
    workers = settings.ingest_worker_concurrency
    minimum = (2 * workers) + 1
    if settings.db_pool_size < minimum:
        raise ValueError(
            f"DB_POOL_SIZE={settings.db_pool_size} is too small for "
            f"INGEST_WORKER_CONCURRENCY={workers}; minimum is {minimum}, "
            f"recommended is at least {(3 * workers) + 2}")
    if settings.ingest_job_heartbeat_seconds * 2 >= settings.ingest_job_lease_seconds:
        raise ValueError(
            "INGEST_JOB_LEASE_SECONDS must be greater than twice "
            "INGEST_JOB_HEARTBEAT_SECONDS")


async def _heartbeat_job(job_id, jobs, interval_seconds):
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await jobs.heartbeat(job_id)
        except Exception:
            logger.exception("ingest job heartbeat failed: job=%s", job_id)


async def process_job(job, settings, jobs, source, embedder, vector_store, extractor, judge):
    heartbeat = None
    if hasattr(jobs, "heartbeat"):
        heartbeat = asyncio.create_task(_heartbeat_job(
            job.id, jobs,
            getattr(settings, "ingest_job_heartbeat_seconds", 60)))
    try:
        operation = (getattr(job, "payload", None) or {}).get("operation", "upsert")
        if operation == "delete":
            lock_timeout = getattr(settings, "ingest_recording_lock_timeout_seconds", 1)
            async with db.recording_lock(job.recording_id, lock_timeout):
                await delete_ingested(
                    settings, job.recording_id, vector_store=vector_store,
                    lock_already_held=True,
                )
                delete_hash = hashlib.sha256(
                    f"delete:{job.recording_id}".encode("utf-8")).hexdigest()
                await jobs.mark_done(job.id, delete_hash, outcome="deleted")
            logger.info("ingest delete completed: job=%s recording=%s",
                        job.id, job.recording_id)
            return

        snapshot = await source.fetch(job.phone, job.recording_id)
        source_hash = snapshot.source_hash()
        force_rebuild = bool(
            (getattr(job, "payload", None) or {}).get("force_rebuild", False))
        lock_timeout = getattr(settings, "ingest_recording_lock_timeout_seconds", 1)
        async with db.recording_lock(snapshot.recording_id, lock_timeout):
            # The hash check is deliberately inside the recording lock. Two duplicate
            # notifications may both be claimed, but only the first performs writes.
            if (not force_rebuild and
                    await jobs.was_processed(snapshot.recording_id, source_hash)):
                await jobs.mark_done(job.id, source_hash, outcome="unchanged")
                logger.info("ingest skipped unchanged source: job=%s recording=%s",
                            job.id, snapshot.recording_id)
                return
            await ingest(
                settings, snapshot.recording_id, snapshot.phone,
                snapshot.transcript or "", snapshot.summary or "",
                embedder=embedder, vector_store=vector_store,
                extractor=extractor, judge=judge,
                meeting_date=snapshot.meeting_date, lock_already_held=True,
            )
            await jobs.mark_done(job.id, source_hash, outcome="processed")
    except asyncio.CancelledError:
        await jobs.mark_failed(job.id, "worker cancelled", retry=True, delay_seconds=0)
        raise
    except Exception as exc:
        retry = job.attempts < settings.ingest_max_attempts
        delay = min(30 * (2 ** max(job.attempts - 1, 0)), 1800)
        await jobs.mark_failed(job.id, f"{type(exc).__name__}: {exc}", retry, delay)
        logger.exception("ingest job failed: id=%s recording_id=%s", job.id, job.recording_id)
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)


async def worker_slot(slot, settings, jobs, source, embedder, vector_store, extractor, judge):
    while True:
        job = await jobs.claim_next()
        if job is None:
            await asyncio.sleep(
                settings.ingest_poll_interval_seconds * (1 + random.random() * 0.25))
            continue
        logger.info("worker slot %s claimed job=%s recording=%s", slot, job.id, job.recording_id)
        await process_job(
            job, settings, jobs, source,
            embedder, vector_store, extractor, judge,
        )


async def main(run_once: bool = False):
    logging.basicConfig(level=logging.INFO)
    settings = Settings.load()
    validate_worker_capacity(settings)
    await db.init_pool(settings)
    init_llm_sem(settings.llm_concurrency)
    aio = AsyncOpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url,
                      timeout=settings.llm_timeout_seconds, max_retries=0)
    vector_store = make_vector_store(settings)
    embedder = make_embedder(settings, client=aio)
    extractor = make_extractor(settings, client=aio)
    judge = make_judge(settings, client=aio)
    jobs = IngestJobsRepo(settings)
    source = MeetingSourceRepo(settings)
    try:
        if run_once:
            job = await jobs.claim_next()
            if job is None:
                logger.info("no pending ingest job")
                return
            await process_job(
                job, settings, jobs, source,
                embedder, vector_store, extractor, judge,
            )
            return
        await asyncio.gather(*[
            worker_slot(slot, settings, jobs, source,
                        embedder, vector_store, extractor, judge)
            for slot in range(settings.ingest_worker_concurrency)
        ])
    finally:
        await vector_store.close()
        await aio.close()
        await db.close_pool()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Meeting Assistant ingest worker")
    parser.add_argument(
        "--once", action="store_true",
        help="process at most one available job and exit (local E2E/debugging)")
    args = parser.parse_args()
    asyncio.run(main(run_once=args.once))
