# -*- coding: utf-8 -*-
"""MCP side bridge: receive ingest completion event and forward to display node."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import queue
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

LOG = logging.getLogger("moben-auto-ppt")
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR.parent / "config.json"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return []
    return json.loads(value)


@dataclass(slots=True)
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 18766
    bridge_token: str = ""
    task_timeout_seconds: int = 900
    pickup_timeout_seconds: int = 30
    default_audience: str = "项目团队和管理层"
    default_style: str = "商务简约"
    default_slides: int = 7
    default_output: str = "会议PPT.pptx"
    job_db: str = ""
    dry_run: bool = False
    display_bridge_url: str = "http://127.0.0.1:18767"
    display_bridge_token: str = ""
    display_bridge_timeout_seconds: float = 10.0
    display_bridge_retries: int = 3
    display_bridge_retry_delay_seconds: float = 1.5
    display_bridge_retry_max_delay_seconds: float = 20.0
    display_bridge_trigger_delay_seconds: float = 0.0

    @classmethod
    def load(cls, path: Path) -> "ServiceConfig":
        raw: dict[str, Any] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
        valid = cls.__dataclass_fields__.keys()
        config = cls(**{key: value for key, value in raw.items() if key in valid})
        config.host = os.environ.get("MOBEN_PPT_HOST", config.host)
        config.port = int(os.environ.get("MOBEN_PPT_PORT", config.port))
        config.bridge_token = os.environ.get("MOBEN_PPT_TOKEN", config.bridge_token)
        host = os.environ.get("DISPLAY_BRIDGE_HOST", "")
        port = os.environ.get("DISPLAY_BRIDGE_PORT", "")
        explicit = os.environ.get("DISPLAY_BRIDGE_URL", "").strip()
        if explicit:
            config.display_bridge_url = explicit.rstrip("/")
        elif host or port:
            config.display_bridge_url = f"http://{host or '127.0.0.1'}:{port or 18767}"
        elif config.display_bridge_url:
            config.display_bridge_url = config.display_bridge_url.rstrip("/")
        else:
            config.display_bridge_url = "http://127.0.0.1:18767"
        config.display_bridge_token = os.environ.get(
            "DISPLAY_BRIDGE_TOKEN", config.display_bridge_token
        )
        config.display_bridge_timeout_seconds = float(
            os.environ.get("DISPLAY_BRIDGE_TIMEOUT_SECONDS", str(config.display_bridge_timeout_seconds))
        )
        config.display_bridge_retries = int(
            os.environ.get("DISPLAY_BRIDGE_RETRIES", str(config.display_bridge_retries))
        )
        config.display_bridge_retry_delay_seconds = float(
            os.environ.get(
                "DISPLAY_BRIDGE_RETRY_DELAY_SECONDS",
                str(config.display_bridge_retry_delay_seconds),
            )
        )
        config.display_bridge_retry_max_delay_seconds = float(
            os.environ.get(
                "DISPLAY_BRIDGE_RETRY_MAX_DELAY_SECONDS",
                str(config.display_bridge_retry_max_delay_seconds),
            )
        )
        config.display_bridge_trigger_delay_seconds = float(
            os.environ.get(
                "DISPLAY_BRIDGE_TRIGGER_DELAY_SECONDS",
                str(config.display_bridge_trigger_delay_seconds),
            )
        )
        return config


def normalise_event(payload: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(payload.get("recording_id") or payload.get("meeting_id") or "").strip()
    meeting_title = str(payload.get("meeting_title") or payload.get("title") or "").strip()
    completed_at = str(payload.get("completed_at") or "").strip()
    use_latest = bool(payload.get("use_latest", not recording_id and not meeting_title))
    if not recording_id and not meeting_title and not use_latest:
        raise ValueError(
            "recording_id、meeting_title 至少提供一个；或者使用 use_latest=true"
        )

    event = {
        "event_id": str(payload.get("event_id") or "").strip(),
        "recording_id": recording_id,
        "meeting_title": meeting_title,
        "completed_at": completed_at,
        "use_latest": use_latest,
        "audience": str(payload.get("audience") or "").strip(),
        "style": str(payload.get("style") or "").strip(),
        "slides": payload.get("slides"),
        "output": str(payload.get("output") or "").strip(),
        "prompt": str(payload.get("prompt") or "").strip(),
        "source": str(payload.get("source") or "moben-recorder-app").strip(),
    }
    if event["slides"] is not None:
        try:
            event["slides"] = int(event["slides"])
        except (TypeError, ValueError) as exc:
            raise ValueError("slides 需要是整数") from exc
        if not 3 <= event["slides"] <= 30:
            raise ValueError("slides 需要在 3 到 30 之间")

    if not event["event_id"]:
        stable = json_dumps({
            "recording_id": event["recording_id"],
            "meeting_title": event["meeting_title"],
            "source": event["source"],
            "completed_at": event["completed_at"],
        })
        event["event_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    if len(event["event_id"]) > 128:
        raise ValueError("event_id 长度不能超过 128")
    return event


def build_prompt(event: dict[str, Any], config: ServiceConfig) -> str:
    audience = event["audience"] or config.default_audience
    style = event["style"] or config.default_style
    slides = event["slides"] if event["slides"] else config.default_slides
    output = event["output"] or config.default_output
    return (
        "请使用 Toby.AI录音卡助手，直接为我生成最近一场会议的PPT。"
        f"采用默认参数：排版 PPT（可编辑 .pptx）、受众为{audience}、"
        f"{style}风格、约{slides}页，输出文件名为{output}。"
        "不要向我提问或等待确认；直接选择最近会议，优先读取已有纪要，"
        "纪要不可用时读取逐字稿，然后调用PPT能力生成并返回文件。"
        "生成完成后直接返回可编辑PPT文件及其绝对路径即可，"
        "无需额外展示缩略图、逐页视觉复核、质量评分或二次优化过程。"
    )


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auto_ppt_job (
                    event_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    state TEXT NOT NULL,
                    message_id TEXT NOT NULL DEFAULT '',
                    response_text TEXT NOT NULL DEFAULT '',
                    file_paths TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(self, event: dict[str, Any], prompt: str) -> bool:
        now = now_text()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO auto_ppt_job
                    (event_id, request_json, prompt, state, created_at, updated_at)
                    VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (event["event_id"], json_dumps(event), prompt, now, now),
            )
            return cursor.rowcount == 1

    def update(self, event_id: str, **fields: Any) -> None:
        allowed = {
            "state", "message_id", "response_text", "file_paths", "error", "attempts",
            "next_retry_at"
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return
        values["updated_at"] = now_text()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE auto_ppt_job SET {assignments} WHERE event_id=?",
                [*values.values(), event_id],
            )

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM auto_ppt_job WHERE event_id=?", (event_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["request"] = json_loads(result.pop("request_json"))
        result["file_paths"] = json_loads(result["file_paths"])
        return result

    def fail_incomplete_after_restart(self) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE auto_ppt_job
                SET state='failed', error='bridge service restarted while job was active',
                    updated_at=?
                WHERE state IN ('queued', 'submitting', 'running')
                """,
                (now_text(),),
            )
            return cursor.rowcount


class DisplayBridgeClient:
    def __init__(self, config: ServiceConfig):
        self.config = config

    @property
    def base_url(self) -> str:
        return self.config.display_bridge_url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json_dumps(payload).encode("utf-8")
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.config.display_bridge_token:
            headers["X-Bridge-Token"] = self.config.display_bridge_token
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.config.display_bridge_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"display bridge HTTP {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"display bridge connection failed: {exc}") from exc

    def health(self) -> dict[str, Any]:
        result = self._request("GET", "/health")
        return {"target": self.base_url, "remote_health": result}

    def submit(self, event: dict[str, Any], prompt: str) -> str:
        if self.config.display_bridge_trigger_delay_seconds > 0:
            time.sleep(self.config.display_bridge_trigger_delay_seconds)
        payload = dict(event)
        payload["prompt"] = prompt
        body = self._request(
            "POST", "/events/recording-completed", payload=payload
        )
        return str(body.get("event_id") or event["event_id"])

    def wait(self, message_id: str) -> dict[str, Any]:
        started = time.monotonic()
        while time.monotonic() - started < self.config.task_timeout_seconds:
            job = self._request("GET", f"/jobs/{message_id}")
            status = str(job.get("state") or "")
            if status in {"completed", "failed", "skipped"}:
                if status == "failed":
                    if (
                        (job.get("file_paths") or job.get("outbound_text"))
                        and not job.get("result_error")
                        and not job.get("opencode_error")
                    ):
                        return job
                    raise RuntimeError(job.get("error") or job.get("result_error") or "display bridge generated failed")
                return job
            time.sleep(2)
        raise TimeoutError("display bridge 生成 PPT 超时")


class AutoPptService:
    def __init__(self, config: ServiceConfig):
        self.config = config
        db_path = Path(config.job_db).expanduser() if config.job_db else SCRIPT_DIR / ".auto_ppt_jobs.db"
        self.store = JobStore(db_path)
        interrupted = self.store.fail_incomplete_after_restart()
        if interrupted:
            LOG.warning("marked %s interrupted jobs as failed", interrupted)
        self.bridge = DisplayBridgeClient(config)
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.worker = threading.Thread(target=self._work_loop, daemon=True)
        self.worker.start()

    def submit(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        event = normalise_event(payload)
        # The server-side Bridge owns the demo prompt. Upstream only reports the
        # completed recording event and cannot replace the TeleAgent instruction.
        prompt = build_prompt(event, self.config)
        created = self.store.create(event, prompt)
        if created:
            self.jobs.put(event["event_id"])
        job = self.store.get(event["event_id"])
        assert job is not None
        return job, created

    def _next_attempt_delay(self, attempts: int) -> float:
        if attempts <= 0:
            return 0.0
        return min(
            self.config.display_bridge_retry_delay_seconds * (2 ** max(attempts - 1, 0)),
            self.config.display_bridge_retry_max_delay_seconds,
        )

    def _is_time_to_run(self, job: dict[str, Any]) -> bool:
        retry_at = str(job.get("next_retry_at") or "").strip()
        if not retry_at:
            return True
        try:
            return time.time() >= float(retry_at)
        except ValueError:
            return True

    def _work_loop(self) -> None:
        while True:
            event_id = self.jobs.get()
            if event_id is None:
                return
            try:
                job = self.store.get(event_id)
                if not job or job["state"] not in {"queued", "running"}:
                    continue
                if not self._is_time_to_run(job):
                    self.store.update(event_id, state="queued")
                    self.jobs.put(event_id)
                    continue
                if self.config.dry_run:
                    self.store.update(
                        event_id,
                        state="completed",
                        response_text="dry-run: bridge stub",
                        file_paths=json_dumps([]),
                    )
                    continue
                attempts = int(job.get("attempts") or 0)
                self.store.update(
                    event_id,
                    state="submitting",
                    attempts=attempts + 1,
                    error="",
                    next_retry_at="",
                )
                message_id = self.bridge.submit(job["request"], job["prompt"])
                self.store.update(event_id, state="running", message_id=message_id)
                result = self.bridge.wait(message_id)
                self.store.update(
                    event_id,
                    state="completed",
                    response_text=result.get("outbound_text", ""),
                    file_paths=json_dumps(result.get("file_paths", [])),
                )
            except Exception as exc:
                job = self.store.get(event_id)
                if not job:
                    continue
                attempts = int(job.get("attempts") or 0)
                delay = self._next_attempt_delay(attempts)
                if attempts < self.config.display_bridge_retries + 1:
                    next_retry = time.time() + delay
                    LOG.exception("bridge forward failed for event=%s attempt=%s", event_id, attempts)
                    self.store.update(
                        event_id,
                        state="queued",
                        error=str(exc),
                        attempts=attempts,
                        next_retry_at=str(next_retry),
                    )
                    if delay > 0:
                        time.sleep(delay)
                    self.jobs.put(event_id)
                else:
                    LOG.exception("bridge forward failed for event=%s, no retries left", event_id)
                    self.store.update(event_id, state="failed", error=str(exc), attempts=attempts)
            finally:
                self.jobs.task_done()

    def stop(self) -> None:
        self.jobs.put(None)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "MobenAutoPpt/1.0"

    @property
    def app(self) -> AutoPptService:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("http %s - %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        token = self.app.config.bridge_token
        if not token:
            return True
        supplied = self.headers.get("X-Bridge-Token", "")
        bearer = self.headers.get("Authorization", "")
        if bearer.lower().startswith("bearer "):
            supplied = bearer[7:].strip()
        return supplied == token

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorised():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        path = unquote(urlparse(self.path).path)
        if path == "/health":
            try:
                bridge_health = self.app.bridge.health()
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "moben-auto-ppt-bridge",
                        "dry_run": self.app.config.dry_run,
                        "bridge": bridge_health,
                        "display_target": self.app.config.display_bridge_url,
                    },
                )
            except Exception as exc:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "error", "error": str(exc)},
                )
            return
        if path.startswith("/jobs/"):
            event_id = path.removeprefix("/jobs/").strip()
            job = self.app.store.get(event_id)
            if not job:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
            else:
                self._json(HTTPStatus.OK, job)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorised():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        path = unquote(urlparse(self.path).path)
        if path != "/events/recording-completed":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("请求内容长度需在 1~65536 字节")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求载荷必须为 JSON 对象")
            job, created = self.app.submit(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        status = HTTPStatus.ACCEPTED if created else HTTPStatus.OK
        self._json(
            status,
            {
                "accepted": created,
                "event_id": job["event_id"],
                "state": job["state"],
                "status_url": f"/jobs/{job['event_id']}",
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="录音卡 App -> 展示端自动PPT服务")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="检查桥接状态")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = ServiceConfig.load(args.config)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.dry_run:
        config.dry_run = True
    app = AutoPptService(config)
    if args.check:
        print(json.dumps(app.bridge.health(), ensure_ascii=False, indent=2))
        app.stop()
        return

    server = ThreadingHTTPServer((config.host, config.port), ApiHandler)
    server.app = app  # type: ignore[attr-defined]

    def stop_server(*_: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_server)

    LOG.info("service listening at http://%s:%s", config.host, config.port)
    LOG.info("display bridge target: %s", config.display_bridge_url)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()
