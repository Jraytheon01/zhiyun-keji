"""Standalone HTTP API for upstream ingest notifications."""
import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import db
from .config import Settings
from .notification_api import build_notification_handler
from .repos.ingest_jobs_repo import IngestJobsRepo


settings = Settings.load()
notification_handler = build_notification_handler(settings, IngestJobsRepo(settings))


async def health(_request):
    return JSONResponse({"status": "ok", "service": "meeting-assistant-ingest-api"})


@asynccontextmanager
async def lifespan(_app):
    await db.init_pool(settings)
    try:
        yield
    finally:
        await db.close_pool()


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/api/v1/ingest/notifications", notification_handler, methods=["POST"]),
    ],
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.ingest_api_port)
