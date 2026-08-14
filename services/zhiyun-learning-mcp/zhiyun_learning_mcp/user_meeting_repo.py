# meeting_assistant/user_meeting_repo.py
"""Read production meeting metadata and speaker-segment transcripts asynchronously.

多租户：所有方法强制按 phone 过滤——一个手机号只能查到自己的课程。
recording_id 在 MCP 全局 = str(user_meeting_info.id)。
课程摘要与元数据来自 user_meeting_info；课程文字来自 user_meeting_content。
"""
from .db import aconn
from .ids import validate_recording_id
from .transcripts import format_transcript_rows


class MeetingNotFound(KeyError):
    pass


class ContentNotGenerated(Exception):
    pass


class UserMeetingRepo:
    def __init__(self, settings):
        self.s = settings

    def _rid(self, recording_id):
        validate_recording_id(recording_id)
        return str(recording_id)

    async def list_for_phone(self, phone: str) -> list[dict]:
        """该手机号的全部可用课程（status=2 已生成、del_flag=0 未删）。"""
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(
                """SELECT id, phone, meeting_name, title, create_time, during,
                          CHAR_LENGTH(abstract_content) AS alen,
                          EXISTS(SELECT 1 FROM user_meeting_content umc
                                 WHERE umc.meet_id=user_meeting_info.id
                                   AND umc.content IS NOT NULL AND umc.content<>'') AS has_segments,
                          CHAR_LENGTH(content) AS legacy_clen,
                          (record_url IS NOT NULL AND record_url<>'') AS has_audio
                   FROM user_meeting_info
                   WHERE phone=%s AND status='2' AND del_flag='0'
                   ORDER BY create_time IS NULL, create_time DESC""",
                (phone,),
            )
            rows = await cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "recording_id": str(r["id"]),
                "phone": r["phone"],
                "title": r.get("title") or r.get("meeting_name"),
                "meeting_name": r.get("meeting_name"),
                "create_time": r["create_time"].strftime("%Y-%m-%d %H:%M:%S") if r.get("create_time") else None,
                "during": r.get("during"),
                "has_transcript": bool(r["has_segments"] or r["legacy_clen"]),
                "has_summary": bool(r["alen"]),
                "has_audio": bool(r["has_audio"]),
            })
        return out

    async def _row(self, phone: str, recording_id: str):
        rid = self._rid(recording_id)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(
                """SELECT id, phone, title, content, abstract_content,
                          abstract_text, record_url, asr_url, create_time
                   FROM user_meeting_info
                   WHERE id=%s AND phone=%s AND status='2' AND del_flag='0'""",
                (rid, phone),
            )
            row = await cur.fetchone()
        if not row:
            raise MeetingNotFound(f"课程不存在或无权访问: {recording_id}")
        return row

    async def ensure_owned(self, phone: str, recording_id: str) -> None:
        """Fail unless the recording belongs to the current MCP tenant."""
        await self._row(phone, recording_id)

    async def get_transcript(self, phone: str, recording_id: str) -> str:
        row = await self._row(phone, recording_id)
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(
                """SELECT id, begin_time, end_time, speaker, content, code, type
                   FROM user_meeting_content
                   WHERE meet_id=%s
                   ORDER BY begin_time IS NULL, begin_time, id""",
                (row["id"],),
            )
            segments = await cur.fetchall()
        txt = format_transcript_rows(segments) or row.get("content") or ""
        if not txt:
            raise ContentNotGenerated(
                f"课程 {recording_id} 存在，但课程文字内容尚未生成")
        return txt

    async def get_summary(self, phone: str, recording_id: str) -> str:
        row = await self._row(phone, recording_id)
        txt = row.get("abstract_content") or row.get("abstract_text") or ""
        if not txt:
            raise ContentNotGenerated(f"课程 {recording_id} 存在，但课程摘要尚未生成")
        return txt

    async def get_record_url(self, phone: str, recording_id: str) -> str:
        row = await self._row(phone, recording_id)
        url = row.get("record_url") or ""
        if not url:
            raise ContentNotGenerated(f"课程 {recording_id} 没有关联音频，可继续使用课程文字作为依据")
        return url
