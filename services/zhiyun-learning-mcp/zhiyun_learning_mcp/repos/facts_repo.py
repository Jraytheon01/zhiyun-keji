# meeting_assistant/repos/facts_repo.py
import asyncio
import json
from ..db import aconn

COLLECTION = "facts"
SCALAR_FIELDS = {"kind": "varchar", "subject": "varchar", "phone": "varchar"}


class FactsRepo:
    """MySQL holds fact metadata; Milvus (via async VectorStore) holds the subject vectors.
    多租户：所有写入带 phone，所有检索按 phone 过滤。
    On supersede the old vector is removed from Milvus (so it's never recalled) while the
    MySQL row is kept (status='superseded') for history/provenance."""
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
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("SELECT id FROM facts WHERE recording_id=%s", (rid,))
            ids = [r["id"] for r in await cur.fetchall()]
        # Facts collections created by the existing schema do not carry
        # recording_id. Delete vectors first so a Milvus failure leaves the
        # MySQL IDs available for a safe retry.
        if ids:
            await self.vs.delete(COLLECTION, ids)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("DELETE FROM facts WHERE recording_id=%s", (rid,))

    async def insert(self, f: dict):
        await self._ensure()
        detail_json = json.dumps(f["detail"], ensure_ascii=False)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""INSERT INTO facts
                (recording_id, phone, meeting_id, fact_text, fact_type,
                 kind, confidence, subject, detail, date, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')""",
                (f["recording_id"], f["phone"], f["recording_id"], detail_json,
                 f["kind"], f["kind"], f.get("confidence", 1.0), f["subject"], detail_json,
                 f.get("date")))
            fid = cur.lastrowid
        await self.vs.upsert(COLLECTION, [fid], [f["embedding"]],
                             {"kind": [f["kind"]], "subject": [f["subject"][:255]],
                              "phone": [str(f["phone"])]})
        return fid

    async def supersede(self, old_id, new_id):
        await self._ensure()
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("UPDATE facts SET status='superseded', superseded_by=%s WHERE id=%s",
                              (new_id, old_id))
        await self.vs.delete(COLLECTION, [old_id])

    async def update_detail(self, rid, detail):
        detail_json = json.dumps(detail, ensure_ascii=False)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("UPDATE facts SET detail=%s, fact_text=%s WHERE id=%s",
                              (detail_json, detail_json, rid))

    async def active_by_subject(self, kind, subject, phone):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""SELECT facts.*, fact_type AS kind FROM facts
                WHERE fact_type=%s AND subject=%s AND status='active'
                  AND phone=%s ORDER BY date DESC""", (kind, subject, phone))
            return await cur.fetchall()

    async def relationships_for(self, name, phone):
        """Active relationships where `name` is either endpoint (detail->>'a' or 'b')."""
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("""SELECT facts.*, fact_type AS kind FROM facts
                WHERE fact_type='relationship' AND status='active'
                AND phone=%s AND (detail->>'$.a' = %s OR detail->>'$.b' = %s)""",
                (phone, name, name))
            return await cur.fetchall()

    async def candidates(self, kind, embedding, phone, k=8,
                         exclude_recording_id=None):
        await self._ensure()
        # Semantic top-K among same-kind active facts, scoped to tenant.
        hits = await self.vs.search(COLLECTION, embedding, top_k=k * 2,
                                    filters={"kind": kind, "phone": str(phone)})
        if not hits:
            return []
        id2score = {i: s for i, s in hits}
        ids = list(id2score.keys())
        placeholders = ",".join(["%s"] * len(ids))
        async with aconn(self.s) as c, c.cursor() as cur:
            query = (f"SELECT facts.*, fact_type AS kind FROM facts "
                     f"WHERE id IN ({placeholders}) AND status='active' AND phone=%s")
            params = [*ids, phone]
            if exclude_recording_id is not None:
                query += " AND recording_id<>%s"
                params.append(exclude_recording_id)
            await cur.execute(query, params)
            return (await cur.fetchall())[:k]

    async def search(self, embedding, phone, top_k=5, kind=None):
        await self._ensure()
        filters = {"phone": str(phone)}
        if kind:
            filters["kind"] = kind
        hits = await self.vs.search(COLLECTION, embedding, top_k=top_k, filters=filters)
        if not hits:
            return []
        id2score = {i: s for i, s in hits}
        ids = list(id2score.keys())
        placeholders = ",".join(["%s"] * len(ids))
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(f"SELECT facts.*, fact_type AS kind FROM facts WHERE id IN ({placeholders}) AND status='active' AND phone=%s",
                        (*ids, phone))
            rows = await cur.fetchall()
        for r in rows:
            r["score"] = id2score.get(r["id"], 0.0)
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows
