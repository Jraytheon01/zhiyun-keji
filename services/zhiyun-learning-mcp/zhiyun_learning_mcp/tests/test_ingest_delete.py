from zhiyun_learning_mcp import ingest as ingest_module


async def test_delete_ingested_cleans_every_derived_store(monkeypatch):
    calls = []

    class FakeChunksRepo:
        def __init__(self, _settings, vector_store):
            assert vector_store == "vector-store"

        async def delete_for(self, rid):
            calls.append(("chunks", rid))

    class FakeFactsRepo:
        def __init__(self, _settings, vector_store):
            assert vector_store == "vector-store"

        async def delete_for(self, rid):
            calls.append(("facts", rid))

    class FakeTodosRepo:
        def __init__(self, _settings):
            pass

        async def delete_for(self, rid):
            calls.append(("todos", rid))

    class FakeRecordingsRepo:
        def __init__(self, _settings):
            pass

        async def delete(self, rid):
            calls.append(("recordings", rid))

    monkeypatch.setattr(ingest_module, "ChunksRepo", FakeChunksRepo)
    monkeypatch.setattr(ingest_module, "RecordingsRepo", FakeRecordingsRepo)
    monkeypatch.setattr(
        "zhiyun_learning_mcp.repos.facts_repo.FactsRepo", FakeFactsRepo)
    monkeypatch.setattr(
        "zhiyun_learning_mcp.repos.todos_repo.TodosRepo", FakeTodosRepo)

    await ingest_module.delete_ingested(
        object(), "42", vector_store="vector-store", lock_already_held=True)

    assert calls == [
        ("chunks", "42"),
        ("facts", "42"),
        ("todos", "42"),
        ("recordings", "42"),
    ]
