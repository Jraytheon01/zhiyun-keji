# meeting_assistant/repos/api_keys_repo.py
"""Read-only mcp_api_keys lookup: one key maps to one phone tenant."""
import hashlib

from ..db import aconn


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


class ApiKeysRepo:
    def __init__(self, settings):
        self.s = settings

    async def verify(self, plaintext: str) -> dict | None:
        """Read and verify a key, returning its trusted phone principal."""
        if not plaintext:
            return None
        h = hash_key(plaintext)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(
                "SELECT id, phone FROM mcp_api_keys "
                "WHERE key_hash=%s AND active=1 AND phone IS NOT NULL AND phone<>''",
                (h,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return {"key_id": int(row["id"]), "phone": str(row["phone"])}
