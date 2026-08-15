from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def stable_vector_id(value: str) -> int:
    """Return a positive deterministic int64 id for Milvus."""
    raw = hashlib.sha256(value.encode("utf-8")).digest()[:8]
    return int.from_bytes(raw, "big") & 0x7FFF_FFFF_FFFF_FFFF


class LearningMemoryIndex:
    """Per-learner semantic index for confirmed/candidate learning memories.

    SQLite remains the authoritative ledger. Milvus stores only vectors and lookup
    metadata, so vector search can never silently become the source of truth.
    """

    def __init__(self, store):
        self.store = store
        self.api_key = os.environ.get("AI_EMBEDDING_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("AI_API_KEY") or ""
        self.base_url = os.environ.get("AI_EMBEDDING_BASE_URL") or os.environ.get("AI_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3"
        self.model = os.environ.get("AI_EMBEDDING_MODEL") or os.environ.get("EMBED_MODEL") or "doubao-embedding-text-240715"
        self.dim = int(os.environ.get("EMBEDDING_DIM", "2560"))
        self.collection = f"{os.environ.get('MILVUS_COLLECTION_PREFIX', 'zyk_')}learning_memory"
        self.uri = self._host_uri(os.environ.get("MILVUS_URI", "http://127.0.0.1:19530"))
        self.db_name = os.environ.get("MILVUS_DB", "")
        self.token = os.environ.get("MILVUS_TOKEN", "")
        self._client = None
        self._ready = False
        self.last_error = ""

    @staticmethod
    def _host_uri(uri: str) -> str:
        parsed = urlsplit(uri)
        if parsed.hostname not in {"milvus", "mysql"}:
            return uri
        port = parsed.port or 19530
        return urlunsplit((parsed.scheme or "http", f"127.0.0.1:{port}", parsed.path, parsed.query, parsed.fragment))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.uri)

    def _ensure(self) -> bool:
        if self._ready:
            return True
        if not self.configured:
            self.last_error = "Embedding 或 Milvus 未配置"
            return False
        try:
            from pymilvus import DataType, MilvusClient

            kwargs: dict[str, Any] = {"uri": self.uri}
            if self.db_name:
                kwargs["db_name"] = self.db_name
            if self.token:
                kwargs["token"] = self.token
            self._client = MilvusClient(**kwargs)
            if not self._client.has_collection(self.collection):
                schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
                schema.add_field("id", DataType.INT64, is_primary=True)
                schema.add_field("learner_id", DataType.VARCHAR, max_length=128)
                schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
                schema.add_field("course_id", DataType.VARCHAR, max_length=128)
                schema.add_field("knowledge_point", DataType.VARCHAR, max_length=256)
                schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dim)
                indexes = self._client.prepare_index_params()
                indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
                self._client.create_collection(
                    collection_name=self.collection,
                    schema=schema,
                    index_params=indexes,
                )
            self._ready = True
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._ready = False
            return False

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        request = Request(
            f"{self.base_url.rstrip('/')}/embeddings",
            data=json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding HTTP {exc.code}: {detail[:300]}") from exc
        vectors = [item["embedding"] for item in sorted(payload.get("data", []), key=lambda row: row.get("index", 0))]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding 返回数量与输入不一致")
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(f"Embedding 维度不匹配：配置 {self.dim}，实际 {len(vectors[0])}")
        return vectors

    def index_memories(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"indexed": 0, "ready": self._ready, "error": ""}
        if not self._ensure():
            raise RuntimeError(f"长期记忆索引不可用：{self.last_error}")
        try:
            texts = [f"{item.get('title','')}\n{item.get('content','')}\n知识点：{item.get('knowledge_point','')}" for item in items]
            vectors = self._embed(texts)
            rows = []
            for item, vector in zip(items, vectors):
                rows.append({
                    "id": int(item["vector_id"]),
                    "learner_id": str(item["learner_id"])[:128],
                    "memory_type": str(item.get("memory_type", "episodic"))[:64],
                    "course_id": str(item.get("course_id", ""))[:128],
                    "knowledge_point": str(item.get("knowledge_point", ""))[:256],
                    "vector": vector,
                })
            self._client.upsert(collection_name=self.collection, data=rows)
            self.store.mark_memories_indexed([int(row["id"]) for row in rows])
            self.last_error = ""
            return {"indexed": len(rows), "ready": True, "error": ""}
        except Exception as exc:
            self.last_error = str(exc)
            raise RuntimeError(f"长期记忆索引失败：{self.last_error}") from exc

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def search(self, learner_id: str, query: str, top_k: int = 6) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        if not self._ensure():
            raise RuntimeError(f"长期记忆检索不可用：{self.last_error}")
        try:
            vector = self._embed([query])[0]
            expr = f'learner_id == "{self._escape(learner_id)}"'
            results = self._client.search(
                collection_name=self.collection,
                data=[vector],
                anns_field="vector",
                filter=expr,
                limit=max(1, min(20, top_k)),
                output_fields=["memory_type", "course_id", "knowledge_point"],
            )
            scored = {int(hit["id"]): float(hit.get("distance", 0)) for hit in (results[0] if results else [])}
            rows = self.store.learning_memories_by_vector_ids(list(scored))
            for row in rows:
                row["similarity"] = round(scored.get(int(row["vector_id"]), 0), 4)
            return sorted(rows, key=lambda row: row.get("similarity", 0), reverse=True)
        except Exception as exc:
            self.last_error = str(exc)
            raise RuntimeError(f"长期记忆检索失败：{self.last_error}") from exc

    def delete_vectors(self, vector_ids: list[int]) -> None:
        if not vector_ids or not self._ensure():
            return
        try:
            values = ",".join(str(int(value)) for value in vector_ids)
            self._client.delete(collection_name=self.collection, filter=f"id in [{values}]")
        except Exception as exc:
            self.last_error = str(exc)

    def health(self) -> dict[str, Any]:
        ready = self._ensure()
        return {
            "configured": self.configured,
            "ready": ready,
            "collection": self.collection,
            "model": self.model,
            "error": self.last_error,
        }
