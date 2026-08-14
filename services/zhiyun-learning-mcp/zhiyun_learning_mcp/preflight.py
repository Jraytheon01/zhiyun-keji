"""Read-only deployment preflight for MySQL, Milvus, and required configuration."""
import asyncio
import json

from pymilvus import AsyncMilvusClient

from . import db
from .config import Settings
from .vector_store import _field_names, _vector_dimension


REQUIRED_COLUMNS = {
    "user_meeting_info": {
        "id", "phone", "content", "abstract_content", "abstract_text",
        "create_time", "title", "meeting_name", "record_url", "asr_url", "during",
        "status", "del_flag",
    },
    "user_meeting_content": {
        "id", "meet_id", "begin_time", "end_time", "speaker", "content", "code", "type",
    },
    "recordings": {"recording_id", "phone", "uploaded_at", "has_audio",
                   "has_transcript", "has_summary", "ingestion_status", "ingested_at",
                   "chunk_count", "fact_count", "todo_count", "embed_model", "extract_model"},
    "chunks": {"id", "recording_id", "phone", "chunk_index", "text", "kind",
               "speaker", "section", "token_len"},
    "facts": {"id", "recording_id", "phone", "meeting_id", "fact_text",
              "fact_type", "kind", "confidence", "subject", "detail", "date",
              "status", "superseded_by"},
    "todos": {"id", "recording_id", "phone", "task", "owner", "due", "status"},
    "mcp_api_keys": {"id", "key_hash", "phone", "active"},
    "ingest_jobs": {"id", "recording_id", "status", "payload", "locked_at"},
}


async def main():
    settings = Settings.load()
    report = {"mysql": {}, "milvus": {}, "ok": True}
    await db.init_pool(settings)
    try:
        async with db.aconn(settings) as connection, connection.cursor() as cursor:
            for table, required in REQUIRED_COLUMNS.items():
                await cursor.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=DATABASE() AND table_name=%s", (table,))
                actual = {row["column_name"] for row in await cursor.fetchall()}
                missing = sorted(required - actual)
                report["mysql"][table] = {"missing_columns": missing}
                report["ok"] = report["ok"] and not missing
    finally:
        await db.close_pool()

    milvus_kwargs = {"uri": settings.milvus_uri}
    if settings.milvus_db:
        milvus_kwargs["db"] = settings.milvus_db
    if settings.milvus_token:
        milvus_kwargs["token"] = settings.milvus_token
    client = AsyncMilvusClient(**milvus_kwargs)
    try:
        for kind in ("chunks", "facts"):
            name = settings.milvus_collection_prefix + kind
            exists = await client.has_collection(name)
            dimension = None
            missing_fields = []
            if exists:
                description = await client.describe_collection(name)
                dimension = _vector_dimension(description)
                missing_fields = sorted({"phone"} - _field_names(description))
            valid = not exists or (
                dimension == settings.embedding_dim and not missing_fields)
            report["milvus"][name] = {
                "exists": exists, "dimension": dimension,
                "expected_dimension": settings.embedding_dim,
                "missing_fields": missing_fields, "valid": valid,
            }
            report["ok"] = report["ok"] and valid
    finally:
        await client.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
