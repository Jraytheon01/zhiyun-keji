from zhiyun_learning_mcp.transcripts import format_transcript_rows


def test_prefers_normalized_transcript_rows_and_keeps_speakers():
    rows = [
        {"id": 1, "type": "0", "speaker": "旧版", "code": "1", "content": "不要重复"},
        {"id": 2, "type": "1", "speaker": "张三", "code": "1", "content": "确认方案"},
        {"id": 3, "type": "1", "speaker": None, "code": "2", "content": " 明天完成 "},
    ]

    assert format_transcript_rows(rows) == "张三：确认方案\n说话人2：明天完成"


def test_falls_back_to_ordinary_rows_when_no_normalized_version():
    rows = [{"id": 1, "type": "0", "speaker": None, "code": "1", "content": "原始转写"}]
    assert format_transcript_rows(rows) == "说话人1：原始转写"
