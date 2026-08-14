# meeting_assistant/services/lookup.py
from ..user_meeting_repo import UserMeetingRepo, MeetingNotFound, ContentNotGenerated


class RecordingNotFound(KeyError):
    pass


class FileNotGenerated(Exception):
    pass


class LookupService:
    """逐字稿取自 user_meeting_content；纪要/音频取自 user_meeting_info。"""

    def __init__(self, repo: UserMeetingRepo):
        self.repo = repo

    async def _wrap(self, fn, phone, rid):
        try:
            return await fn(phone, rid)
        except MeetingNotFound as e:
            raise RecordingNotFound(str(e))
        except ContentNotGenerated as e:
            raise FileNotGenerated(str(e))

    async def get_transcript(self, phone: str, rid: str) -> str:
        return await self._wrap(self.repo.get_transcript, phone, rid)

    async def get_summary(self, phone: str, rid: str) -> str:
        return await self._wrap(self.repo.get_summary, phone, rid)

    async def get_audio_url(self, phone: str, rid: str, expires: int = 3600) -> str:
        # record_url 是公网可直接访问的链接，无需 presign；expires 保留以兼容旧签名。
        return await self._wrap(self.repo.get_record_url, phone, rid)
