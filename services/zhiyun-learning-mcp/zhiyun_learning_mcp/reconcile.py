# meeting_assistant/reconcile.py
"""mem0-style memory reconciliation (async): decide ADD / UPDATE / SUPERSEDE / NOOP per fact.

The `judge` is injectable: a deterministic lambda in unit tests, `make_judge(settings)`
(deepseek, async) in production. SQL stays in FactsRepo; this module has no SQL.
"""
import json

from .concurrency import call_llm

RECONCILE_PROMPT = """你在做记忆去重。给定一条【新事实】和若干【已有事实】（同类、同主题/相近），判定其一：
- ADD：新事实，无匹配
- UPDATE：与某条匹配，字段可合并/覆盖（返回该条 id）
- SUPERSEDE：与某条匹配但属更新态（如状态变更、偏好改变），旧条应被取代（返回旧条 id）
- NOOP：与某条语义重复
只输出一行：VERDICT <id|none>，例如 `SUPERSEDE 42` 或 `ADD none` 或 `NOOP 17`。默认宁可不插（重复时 NOOP）。
对 kind=insight 的灵感放宽去重：只有高度重复（语义近乎相同）才 NOOP；相近但不同的火花都 ADD（灵感的价值在于保留多样性，不像事实那样需要收敛）。"""


def parse_verdict(raw: str):
    """Parse 'SUPERSEDE 42' / 'ADD none' / 'NOOP 17' into (action, rid|None)."""
    parts = raw.strip().split()
    action = parts[0]
    rid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
    return action, rid


async def reconcile_fact(facts_repo, new_fact: dict, judge, embed):
    """judge(candidates, new_fact) -> awaitable verdict string. embed unused (signature stability)。"""
    plan = await plan_fact_reconcile(facts_repo, new_fact, judge)
    return await apply_fact_reconcile(facts_repo, new_fact, plan)


async def plan_fact_reconcile(facts_repo, new_fact: dict, judge,
                              exclude_recording_id=None):
    """Run candidate lookup and the LLM decision without mutating storage."""
    candidate_args = (
        new_fact["kind"], new_fact.get("embedding", []), new_fact["phone"])
    if exclude_recording_id is None:
        cands = await facts_repo.candidates(*candidate_args)
    else:
        cands = await facts_repo.candidates(
            *candidate_args, exclude_recording_id=exclude_recording_id)
    return parse_verdict(await judge(cands, new_fact))


async def apply_fact_reconcile(facts_repo, new_fact: dict, plan):
    """Apply a previously validated reconciliation decision."""
    action, rid = plan
    if action == "ADD" or (action in ("UPDATE", "SUPERSEDE") and rid is None):
        return await facts_repo.insert(new_fact)
    if action == "UPDATE" and rid is not None:
        await facts_repo.update_detail(rid, new_fact["detail"])
        return rid
    if action == "SUPERSEDE" and rid is not None:
        new_id = await facts_repo.insert(new_fact)
        await facts_repo.supersede(rid, new_id)
        return new_id
    # NOOP or unknown
    return None


def make_judge(settings, client=None):
    """Returns async judge(candidates, new_fact) -> verdict_str using deepseek."""
    if client is None:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url,
                             timeout=settings.llm_timeout_seconds, max_retries=0)

    async def judge(candidates, new_fact):
        ctx = (
            f"新事实: {json.dumps(new_fact, ensure_ascii=False, default=str)}\n"
            f"已有事实: {json.dumps(candidates, ensure_ascii=False, default=str)}"
        )
        resp = await call_llm(
            client.chat.completions,
            model=settings.extract_model,
            messages=[
                {"role": "system", "content": RECONCILE_PROMPT},
                {"role": "user", "content": ctx},
            ],
            temperature=0,
        )
        return resp.choices[0].message.content

    return judge
