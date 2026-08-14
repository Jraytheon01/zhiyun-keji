"""Read the latest ingest source snapshot directly from upstream-owned MySQL tables."""
from .db import aconn
from .ids import validate_recording_id
from .ingest_contracts import MeetingSnapshot
from .transcripts import format_transcript_rows


class MeetingSourceNotFound(LookupError):
    pass


class MeetingSourceRepo:
    def __init__(self, settings):
        self.s = settings

    async def fetch(self, phone: str, meeting_id: str) -> MeetingSnapshot:
        rid = validate_recording_id(str(meeting_id))
        async with aconn(self.s) as connection, connection.cursor() as cursor:
            await cursor.execute(
                """SELECT id, phone, content, abstract_content,
                          abstract_text, create_time, title
                   FROM user_meeting_info
                   WHERE id=%s AND phone=%s AND (del_flag='0' OR del_flag IS NULL)""",
                (rid, phone),
            )
            meeting = await cursor.fetchone()
            if not meeting:
                raise MeetingSourceNotFound(
                    f"meeting not found for notification: meeting_id={rid}")
            await cursor.execute(
                """SELECT id, begin_time, end_time, speaker, content, code, type
                   FROM user_meeting_content
                   WHERE meet_id=%s
                   ORDER BY begin_time IS NULL, begin_time, id""",
                (rid,),
            )
            segments = await cursor.fetchall()

        transcript = format_transcript_rows(segments) or meeting.get("content") or ""
        summary = meeting.get("abstract_content") or meeting.get("abstract_text") or ""
        created = meeting.get("create_time")
        return MeetingSnapshot(
            recording_id=str(meeting["id"]),
            phone=str(meeting["phone"]),
            transcript=transcript,
            summary=summary,
            meeting_date=created.date().isoformat() if created else None,
            title=meeting.get("title"),
        )
