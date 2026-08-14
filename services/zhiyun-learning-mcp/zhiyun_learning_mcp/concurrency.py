# meeting_assistant/concurrency.py
"""全局 LLM 并发闸 + 429/超时重试。

所有 DashScope 调用（embed/extract/judge）都过 call_llm()：
- async with 全局信号量（LLM_CONCURRENCY，默认 8）→ 在飞调用有上限
- 捕获 RateLimitError(429) / APIConnectionError / APITimeoutError → 指数退避重试（最多 5 次）
init_llm_sem() 必须在事件循环起来后调用（lifespan / asyncio.run 里）。
"""
import asyncio
import random

from openai import APITimeoutError, APIConnectionError, RateLimitError

_llm_sem: asyncio.Semaphore | None = None


def init_llm_sem(n: int) -> None:
    global _llm_sem
    _llm_sem = asyncio.Semaphore(n)


async def call_llm(api, **kw):
    """罩信号量 + 重试。api = client.embeddings 或 client.chat.completions（需有 async create）。"""
    assert _llm_sem is not None, "先调 init_llm_sem()"
    last = None
    for attempt in range(6):  # 初试 + 5 次重试
        try:
            async with _llm_sem:
                return await api.create(**kw)
        except (RateLimitError, APIConnectionError, APITimeoutError) as e:
            last = e
            if attempt == 5:
                break
            # 瞬时错误（连接/超时）只重试 2 次；429 重试满 5 次。
            # 退避必须在 semaphore 外，避免所有调用名额被睡眠任务占住。
            if not isinstance(e, RateLimitError) and attempt >= 2:
                break
            backoff = (0.5 * (2 ** attempt)) + random.random()
            await asyncio.sleep(backoff)
    raise last
