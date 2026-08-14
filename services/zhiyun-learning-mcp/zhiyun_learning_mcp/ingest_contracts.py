"""Stable notification and internal MySQL snapshot contracts."""
import hashlib
import json
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class ChangeStatus(str, Enum):
    none = "none"
    created = "created"
    updated = "updated"


class NotificationOperation(str, Enum):
    upsert = "upsert"
    delete = "delete"


class IngestNotification(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    phone: str = Field(min_length=1, max_length=32)
    meeting_id: str | None = Field(
        min_length=1, max_length=255,
        validation_alias=AliasChoices("meeting_id", "meetingId"))
    operation: NotificationOperation = Field(
        default=NotificationOperation.upsert,
        validation_alias=AliasChoices("operation", "event_type", "eventType", "action"))
    transcript_status: ChangeStatus = Field(
        default=ChangeStatus.none,
        validation_alias=AliasChoices("transcript_status", "transcriptStatus"))
    summary_status: ChangeStatus = Field(
        default=ChangeStatus.none,
        validation_alias=AliasChoices("summary_status", "summaryStatus"))
    @field_validator("meeting_id", mode="before")
    @classmethod
    def normalize_meeting_id(cls, value):
        return str(value) if value is not None else value

    @model_validator(mode="after")
    def require_a_change(self):
        if self.operation == NotificationOperation.delete:
            return self
        if self.meeting_id is None:
            raise ValueError("operation=upsert 时 meeting_id 不能为 null")
        if self.transcript_status == ChangeStatus.none and self.summary_status == ChangeStatus.none:
            raise ValueError("transcript_status 和 summary_status 至少一个必须是 created 或 updated")
        return self


class MeetingSnapshot(BaseModel):
    """Canonical transcript/summary snapshot read from MySQL source tables."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore", str_strip_whitespace=True)

    recording_id: str = Field(
        min_length=1, max_length=255,
        validation_alias=AliasChoices("recording_id", "recordingId", "meeting_id", "meetingId", "id"))
    phone: str = Field(min_length=1, max_length=32)
    transcript: str | None = Field(
        default=None, validation_alias=AliasChoices("transcript", "content"))
    summary: str | None = Field(
        default=None,
        validation_alias=AliasChoices("summary", "abstract_content", "abstractContent"))
    meeting_date: str | None = Field(
        default=None,
        validation_alias=AliasChoices("meeting_date", "meetingDate", "create_time", "createTime"))
    title: str | None = None

    @field_validator("recording_id", mode="before")
    @classmethod
    def normalize_recording_id(cls, value):
        return str(value) if value is not None else value

    @model_validator(mode="after")
    def require_content(self):
        if not (self.transcript or self.summary):
            raise ValueError("MySQL 快照必须至少包含逐字稿或摘要")
        return self

    def source_hash(self) -> str:
        """Hash exactly the source fields that affect derived ingest output."""
        canonical = json.dumps({
            "recording_id": self.recording_id,
            "phone": self.phone,
            "transcript": self.transcript or "",
            "summary": self.summary or "",
            "meeting_date": self.meeting_date or "",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# Temporary import compatibility for callers created before direct-MySQL ingest.
UpstreamMeetingSnapshot = MeetingSnapshot
