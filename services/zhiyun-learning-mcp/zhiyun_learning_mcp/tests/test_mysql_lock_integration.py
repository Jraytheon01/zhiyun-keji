import asyncio

import pytest

from zhiyun_learning_mcp import db
from zhiyun_learning_mcp.config import Settings


@pytest.mark.integration
async def test_recording_lock_blocks_same_meeting_but_not_different_meeting():
    settings = Settings.load()
    await db.init_pool(settings, maxsize=4)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with db.recording_lock("integration-lock-1", 0):
            entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(db.RecordingLockBusy):
            async with db.recording_lock("integration-lock-1", 0):
                pass
        async with db.recording_lock("integration-lock-2", 0):
            pass
    finally:
        release.set()
        await task
        await db.close_pool()
