import pytest
from pydantic import ValidationError

from zhiyun_learning_mcp.ingest_contracts import (
    IngestNotification,
    NotificationOperation,
    UpstreamMeetingSnapshot,
)


def test_notification_accepts_java_camel_case():
    item = IngestNotification.model_validate({
        "phone": "13800000000",
        "meetingId": "42",
        "transcriptStatus": "created",
        "summaryStatus": "none",
    })
    assert item.meeting_id == "42"
    assert item.operation == NotificationOperation.upsert


def test_delete_notification_does_not_require_content_statuses():
    item = IngestNotification.model_validate({
        "phone": "13800000000",
        "meetingId": "42",
        "operation": "delete",
    })
    assert item.operation == NotificationOperation.delete
    assert item.transcript_status.value == "none"
    assert item.summary_status.value == "none"


def test_delete_notification_accepts_null_meeting_id():
    item = IngestNotification.model_validate({
        "phone": "13800000000",
        "meetingId": None,
        "operation": "delete",
    })
    assert item.meeting_id is None


def test_upsert_notification_rejects_null_meeting_id():
    with pytest.raises(ValidationError):
        IngestNotification.model_validate({
            "phone": "13800000000",
            "meetingId": None,
            "operation": "upsert",
            "transcriptStatus": "created",
        })


def test_notification_requires_at_least_one_change():
    with pytest.raises(ValidationError):
        IngestNotification.model_validate({
            "phone": "13800000000",
            "meeting_id": "42",
            "transcript_status": "none",
            "summary_status": "none",
        })


def test_upstream_snapshot_maps_existing_mysql_names():
    snapshot = UpstreamMeetingSnapshot.model_validate({
        "id": 42,
        "phone": "13800000000",
        "content": "逐字稿",
        "abstract_content": "摘要",
        "create_time": "2026-08-10 09:00:00",
    })
    assert snapshot.recording_id == "42"
    assert snapshot.transcript == "逐字稿"
    assert snapshot.summary == "摘要"


def test_source_hash_is_stable_and_changes_with_ingest_input():
    first = UpstreamMeetingSnapshot.model_validate({
        "meetingId": "42", "phone": "13800000000",
        "content": "逐字稿", "abstractContent": "摘要",
    })
    same = UpstreamMeetingSnapshot.model_validate({
        "phone": "13800000000", "abstractContent": "摘要",
        "content": "逐字稿", "meetingId": "42",
    })
    changed = UpstreamMeetingSnapshot.model_validate({
        "meetingId": "42", "phone": "13800000000",
        "content": "修改后的逐字稿", "abstractContent": "摘要",
    })
    assert first.source_hash() == same.source_hash()
    assert first.source_hash() != changed.source_hash()
