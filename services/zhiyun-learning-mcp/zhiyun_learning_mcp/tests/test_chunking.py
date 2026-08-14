from zhiyun_learning_mcp.chunking import chunk_summary


def test_chunks_real_chinese_summary_sections():
    text = "【会议概述】\n项目进入测试。\n【会议核心过程】\n张三负责联调。"
    chunks = chunk_summary(text)
    assert [chunk["section"] for chunk in chunks] == ["会议概述", "会议核心过程"]


def test_summary_without_headers_still_produces_a_chunk():
    assert chunk_summary("这是一个普通文本摘要") == [{
        "kind": "summary", "ordinal": 0,
        "text": "这是一个普通文本摘要", "section": "会议摘要",
    }]
