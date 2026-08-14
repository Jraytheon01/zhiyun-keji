from types import SimpleNamespace

from zhiyun_learning_mcp.concurrency import init_llm_sem
from zhiyun_learning_mcp.extractor import AsyncExtractor


class SequenceCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        content = "" if self.calls == 1 else '{"todos": [{"task": "联调"}]}'
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content))])


async def test_extractor_retries_empty_success_response():
    init_llm_sem(1)
    endpoint = SequenceCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=endpoint))
    result = await AsyncExtractor(client, "test-model").extract("转写", "摘要", "2026-08-10")
    assert endpoint.calls == 2
    assert result["todos"] == [{"task": "联调"}]
    assert result["projects"] == []


async def test_long_transcript_is_split_and_merged(monkeypatch):
    async def direct_call(endpoint, **kwargs):
        return await endpoint.create(**kwargs)

    monkeypatch.setattr("zhiyun_learning_mcp.extractor.call_llm", direct_call)

    class Endpoint:
        def __init__(self):
            self.calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            payload = '{"todos":[{"task":"任务' + str(self.calls) + '"}]}'
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=payload))])

    endpoint = Endpoint()
    client = SimpleNamespace(chat=SimpleNamespace(completions=endpoint))
    result = await AsyncExtractor(client, "test-model").extract(
        "说话人1：" + ("很长的逐字稿\n" * 5000), "摘要", "2026-08-11")

    assert endpoint.calls > 1
    assert len(result["todos"]) == endpoint.calls
