import json
from types import SimpleNamespace

from starlette.requests import Request

from zhiyun_learning_mcp.notification_api import build_notification_handler


class FakeJobsRepo:
    def __init__(self):
        self.seen = []

    async def enqueue(self, notification):
        self.seen.append(notification)
        return 17


def make_request(body):
    raw = json.dumps(body).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/ingest/notifications",
        "raw_path": b"/api/v1/ingest/notifications",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }, receive)


async def test_notification_returns_202_and_persists_job():
    repo = FakeJobsRepo()
    handler = build_notification_handler(SimpleNamespace(), repo)
    response = await handler(make_request({
        "phone": "13800000000",
        "meetingId": "42",
        "transcriptStatus": "created",
        "summaryStatus": "none",
    }))
    assert response.status_code == 202
    assert json.loads(response.body) == {"accepted": True}
    assert repo.seen[0].meeting_id == "42"


async def test_notification_accepts_without_authentication_header():
    repo = FakeJobsRepo()
    handler = build_notification_handler(SimpleNamespace(), repo)
    response = await handler(make_request({
        "phone": "13800000000",
        "meetingId": "43",
        "transcriptStatus": "updated",
        "summaryStatus": "none",
    }))
    assert response.status_code == 202
    assert repo.seen[0].meeting_id == "43"


async def test_notification_rejects_when_nothing_changed():
    repo = FakeJobsRepo()
    handler = build_notification_handler(SimpleNamespace(), repo)
    response = await handler(make_request({
        "phone": "13800000000",
        "meeting_id": "42",
        "transcript_status": "none",
        "summary_status": "none",
    }))
    assert response.status_code == 422
    assert repo.seen == []


async def test_delete_notification_returns_202_without_content_statuses():
    repo = FakeJobsRepo()
    handler = build_notification_handler(SimpleNamespace(), repo)
    response = await handler(make_request({
        "phone": "13800000000",
        "meetingId": "42",
        "operation": "delete",
    }))
    assert response.status_code == 202
    assert json.loads(response.body) == {"accepted": True}
    assert repo.seen[0].operation.value == "delete"


async def test_delete_with_null_meeting_id_returns_200_without_job():
    repo = FakeJobsRepo()
    handler = build_notification_handler(SimpleNamespace(), repo)
    response = await handler(make_request({
        "phone": "13800000000",
        "meetingId": None,
        "operation": "delete",
    }))
    assert response.status_code == 200
    assert json.loads(response.body) == {"accepted": True}
    assert repo.seen == []
