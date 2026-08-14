# meeting_assistant/services/memory.py
"""L3 memory service (async): distilled-fact access over FactsRepo + TodosRepo.
多租户：所有方法带 phone，仅在该租户的事实/待办上检索。
recall vs search_meetings: recall returns distilled facts (decisions/entities/
preferences) with provenance (recording_id+date); search_meetings returns raw
verbatim chunks. Tools in mcp_server.py map 1:1 onto these methods。
"""
import asyncio


async def _dicts(coro):
    return [dict(r) for r in await coro]


class MemoryService:
    def __init__(self, facts_repo, todos_repo, embedder):
        self.fr = facts_repo
        self.tr = todos_repo
        self.embedder = embedder

    async def recall(self, query, phone, top_k=5):
        """Semantic search over active distilled facts. Returns rows with score."""
        vec = await self.embedder.embed(query)
        return [dict(r) for r in await self.fr.search(vec, phone, top_k=top_k)]

    async def get_entity(self, name, phone):
        """All active facts about a project/person + relationships + open todos owned by them."""
        ents, rel, todos = await asyncio.gather(
            _dicts(self.fr.active_by_subject("entity", name, phone)),
            _dicts(self.fr.relationships_for(name, phone)),
            _dicts(self.tr.query(phone, status="open", owner=name)),
        )
        return {"entity": ents, "relationships": rel, "todos": todos}

    async def list_entities(self, type_, phone):
        """List active entities. v1: semantic-scan, filter by detail type when present."""
        rows = await self.fr.search(await self.embedder.embed(type_), phone, top_k=50)
        out = []
        for r in rows:
            if r["kind"] != "entity" or r["status"] != "active":
                continue
            detail = r["detail"] or {}
            t = detail.get("type", (detail.get("attrs") or {}).get("type"))
            if t in (None, type_):
                out.append(dict(r))
        return out

    async def add_memory(self, kind, subject, detail, phone):
        """Manually insert a fact (recording_id='__manual__'); returns new fact id."""
        embedding = await self.embedder.embed(subject)
        return await self.fr.insert({
            "recording_id": "__manual__",
            "phone": phone,
            "kind": kind,
            "subject": subject,
            "detail": detail,
            "embedding": embedding,
        })
