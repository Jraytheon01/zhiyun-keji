# meeting_assistant/db.py
"""DB 访问：sync(pymysql, 仅 init_db 用) + async(aiomysql 池, repos 用)。"""
import json
import hashlib
import asyncio
import ssl
import pymysql
import aiomysql
from pymysql.constants import FIELD_TYPE
from aiomysql.cursors import DictCursor
from contextlib import asynccontextmanager, contextmanager
from .config import Settings


def _parse_json(value, dsc=None):
    # PyMySQL/aiomysql returns JSON columns as str/bytes; decode to Python objects.
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _parse_bool(value, dsc=None):
    """Decode MySQL TINYINT values without treating byte/string ``0`` as true."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("ascii")
    return int(value) != 0


def _build_conv():
    conv = pymysql.converters.conversions.copy()
    conv[FIELD_TYPE.JSON] = _parse_json          # JSON 列 → Python 对象
    conv[FIELD_TYPE.TINY] = _parse_bool           # TINYINT(1) → bool
    return conv


def _ssl_context(settings: Settings):
    if not settings.mysql_ssl_required:
        return None
    context = ssl.create_default_context(cafile=settings.mysql_ssl_ca or None)
    if not settings.mysql_ssl_verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


# ---------- async 池（repos 用）----------
_pool: "aiomysql.pool.Pool | None" = None


async def init_pool(settings: Settings, maxsize: int | None = None):
    """在事件循环里调一次，建全局连接池。"""
    global _pool
    if _pool is not None:
        return
    _pool = await aiomysql.create_pool(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        db=settings.mysql_database, charset="utf8mb4", autocommit=False,
        maxsize=maxsize or settings.db_pool_size,
        connect_timeout=getattr(settings, "db_connect_timeout_seconds", 10),
        pool_recycle=getattr(settings, "db_pool_recycle_seconds", 1800),
        init_command="SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
        cursorclass=DictCursor, conv=_build_conv(),
        ssl=_ssl_context(settings),
    )


class _Acquired:
    """async with aconn(s) as c, c.cursor() as cur: await cur.execute(...)"""
    def __init__(self, settings: Settings):
        self.s = settings

    async def __aenter__(self):
        assert _pool is not None, "先调 init_pool()"
        try:
            self.c = await asyncio.wait_for(
                _pool.acquire(),
                timeout=getattr(self.s, "db_acquire_timeout_seconds", 10),
            )
        except TimeoutError as exc:
            raise DbPoolBusy("timed out waiting for a MySQL connection") from exc
        return self.c

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                await self.c.commit()
            else:
                await self.c.rollback()
        finally:
            _pool.release(self.c)


def aconn(settings: Settings) -> _Acquired:
    return _Acquired(settings)


class RecordingLockBusy(RuntimeError):
    pass


class DbPoolBusy(RuntimeError):
    pass


@asynccontextmanager
async def advisory_lock(namespace: str, value, timeout_seconds: int = 1):
    """Cross-process MySQL advisory lock with an opaque, length-safe key."""
    assert _pool is not None, "先调 init_pool()"
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:44]
    lock_name = f"ma:{namespace}:{digest}"
    try:
        connection = await asyncio.wait_for(
            _pool.acquire(), timeout=10)
    except TimeoutError as exc:
        raise DbPoolBusy("timed out waiting for a MySQL lock connection") from exc
    cursor = await connection.cursor()
    acquired = False
    try:
        await cursor.execute("SELECT GET_LOCK(%s, %s) AS acquired",
                             (lock_name, int(timeout_seconds)))
        row = await cursor.fetchone()
        acquired = bool(row and row.get("acquired") == 1)
        if not acquired:
            raise RecordingLockBusy(f"{namespace} {value} is already being processed")
        yield
    finally:
        if acquired:
            try:
                await cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            except Exception:
                # Closing/recycling the connection also releases a MySQL advisory lock.
                connection.close()
        try:
            await cursor.close()
        except Exception:
            pass
        _pool.release(connection)


def recording_lock(recording_id: str, timeout_seconds: int = 1):
    return advisory_lock("recording", recording_id, timeout_seconds)


def fact_reconcile_lock(phone: str, timeout_seconds: int = 120):
    return advisory_lock("facts", phone, timeout_seconds)


async def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


# ---------- sync（仅 init_db DDL 用）----------
@contextmanager
def conn(settings: Settings):
    c = pymysql.connect(
        host=settings.mysql_host, port=settings.mysql_port,
        user=settings.mysql_user, password=settings.mysql_password,
        database=settings.mysql_database, charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False,
        conv=_build_conv(), ssl=_ssl_context(settings),
    )
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db(settings: Settings, seed_manual: bool = True):
    with conn(settings) as c, c.cursor() as cur:
        with open(__file__.replace("db.py", "schema.sql"), encoding="utf-8") as f:
            # MySQL driver can't run multi-statement scripts via execute() — split on ";\n"
            for stmt in f.read().split(";\n"):
                if stmt.strip():
                    cur.execute(stmt)
        if seed_manual:
            # seed __manual__ sentinel so add_memory() satisfies facts FK
            cur.execute("""INSERT IGNORE INTO recordings
                (recording_id, uploaded_at, has_audio, has_transcript, has_summary, ingestion_status)
                VALUES ('__manual__', NOW(), 0, 0, 0, 'n/a')""")
