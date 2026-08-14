# meeting_assistant/tests/conftest.py
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        help="run integration tests (need local Docker MySQL/Milvus)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(
        reason="needs --run-integration + local Docker MySQL/Milvus"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
