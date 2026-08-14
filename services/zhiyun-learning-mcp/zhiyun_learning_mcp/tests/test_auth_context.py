import asyncio
from types import SimpleNamespace

from zhiyun_learning_mcp import auth
from zhiyun_learning_mcp.db import _parse_bool


def test_mysql_tinyint_bool_decoder_handles_zero_bytes_correctly():
    assert _parse_bool(b"0") is False
    assert _parse_bool("0") is False
    assert _parse_bool(0) is False
    assert _parse_bool(b"1") is True


async def test_concurrent_tasks_keep_tenant_context_isolated():
    async def one(key_id, phone):
        token = auth.set_principal(auth.Principal(key_id, phone))
        try:
            await asyncio.sleep(0)
            principal = auth.current_principal()
            return auth.current_phone(), principal.phone
        finally:
            auth._principal_ctx.reset(token)

    assert await asyncio.gather(
        one(1, "13800001001"),
        one(2, "13800001002"),
        one(3, "13800001003"),
    ) == [
        ("13800001001", "13800001001"),
        ("13800001002", "13800001002"),
        ("13800001003", "13800001003"),
    ]


def test_missing_principal_never_falls_back_to_default_user():
    settings = SimpleNamespace()
    try:
        auth.current_phone(settings)
    except PermissionError as exc:
        assert "authenticated principal" in str(exc)
    else:
        raise AssertionError("missing principal must fail closed")


class FakeKeyRepo:
    async def verify(self, key):
        if key == "valid-key":
            return {"key_id": 7, "phone": "13800001001"}
        return None


async def _call_middleware(headers, repo=None):
    seen = {}

    async def app(_scope, _receive, send):
        principal = auth.current_principal()
        seen["principal"] = principal
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = []

    async def send(message):
        sent.append(message)

    middleware = auth.ApiKeyMiddleware(
        app, SimpleNamespace(),
        repo or FakeKeyRepo())
    await middleware({"type": "http", "headers": headers}, None, send)
    return sent, seen


async def test_middleware_rejects_missing_key_even_when_legacy_setting_is_false():
    sent, seen = await _call_middleware([])
    assert sent[0]["status"] == 401
    assert seen == {}


async def test_middleware_rejects_invalid_key():
    sent, seen = await _call_middleware([(b"authorization", b"Bearer invalid")])
    assert sent[0]["status"] == 401
    assert seen == {}


async def test_middleware_binds_principal_from_bearer_key():
    sent, seen = await _call_middleware(
        [(b"authorization", b"Bearer valid-key")])
    assert sent[0]["status"] == 200
    assert seen["principal"] == auth.Principal(
        key_id=7, phone="13800001001")


async def test_middleware_returns_503_when_auth_database_is_unavailable():
    class BrokenRepo:
        async def verify(self, _key):
            raise TimeoutError("pool exhausted")

    sent, seen = await _call_middleware(
        [(b"authorization", b"Bearer valid-key")], BrokenRepo())
    assert sent[0]["status"] == 503
    assert seen == {}
