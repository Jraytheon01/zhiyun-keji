# meeting_assistant/extractor.py
import json
import re
import asyncio

from .concurrency import call_llm

EXTRACTION_PROMPT = """你是会议纪要结构化抽取器。从下面的会议转写+总结中抽取结构化事实，输出严格 JSON（只输出 JSON，不要多余文字、不要 markdown 代码块）。
字段：
- projects: [{name, status, attrs}]   项目及状态
- people:   [{name, role, attrs}]      人物及角色
- decisions:[{about, decision, rationale, date}]   决策（date 缺省填会议日期）
- relationships: [{a, relation, b}]    关系（如 张三 负责 项目A）
- preferences: [{about, preference}]   用户/团队偏好
- todos:    [{task, owner, due}]       待办（due 缺省填 null）
- insights: [{text, subtype, tags}]   值得记的非结论性内容：洞察/疑问/假设/火花（subtype: idea|doubt|hypothesis|question|spark）
规则：只抽原文有的信息，不编造；金额/数量/百分比/负责人原样保留；没有的字段返回空数组 []。
日期一律用 YYYY-MM-DD：能确定具体年月日的就写 ISO 日期；模糊/相对日期（如"下周五""5月20日前""Q3末"）无法确定完整日期的，date/due 填 null（不要填中文日期串）。另外抽取值得留存的非结论性想法/开放问题/假设到 insights（只抽确实值得记的，宁缺勿滥）。
"""


def parse_extraction(raw: str) -> dict:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fence:
        raw = fence.group(1)
    else:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            raw = m.group(0)
    data = json.loads(raw)
    for k in ("projects", "people", "decisions", "relationships", "preferences", "todos", "insights"):
        data.setdefault(k, [])
    return data


class AsyncExtractor:
    def __init__(self, client, model: str):
        self.client = client; self.model = model

    async def extract(self, transcript: str, summary: str, meeting_date: str) -> dict:
        parts = _split_for_extraction(transcript)
        results = await asyncio.gather(*[
            self._extract_part(part, summary, meeting_date, index, len(parts))
            for index, part in enumerate(parts, start=1)
        ])
        return _merge_extractions(results)

    async def _extract_part(self, transcript: str, summary: str, meeting_date: str,
                            part_number: int, part_count: int) -> dict:
        user = f"会议日期：{meeting_date}\n\n【转写】\n{transcript}\n\n【总结】\n{summary}"
        if part_count > 1:
            user = f"这是逐字稿第 {part_number}/{part_count} 段。\n" + user
        last_error = None
        for attempt in range(3):
            messages = [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": user},
            ]
            if attempt:
                messages.append({
                    "role": "user",
                    "content": "上一次响应无法解析。请重新输出一个非空、合法的 JSON 对象，只输出 JSON。",
                })
            resp = await call_llm(
                self.client.chat.completions,
                model=self.model,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
            try:
                return parse_extraction(content)
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                last_error = exc
        raise ExtractionResponseError(
            f"model {self.model} returned invalid structured output after 3 attempts") from last_error


class ExtractionResponseError(RuntimeError):
    """The model request succeeded but no parseable JSON object was returned."""


class FakeAsyncExtractor:
    """Returns a fixed payload; pass via extractor= for tests."""
    def __init__(self, payload=None): self.payload = payload or {}; self.model = "fake"

    async def extract(self, transcript, summary, meeting_date):
        p = {"projects": [], "people": [], "decisions": [], "relationships": [],
             "preferences": [], "todos": [], "insights": []}
        p.update(self.payload)
        return p


def make_extractor(settings, client=None):
    if client is None:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.ai_api_key, base_url=settings.ai_base_url,
                             timeout=settings.llm_timeout_seconds, max_retries=0)
    return AsyncExtractor(client, settings.extract_model)


def _split_for_extraction(transcript: str, max_chars: int = 24000,
                          overlap_chars: int = 600) -> list[str]:
    """Bound model input while preserving a small overlap between parts."""
    text = transcript or ""
    if len(text) <= max_chars:
        return [text]
    parts = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return parts


def _merge_extractions(results: list[dict]) -> dict:
    keys = ("projects", "people", "decisions", "relationships",
            "preferences", "todos", "insights")
    merged = {key: [] for key in keys}
    seen = {key: set() for key in keys}
    for result in results:
        for key in keys:
            for item in result.get(key, []):
                identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if identity not in seen[key]:
                    seen[key].add(identity)
                    merged[key].append(item)
    return merged
