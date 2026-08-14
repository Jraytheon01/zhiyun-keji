"""Create the isolated Zhiyun Learning Milvus database when missing."""

from pymilvus import MilvusClient

from .config import Settings


def ensure_database(settings: Settings) -> bool:
    if not settings.milvus_db:
        raise RuntimeError("MILVUS_DB must be configured for the education service")
    kwargs = {"uri": settings.milvus_uri}
    if settings.milvus_token:
        kwargs["token"] = settings.milvus_token
    client = MilvusClient(**kwargs)
    try:
        existing = set(client.list_databases())
        if settings.milvus_db in existing:
            return False
        client.create_database(settings.milvus_db)
        return True
    finally:
        client.close()


if __name__ == "__main__":
    settings = Settings.load()
    created = ensure_database(settings)
    print(f"Milvus database {settings.milvus_db}: {'created' if created else 'already exists'}")
