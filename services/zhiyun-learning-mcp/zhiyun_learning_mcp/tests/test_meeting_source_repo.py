from contextlib import asynccontextmanager
from datetime import datetime

from zhiyun_learning_mcp.meeting_source_repo import MeetingSourceRepo


class FakeCursor:
    def __init__(self):
        self.query = 0
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _sql, params):
        self.query += 1
        self.params.append(params)

    async def fetchone(self):
        return {
            "id": 42, "phone": "13800000000",
            "content": None, "abstract_content": "会议摘要", "abstract_text": None,
            "create_time": datetime(2026, 8, 11, 9, 30), "title": "周会",
        }

    async def fetchall(self):
        return [
            {"id": 1, "type": "1", "speaker": "张三", "code": "1", "content": "确认上线"},
            {"id": 2, "type": "1", "speaker": None, "code": "2", "content": "负责测试"},
        ]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


async def test_fetches_snapshot_directly_from_two_mysql_tables(monkeypatch):
    cursor = FakeCursor()

    @asynccontextmanager
    async def fake_aconn(_settings):
        yield FakeConnection(cursor)

    monkeypatch.setattr("zhiyun_learning_mcp.meeting_source_repo.aconn", fake_aconn)
    snapshot = await MeetingSourceRepo(object()).fetch("13800000000", "42")

    assert cursor.params == [("42", "13800000000"), ("42",)]
    assert snapshot.recording_id == "42"
    assert snapshot.phone == "13800000000"
    assert snapshot.transcript == "张三：确认上线\n说话人2：负责测试"
    assert snapshot.summary == "会议摘要"
    assert snapshot.meeting_date == "2026-08-11"
