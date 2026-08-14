# meeting_assistant/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    mysql_ssl_required: bool
    mysql_ssl_verify: bool
    mysql_ssl_ca: str
    milvus_uri: str
    milvus_db: str
    milvus_token: str
    milvus_collection_prefix: str
    ai_api_key: str
    ai_base_url: str
    embed_model: str
    embedding_dim: int
    extract_model: str
    llm_timeout_seconds: float
    mcp_port: int
    ingest_api_port: int
    llm_concurrency: int
    db_pool_size: int
    db_acquire_timeout_seconds: float
    db_connect_timeout_seconds: int
    db_pool_recycle_seconds: int
    recording_concurrency: int
    ingest_poll_interval_seconds: float
    ingest_max_attempts: int
    ingest_worker_concurrency: int
    ingest_job_lease_seconds: int
    ingest_job_heartbeat_seconds: int
    ingest_recording_lock_timeout_seconds: int
    ingest_fact_lock_timeout_seconds: int

    @classmethod
    def load(cls):
        return cls(
            mysql_host=os.environ.get("MYSQL_HOST", "localhost"),
            mysql_port=int(os.environ.get("MYSQL_PORT", "3306")),
            mysql_user=os.environ["MYSQL_USER"],
            mysql_password=os.environ["MYSQL_PASSWORD"],
            mysql_database=os.environ["MYSQL_DATABASE"],
            mysql_ssl_required=os.environ.get("MYSQL_SSL_REQUIRED", "false").lower() == "true",
            mysql_ssl_verify=os.environ.get("MYSQL_SSL_VERIFY", "true").lower() == "true",
            mysql_ssl_ca=os.environ.get("MYSQL_SSL_CA", ""),
            milvus_uri=os.environ.get("MILVUS_URI", "http://localhost:19530"),
            milvus_db=os.environ.get("MILVUS_DB", ""),
            milvus_token=os.environ.get("MILVUS_TOKEN", ""),
            milvus_collection_prefix=os.environ.get("MILVUS_COLLECTION_PREFIX", "zyk_learning_"),
            ai_api_key=(os.environ.get("AI_API_KEY")
                        or os.environ.get("ARK_API_KEY")
                        or os.environ.get("DASHSCOPE_API_KEY", "")),
            ai_base_url=(os.environ.get("AI_BASE_URL")
                         or os.environ.get("ARK_BASE_URL")
                         or os.environ.get("DASHSCOPE_BASE")
                         or "https://ark.cn-beijing.volces.com/api/v3"),
            embed_model=os.environ.get("EMBED_MODEL", "doubao-embedding-text-240715"),
            embedding_dim=int(os.environ.get("EMBEDDING_DIM", "2560")),
            extract_model=os.environ.get("EXTRACT_MODEL", "deepseek-v4-flash-ga-260731"),
            llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", "120")),
            mcp_port=int(os.environ.get("MCP_PORT", "8768")),
            ingest_api_port=int(os.environ.get("INGEST_API_PORT", "8769")),
            llm_concurrency=int(os.environ.get("LLM_CONCURRENCY", "8")),
            db_pool_size=int(os.environ.get("DB_POOL_SIZE", "10")),
            db_acquire_timeout_seconds=max(
                0.1, float(os.environ.get("DB_ACQUIRE_TIMEOUT_SECONDS", "10"))),
            db_connect_timeout_seconds=max(
                1, int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "10"))),
            db_pool_recycle_seconds=max(
                60, int(os.environ.get("DB_POOL_RECYCLE_SECONDS", "1800"))),
            recording_concurrency=int(os.environ.get("RECORDING_CONCURRENCY", "4")),
            ingest_poll_interval_seconds=float(os.environ.get("INGEST_POLL_INTERVAL_SECONDS", "2")),
            ingest_max_attempts=int(os.environ.get("INGEST_MAX_ATTEMPTS", "5")),
            ingest_worker_concurrency=max(1, int(os.environ.get("INGEST_WORKER_CONCURRENCY", "2"))),
            ingest_job_lease_seconds=max(
                60, int(os.environ.get("INGEST_JOB_LEASE_SECONDS", "600"))),
            ingest_job_heartbeat_seconds=max(
                10, int(os.environ.get("INGEST_JOB_HEARTBEAT_SECONDS", "60"))),
            ingest_recording_lock_timeout_seconds=max(
                0, int(os.environ.get("INGEST_RECORDING_LOCK_TIMEOUT_SECONDS", "1"))),
            ingest_fact_lock_timeout_seconds=max(
                1, int(os.environ.get("INGEST_FACT_LOCK_TIMEOUT_SECONDS", "120"))),
        )
