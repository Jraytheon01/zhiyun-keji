# meeting_assistant/vector_store.py
"""Vector storage abstraction (async)。Milvus 生产；Fake 测试用。
repos 依赖的接口就是这几个 async 方法；Milvus 细节封装在 AsyncMilvusVectorStore 里。"""
import math
import asyncio


class AsyncVectorStore:
    async def ensure_collection(self, name, dim, scalar_fields: dict): ...
    async def upsert(self, name, ids, vectors, scalars: dict): ...
        # ids: list[int]; vectors: list[list[float]]; scalars: {field: [vals]} aligned with ids
    async def search(self, name, vector, top_k=5, filters: dict | None = None): ...
        # returns list[(id, score)]
    async def delete(self, name, ids): ...
    async def delete_where(self, name, filters: dict): ...
    async def close(self): ...


class FakeAsyncVectorStore(AsyncVectorStore):
    def __init__(self):
        self.data = {}            # name -> {id: {"vector":[...], **scalars}}
        self.dimensions = {}
    async def ensure_collection(self, name, dim, scalar_fields):
        existing = self.dimensions.get(name)
        if existing is not None and existing != dim:
            raise VectorDimensionMismatch(name, dim, existing)
        self.dimensions[name] = dim
        self.data.setdefault(name, {})
    async def upsert(self, name, ids, vectors, scalars):
        coll = self.data.setdefault(name, {})
        for j, i in enumerate(ids):
            coll[i] = {"vector": vectors[j], **{k: v[j] for k, v in scalars.items()}}
    async def search(self, name, vector, top_k=5, filters=None):
        coll = self.data.get(name, {})
        scored = []
        for i, meta in coll.items():
            if not all(meta.get(k) == v for k, v in (filters or {}).items()):
                continue
            scored.append((i, self._cos(vector, meta["vector"])))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
    async def delete(self, name, ids):
        coll = self.data.get(name, {})
        for i in list(ids):
            coll.pop(i, None)
    async def delete_where(self, name, filters):
        coll = self.data.get(name, {})
        for i, meta in list(coll.items()):
            if all(meta.get(k) == v for k, v in filters.items()):
                coll.pop(i, None)
    async def close(self): pass
    @staticmethod
    def _cos(a, b):
        dot = sum(x*y for x, y in zip(a, b)); na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
        return dot/(na*nb) if na and nb else 0.0


class AsyncMilvusVectorStore(AsyncVectorStore):
    """pymilvus 3.0.0 AsyncMilvusClient adaptation（所有 I/O 方法 async）。

    API facts (verified against pymilvus 3.0.0 AsyncMilvusClient):
      - create_schema / prepare_index_params 为 sync 构建器；has_collection/create_collection/upsert/search/delete/close 为 async
      - upsert(collection_name, data=[{...}]); delete(collection_name, ids=[...]); search(...) returns [[{hit}]]，hit keys: "id","distance"
    """
    def __init__(self, uri, db="", prefix="ma_", token=""):
        from pymilvus import AsyncMilvusClient
        kwargs = {"uri": uri}
        if db:
            kwargs["db"] = db
        if token:
            kwargs["token"] = token
        self.client = AsyncMilvusClient(**kwargs)
        self.prefix = prefix
        self._ensure_locks = {}
    def _n(self, name): return f"{self.prefix}{name}"
    async def ensure_collection(self, name, dim, scalar_fields: dict):
        full = self._n(name)
        lock = self._ensure_locks.setdefault(full, asyncio.Lock())
        async with lock:
            if await self.client.has_collection(full):
                await self._validate_collection(full, dim, scalar_fields)
                return
            from pymilvus import DataType
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.INT64, is_primary=True)
            for f in scalar_fields:
                schema.add_field(f, DataType.VARCHAR, max_length=256)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
            index_params = self.client.prepare_index_params()
            index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
            try:
                await self.client.create_collection(
                    collection_name=full, schema=schema, index_params=index_params)
            except Exception:
                # Another worker process may have won the collection creation race.
                if not await self.client.has_collection(full):
                    raise
            await self._validate_collection(full, dim, scalar_fields)

    async def _validate_collection(self, full, dim, scalar_fields):
        description = await self.client.describe_collection(full)
        actual = _vector_dimension(description)
        if actual is None:
            raise RuntimeError(
                f"cannot determine vector dimension for existing Milvus collection {full}")
        if actual != dim:
            raise VectorDimensionMismatch(full, dim, actual)
        missing = sorted(set(scalar_fields) - _field_names(description))
        if missing:
            raise VectorSchemaMismatch(full, missing)
    async def upsert(self, name, ids, vectors, scalars):
        data = [{"id": int(ids[j]), **{k: v[j] for k, v in scalars.items()}, "vector": vectors[j]}
                for j in range(len(ids))]
        await self.client.upsert(self._n(name), data)
    async def search(self, name, vector, top_k=5, filters=None):
        expr = " and ".join(f'{k} == "{v}"' for k, v in (filters or {}).items()) or ""
        res = await self.client.search(self._n(name), data=[vector], anns_field="vector",
                                       limit=top_k, filter=expr or None)
        return [(hit["id"], hit["distance"]) for hit in res[0]]
    async def delete(self, name, ids):
        await self.client.delete(self._n(name), ids=[int(i) for i in ids])
    async def delete_where(self, name, filters):
        expr = " and ".join(f'{k} == "{v}"' for k, v in filters.items())
        await self.client.delete(self._n(name), filter=expr)
    async def close(self):
        await self.client.close()


def make_vector_store(settings):
    return AsyncMilvusVectorStore(
        settings.milvus_uri, settings.milvus_db,
        settings.milvus_collection_prefix, settings.milvus_token)


class VectorDimensionMismatch(RuntimeError):
    def __init__(self, collection: str, configured: int, actual: int):
        super().__init__(
            f"Milvus collection {collection} dimension mismatch: "
            f"configured={configured}, actual={actual}; use a compatible collection prefix "
            "or migrate/rebuild the vector collection explicitly")


class VectorSchemaMismatch(RuntimeError):
    def __init__(self, collection: str, missing_fields: list[str]):
        super().__init__(
            f"Milvus collection {collection} is missing required fields: "
            f"{', '.join(missing_fields)}; use a new collection prefix or migrate/rebuild "
            "the vector collection explicitly")


def _vector_dimension(description: dict) -> int | None:
    for field in description.get("fields", []):
        if field.get("name") != "vector":
            continue
        params = field.get("params") or field.get("type_params") or {}
        value = params.get("dim")
        if value is not None:
            return int(value)
    return None


def _field_names(description: dict) -> set[str]:
    return {field.get("name") for field in description.get("fields", []) if field.get("name")}
