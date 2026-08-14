"""Zhiyun Keji education-domain MCP server.

The server intentionally exposes course evidence and controlled learning-dialogue
write-back only. Meeting-domain automation tools do not belong in this product.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastmcp import FastMCP
from openai import AsyncOpenAI

from .auth import current_phone
from .config import Settings
from .concurrency import init_llm_sem
from .db import close_pool, init_pool
from .embeddings import AsyncEmbedder
from .ids import InvalidRecordingId
from .repos.api_keys_repo import ApiKeysRepo
from .repos.chunks_repo import ChunksRepo
from .repos.facts_repo import FactsRepo
from .repos.todos_repo import TodosRepo
from .services.education_callback import (
    complete_learning_interaction as write_learning_interaction,
    get_learning_context as read_learning_context,
)
from .services.lookup import FileNotGenerated, LookupService, RecordingNotFound
from .services.memory import MemoryService
from .services.search import SearchService
from .user_meeting_repo import UserMeetingRepo
from .vector_store import make_vector_store


settings = Settings.load()
courses = lookup = search = memory = None


@asynccontextmanager
async def lifespan(_server):
    global courses, lookup, search, memory
    await init_pool(settings)
    init_llm_sem(settings.llm_concurrency)
    llm = AsyncOpenAI(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )
    vectors = make_vector_store(settings)
    embedder = AsyncEmbedder(llm, settings.embed_model, dim=settings.embedding_dim)
    courses = UserMeetingRepo(settings)
    lookup = LookupService(courses)
    search = SearchService(ChunksRepo(settings, vectors), embedder)
    memory = MemoryService(FactsRepo(settings, vectors), TodosRepo(settings), embedder)
    yield
    await close_pool()
    await vectors.close()
    await llm.close()


mcp = FastMCP("zhiyun-learning", lifespan=lifespan)


async def _safe(call, *args, **kwargs):
    try:
        return await call(*args, **kwargs)
    except (RecordingNotFound, FileNotGenerated, InvalidRecordingId) as exc:
        return str(exc)
    except Exception as exc:
        return f"工具执行失败：{exc}"


@mcp.tool()
async def list_courses() -> list[dict]:
    """列出当前学习者的课程记录。数据按 MCP Key 映射的 phone 隔离。"""
    rows = await courses.list_for_phone(current_phone(settings))
    return [{
        "course_id": row["recording_id"],
        "title": row.get("title"),
        "create_time": row.get("create_time"),
        "duration_ms": row.get("during"),
        "has_course_text": row.get("has_transcript", False),
        "has_summary": row.get("has_summary", False),
        "has_audio": row.get("has_audio", False),
    } for row in rows]


@mcp.tool()
async def get_course_transcript(course_id: str) -> str:
    """读取指定课程文字，作为回答、复盘和评价的可引用原始依据。"""
    return await _safe(lookup.get_transcript, current_phone(settings), course_id)


@mcp.tool()
async def get_course_summary(course_id: str) -> str:
    """读取指定课程已有摘要。重要结论仍应回到课程文字核验。"""
    return await _safe(lookup.get_summary, current_phone(settings), course_id)


@mcp.tool()
async def get_course_audio_url(course_id: str, expires: int = 3600) -> str:
    """获取课程录音地址，供引用证据时跳回原始音频。"""
    return await _safe(lookup.get_audio_url, current_phone(settings), course_id, expires)


@mcp.tool()
async def search_course_content(
    query: str,
    top_k: int = 5,
    course_id: str | None = None,
) -> list[dict]:
    """在当前学习者课程文字与摘要中语义检索，返回可溯源片段。"""
    return await search.search_meetings(
        query,
        current_phone(settings),
        top_k=max(1, min(10, top_k)),
        kind="all",
        recording_id=course_id,
    )


@mcp.tool()
async def find_related_courses(query: str, top_k: int = 5) -> list[dict]:
    """跨课程检索与当前问题相关的历史讲解；相似不表示因果或掌握。"""
    return await search.search_meetings(
        query,
        current_phone(settings),
        top_k=max(1, min(10, top_k)),
        kind="all",
    )


@mcp.tool()
async def get_learning_context(query: str = "最近的学习重点", top_k: int = 6) -> dict:
    """读取平台 AI 整理的长期学习档案与相关记忆，不读取其他学习者数据。"""
    return await read_learning_context(
        phone=current_phone(settings), query=query, top_k=max(1, min(10, top_k))
    )


@mcp.tool()
async def complete_learning_interaction(
    run_id: str,
    course_id: str,
    action: str,
    summary: str,
    dialogue_turns: list[dict],
    key_claims: list[dict] | None = None,
    artifacts: list[dict] | None = None,
) -> dict:
    """将一次完整学习对话回流平台，由平台 AI 提炼而非由 TeleAgent 直接改画像。

    dialogue_turns 应保留关键原始问答和提示过程；key_claims 只作为 TeleAgent
    的初步标注，平台仍会依据课程原文独立分析。任务必须携带平台生成的 run_id。
    """
    phone = current_phone(settings)
    await courses.ensure_owned(phone, course_id)
    return await write_learning_interaction(
        phone=phone,
        run_id=run_id,
        course_id=course_id,
        action=action,
        summary=summary,
        dialogue_turns=dialogue_turns,
        key_claims=key_claims,
        artifacts=artifacts,
    )


if __name__ == "__main__":
    import uvicorn
    from .auth import ApiKeyMiddleware

    # TeleAgent keeps MCP connections across desktop sessions and local service
    # restarts. Stateless HTTP prevents a stale client-side session id from
    # breaking every subsequent tool call with "Missing session ID".
    app = mcp.http_app(
        transport="streamable-http", path="/mcp", stateless_http=True
    )
    app.add_middleware(ApiKeyMiddleware, settings=settings, key_repo=ApiKeysRepo(settings))
    uvicorn.run(app, host="0.0.0.0", port=settings.mcp_port)
