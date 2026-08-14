# meeting_assistant/repos/chunks_repo.py
import asyncio
import random
import pymysql
from ..db import aconn

COLLECTION = "chunks"
# phone 作为 Milvus 标量字段，检索时按租户过滤。
SCALAR_FIELDS = {"kind": "varchar", "recording_id": "varchar", "phone": "varchar"}


class ChunksRepo:
    """MySQL holds metadata; Milvus (via async VectorStore) holds the vectors.
    多租户：所有写入带 phone，所有检索按 phone 过滤。"""
    def __init__(self, settings, vector_store):
        self.s = settings; self.vs = vector_store; self._ensured = False
        self._ensure_lock = asyncio.Lock()

    async def _ensure(self):
        if not self._ensured:
            async with self._ensure_lock:
                if not self._ensured:
                    await self.vs.ensure_collection(
                        COLLECTION, dim=self.s.embedding_dim, scalar_fields=SCALAR_FIELDS)
                    self._ensured = True

    async def delete_for(self, rid):
        await self._ensure()
        # Milvus carries recording_id for chunks, so scalar deletion also
        # removes any orphan vector left by an earlier partial failure.
        await self.vs.delete_where(COLLECTION, {"recording_id": rid})
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("DELETE FROM chunks WHERE recording_id=%s", (rid,))

    async def insert_many(self, rid, phone, chunks: list[dict]):
        """Compatibility alias; ingest should use replace_for for full rebuilds."""
        return await self.replace_for(rid, phone, chunks)

    async def replace_for(self, rid, phone, chunks: list[dict]):
        """Atomically replace MySQL rows, then rebuild all vectors for the recording."""
        await self._ensure()
        phone = str(phone)
        ids = await self._replace_mysql_with_retry(rid, phone, chunks)
        # Delete by scalar filter rather than by the IDs currently visible in MySQL.
        # This also repairs orphan vectors left by an earlier partial failure.
        await self.vs.delete_where(
            COLLECTION, {"recording_id": rid, "phone": phone})
        if ids:
            await self.vs.upsert(COLLECTION, ids, [c["embedding"] for c in chunks],
                                 {"kind": [c["kind"] for c in chunks],
                                  "recording_id": [rid] * len(chunks),
                                  "phone": [phone] * len(chunks)})

    async def _replace_mysql_with_retry(self, rid, phone, chunks, attempts=4):
        """Retry the complete transaction on MySQL deadlock/lock timeout."""
        for attempt in range(attempts):
            try:
                ids = []
                async with aconn(self.s) as c, c.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM chunks WHERE recording_id=%s", (rid,))
                    for c_dict in chunks:
                        await cur.execute("""INSERT INTO chunks
                            (recording_id, phone, kind, chunk_index, text, speaker,
                             section, token_len)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (rid, phone, c_dict["kind"], c_dict.get("ordinal"),
                             c_dict["text"], c_dict.get("speaker"),
                             c_dict.get("section"), len(c_dict["text"]) // 3))
                        ids.append(cur.lastrowid)
                return ids
            except pymysql.err.OperationalError as exc:
                if exc.args[0] not in (1205, 1213) or attempt == attempts - 1:
                    raise
                await asyncio.sleep((0.05 * (2 ** attempt)) + random.random() * 0.05)
        raise AssertionError("unreachable")

    async def search(self, vector, phone, top_k=5, kind=None, recording_id=None):
        await self._ensure()
        filters = {"phone": str(phone)}
        if kind:
            filters["kind"] = kind
        if recording_id:
            filters["recording_id"] = recording_id
        hits = await self.vs.search(COLLECTION, vector, top_k=top_k, filters=filters)
        if not hits:
            return []
        id2score = {i: s for i, s in hits}
        ids = list(id2score.keys())
        placeholders = ",".join(["%s"] * len(ids))
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(f"""SELECT id, recording_id, kind, chunk_index AS ordinal,
                                   text, speaker, section
                            FROM chunks WHERE id IN ({placeholders}) AND phone=%s""",
                        (*ids, phone))
            rows = await cur.fetchall()
        for r in rows:
            r["score"] = id2score.get(r["id"], 0.0)
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows
