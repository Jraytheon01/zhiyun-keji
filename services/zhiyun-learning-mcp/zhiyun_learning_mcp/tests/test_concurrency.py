# tests/test_concurrency.py
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import RateLimitError

from zhiyun_learning_mcp import concurrency


async def test_call_llm_retries_on_429_then_succeeds(monkeypatch):
    concurrency.init_llm_sem(8)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())  # 跳过真实退避

    calls = {"n": 0}
    good = MagicMock()
    good.choices = [MagicMock(message=MagicMock(content="ok"))]

    async def fake_create(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            resp = MagicMock(status_code=429)
            raise RateLimitError("rate limited", response=resp, body=None)
        return good

    api = MagicMock()
    api.create = fake_create

    out = await concurrency.call_llm(api, model="x", messages=[])
    assert out is good
    assert calls["n"] == 3  # 初试 + 2 次 429 = 第 3 次成功


async def test_call_llm_gives_up_after_max_retries(monkeypatch):
    concurrency.init_llm_sem(8)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    async def always_429(**kw):
        raise RateLimitError("rate", response=MagicMock(status_code=429), body=None)

    api = MagicMock()
    api.create = always_429

    with pytest.raises(RateLimitError):
        await concurrency.call_llm(api, model="x", messages=[])


async def test_retry_backoff_does_not_hold_llm_slot(monkeypatch):
    concurrency.init_llm_sem(1)
    slot_was_free = []

    async def fake_sleep(_delay):
        slot_was_free.append(not concurrency._llm_sem.locked())

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    calls = 0

    async def fail_once(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimitError(
                "rate", response=MagicMock(status_code=429), body=None)
        return MagicMock()

    api = MagicMock(create=fail_once)
    await concurrency.call_llm(api, model="x", messages=[])

    assert slot_was_free == [True]
