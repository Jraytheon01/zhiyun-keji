# meeting_assistant/services/search.py
from ..ids import validate_recording_id


class SearchService:
    def __init__(self, chunks_repo, embedder):
        self.chunks_repo = chunks_repo; self.embedder = embedder

    async def search_meetings(self, query, phone, top_k=5, kind="all", recording_id=None):
        if recording_id is not None:
            validate_recording_id(recording_id)
        vec = await self.embedder.embed(query)
        k = None if kind == "all" else kind
        rows = await self.chunks_repo.search(vec, phone, top_k=top_k, kind=k, recording_id=recording_id)
        return [dict(r) for r in rows]
