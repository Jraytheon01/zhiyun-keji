"""ASGI handler for reliable upstream ingest notifications."""
import json

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .ingest_contracts import IngestNotification


def build_notification_handler(settings, jobs_repo):
    async def handle(request: Request):
        try:
            body = await request.json()
            notification = IngestNotification.model_validate(body)
        except ValidationError as exc:
            return JSONResponse(
                {"error": "invalid request", "details": json.loads(exc.json())}, status_code=422)
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON"}, status_code=400)

        # Upstream may have no meeting id when no transcript was ever created.
        # A delete for that state is an acknowledged no-op, not an ingest job.
        if notification.operation.value == "delete" and notification.meeting_id is None:
            return JSONResponse({"accepted": True}, status_code=200)

        await jobs_repo.enqueue(notification)
        return JSONResponse({"accepted": True}, status_code=202)

    return handle
