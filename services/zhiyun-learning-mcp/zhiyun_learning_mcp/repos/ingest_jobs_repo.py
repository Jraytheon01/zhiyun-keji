"""Persistent inbox/job repository for reliable notification processing."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..db import aconn
from ..ingest_contracts import IngestNotification


@dataclass
class IngestJob:
    id: int
    recording_id: str
    phone: str
    attempts: int
    payload: dict


class IngestJobsRepo:
    def __init__(self, settings):
        self.s = settings

    async def enqueue(self, notification: IngestNotification) -> int:
        payload = notification.model_dump(mode="json", by_alias=False)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""INSERT INTO ingest_jobs
                (recording_id, phone, transcript_status, summary_status, payload)
                VALUES (%s,%s,%s,%s,%s)""",
                (notification.meeting_id, notification.phone,
                 notification.transcript_status.value, notification.summary_status.value,
                 json.dumps(payload, ensure_ascii=False)))
            return int(cur.lastrowid)

    async def claim_next(self) -> IngestJob | None:
        lease_seconds = getattr(self.s, "ingest_job_lease_seconds", 600)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""SELECT id, recording_id, phone, attempts, payload
                FROM ingest_jobs
                WHERE ((status IN ('pending','retry')
                        AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()))
                       OR (status='processing' AND locked_at < DATE_SUB(NOW(), INTERVAL %s SECOND)))
                ORDER BY id
                LIMIT 1 FOR UPDATE""", (lease_seconds,))
            row = await cur.fetchone()
            if not row:
                return None
            await cur.execute("""UPDATE ingest_jobs
                SET status='processing', attempts=attempts+1, locked_at=NOW(), last_error=NULL
                WHERE id=%s""", (row["id"],))
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return IngestJob(
                id=int(row["id"]), recording_id=row["recording_id"], phone=row["phone"],
                attempts=int(row["attempts"]) + 1, payload=payload,
            )

    async def heartbeat(self, job_id: int) -> None:
        """Renew a processing lease without changing attempts or outcome."""
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(
                "UPDATE ingest_jobs SET locked_at=NOW() "
                "WHERE id=%s AND status='processing'", (job_id,))

    async def was_processed(self, recording_id: str, source_hash: str) -> bool:
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""SELECT 1 FROM ingest_jobs
                WHERE recording_id=%s AND source_hash=%s
                  AND status='done' AND outcome='processed'
                LIMIT 1""", (recording_id, source_hash))
            return await cur.fetchone() is not None

    async def mark_done(self, job_id: int, source_hash: str, outcome: str) -> None:
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""UPDATE ingest_jobs
                SET status='done', processed_at=NOW(), locked_at=NULL,
                    next_attempt_at=NULL, last_error=NULL,
                    source_hash=%s, outcome=%s
                WHERE id=%s""", (source_hash, outcome, job_id))

    async def mark_failed(self, job_id: int, error: str, retry: bool, delay_seconds: int = 30) -> None:
        status = "retry" if retry else "failed"
        next_at = datetime.now() + timedelta(seconds=delay_seconds) if retry else None
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""UPDATE ingest_jobs
                SET status=%s, locked_at=NULL, next_attempt_at=%s, last_error=%s
                WHERE id=%s""", (status, next_at, error[:4000], job_id))
