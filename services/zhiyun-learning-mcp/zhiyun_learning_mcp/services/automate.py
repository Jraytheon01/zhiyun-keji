# meeting_assistant/services/automate.py
"""L4 automation service (async): todo queries, reminders, and full-replace reingest.
多租户：所有方法带 phone。
reingest 从 user_meeting_content/user_meeting_info 读转写/纪要，重跑整条 ingest 管道。
"""
import asyncio
from datetime import datetime, timezone, timedelta

from ..concurrency import call_llm


async def _empty():
    return []


class AutomateService:
    def __init__(self, todos_repo, settings, meetings, search=None, memory=None, llm=None,
                 embedder=None, vector_store=None):
        self.tr = todos_repo
        self.s = settings
        self.meetings = meetings
        self.search = search
        self.memory = memory
        self.llm = llm
        self.embedder = embedder
        self.vector_store = vector_store

    async def get_todos(self, phone, status="open", due_before=None, owner=None):
        """Filter todos by status / due cutoff / owner (all optional), scoped to tenant."""
        return [dict(t) for t in await self.tr.query(phone, status=status, due_before=due_before, owner=owner)]

    async def remind_upcoming(self, phone, days=7):
        """Open todos whose due date is on/before today+days (CST, UTC+8)."""
        now = datetime.now(timezone(timedelta(hours=8))).date()
        return [dict(t) for t in await self.tr.due_within(phone, days, now)]

    async def reingest(self, rid, phone, extractor=None, judge=None, embedder=None, vector_store=None):
        """FULL replace: re-run the whole pipeline for rid (chunks+facts+todos)。

        从说话人明细表读逐字稿、从主表读 abstract_content；ingest 先完成
        Embedding/抽取，再在排他锁内替换派生数据。
        """
        from ..ids import validate_recording_id
        validate_recording_id(rid)
        transcript = await self.meetings.get_transcript(phone, rid)
        summary = await self.meetings.get_summary(phone, rid)
        from ..ingest import ingest
        if extractor is None:
            from ..extractor import make_extractor
            extractor = make_extractor(self.s, client=self.llm)
        if judge is None:
            from ..reconcile import make_judge
            judge = make_judge(self.s, client=self.llm)
        return await ingest(self.s, rid, phone, transcript, summary,
                            embedder=embedder or self.embedder,
                            vector_store=vector_store or self.vector_store,
                            extractor=extractor, judge=judge)

    async def _complete(self, system, user):
        if self.llm is None:
            from openai import AsyncOpenAI
            self.llm = AsyncOpenAI(
                api_key=self.s.ai_api_key, base_url=self.s.ai_base_url,
                timeout=self.s.llm_timeout_seconds, max_retries=0)
        resp = await call_llm(
            self.llm.chat.completions,
            model=self.s.extract_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3, extra_body={"enable_thinking": False})
        return resp.choices[0].message.content

    async def draft_agenda(self, topic, phone):
        facts, refs, todos = await asyncio.gather(
            self.memory.recall(topic, phone, top_k=5) if self.memory else _empty(),
            self.search.search_meetings(topic, phone, top_k=5) if self.search else _empty(),
            self.get_todos(phone, status="open"),
        )
        ctx = f"主题：{topic}\n相关事实：{facts}\n相关会议原文：{refs}\n待办：{todos}"
        return await self._complete("你是会议议程起草助手。基于下列资料输出 Markdown 议程，引用具体 recording_id。", ctx)

    async def weekly_report(self, week, phone):
        rows, todos = await asyncio.gather(
            self.meetings.list_for_phone(phone),
            self.get_todos(phone, status="open"),
        )
        ctx = f"近期录音：{rows}\n当前 open 待办：{todos}"
        return await self._complete("你是周报生成助手。基于下列资料生成本周 Markdown 周报（进展/风险/下周计划）。", ctx)
