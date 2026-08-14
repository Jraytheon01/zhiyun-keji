"""Platform callbacks used by the education MCP."""
from __future__ import annotations

import os
from typing import Any

import httpx


ALLOWED_ACTIONS = {
    "course_review", "mind_map", "learning_check", "cross_course_review", "study_plan"
}


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _turns(items: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate((items or [])[:80]):
        if not isinstance(item, dict):
            continue
        role = _text(item.get("role"), 24).lower()
        if role not in {"student", "user", "assistant", "teleagent", "teacher"}:
            role = "unknown"
        content = _text(item.get("content"), 4000)
        if content:
            normalized.append({"turn_index": index, "role": role, "content": content})
    return normalized


def _objects(items: list[dict] | None, limit: int) -> list[dict]:
    result = []
    for item in (items or [])[:limit]:
        if isinstance(item, dict):
            result.append(item)
    return result


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("PLATFORM_WRITE_TOKEN", "").strip()
    if token:
        headers["X-Platform-Token"] = token
    return headers


def _platform_url() -> str:
    value = os.environ.get("PLATFORM_PUBLIC_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("PLATFORM_PUBLIC_URL 未配置，无法连接智云课迹")
    return value


async def complete_learning_interaction(
    *,
    phone: str,
    run_id: str,
    course_id: str,
    action: str,
    summary: str,
    dialogue_turns: list[dict] | None,
    key_claims: list[dict] | None,
    artifacts: list[dict] | None,
) -> dict:
    payload = {
        "phone": _text(phone, 64),
        "run_id": _text(run_id, 96),
        "course_id": _text(course_id, 96),
        "action": action if action in ALLOWED_ACTIONS else "course_review",
        "summary": _text(summary, 4000),
        "dialogue_turns": _turns(dialogue_turns),
        "key_claims": _objects(key_claims, 20),
        "artifacts": _objects(artifacts, 10),
    }
    if not payload["run_id"] or not payload["course_id"]:
        raise ValueError("run_id 和 course_id 必填")
    if not payload["dialogue_turns"] and not payload["summary"]:
        raise ValueError("至少提交对话原文或互动摘要")
    if payload["action"] in {"course_review", "learning_check"}:
        roles = {item["role"] for item in payload["dialogue_turns"]}
        if not roles.intersection({"student", "user"}) or not roles.intersection(
            {"assistant", "teleagent", "teacher"}
        ):
            raise ValueError("课程复盘/学习检测必须回流学生原话和 TeleAgent 提示或回答")
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{_platform_url()}/api/internal/learning-interactions",
            json=payload,
            headers=_headers(),
        )
    if response.is_error:
        raise RuntimeError(f"智云课迹回流失败（{response.status_code}）：{response.text[:500]}")
    data = response.json()
    memory_index = data.get("memory_index") or {}
    return {
        "ok": True,
        "run_id": payload["run_id"],
        "course_id": payload["course_id"],
        "state": data.get("run", {}).get("state", "completed"),
        "insight_count": len(data.get("insights", [])),
        "memory_count": len(data.get("memories", [])),
        "memory_ids": [item.get("memory_id") for item in data.get("memories", []) if item.get("memory_id")],
        "vector_indexed": int(memory_index.get("indexed") or 0),
        "memory_search_ready": bool(memory_index.get("ready")),
        "memory_index_error": str(memory_index.get("error") or "")[:300],
        "idempotent": bool(data.get("idempotent")),
    }


async def get_learning_context(*, phone: str, query: str, top_k: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{_platform_url()}/api/internal/learning-context",
            params={"phone": _text(phone, 64), "query": _text(query, 500), "top_k": top_k},
            headers=_headers(),
        )
    if response.is_error:
        raise RuntimeError(f"读取学习档案失败（{response.status_code}）：{response.text[:500]}")
    return response.json()
