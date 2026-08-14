# meeting_assistant/repos/recordings_repo.py
from ..db import aconn


class RecordingsRepo:
    def __init__(self, settings): self.s = settings

    async def upsert(self, rid, fields: dict):
        cols = ["recording_id"] + list(fields.keys())
        vals = [rid] + list(fields.values())
        placeholders = ",".join(["%s"] * len(cols))
        updates = ",".join(f"{c}=VALUES({c})" for c in fields.keys())
        sql = f"INSERT INTO recordings ({','.join(cols)}) VALUES ({placeholders})"
        if updates:
            sql += f" ON DUPLICATE KEY UPDATE {updates}"
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(sql, vals)

    async def get(self, rid):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("SELECT * FROM recordings WHERE recording_id=%s", (rid,))
            return await cur.fetchone()

    async def list_all(self):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("SELECT * FROM recordings ORDER BY uploaded_at IS NULL, uploaded_at DESC")
            return await cur.fetchall()

    async def set_ingestion(self, rid, status, chunk_count=None, fact_count=None,
                            todo_count=None, embed_model=None, extract_model=None):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""UPDATE recordings SET ingestion_status=%s, chunk_count=%s,
                          fact_count=%s, todo_count=%s, embed_model=%s, extract_model=%s,
                          ingested_at=NOW() WHERE recording_id=%s""",
                        (status, chunk_count, fact_count, todo_count, embed_model, extract_model, rid))

    async def delete(self, rid):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("DELETE FROM recordings WHERE recording_id=%s", (rid,))
