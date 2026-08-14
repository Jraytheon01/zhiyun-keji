# -*- coding: utf-8 -*-
"""Zhiyun Keji learning-task event -> TeleAgent local task receiver.

Supports two roles:
  * receiver: write into local TeleAgent SQLite (same machine mode)
  * relay: relay event to display computer AutoPPT service via HTTP
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
import os
import queue
import signal
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Literal
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


def _normalize_remote_base(url: str) -> str:
    if not url:
        return ""
    base = url.strip().rstrip("/")
    lowered = base.lower()
    for suffix in (
        "/events/recording-completed",
        "/events/learning-task",
        "/jobs",
        "/health",
        "/",
    ):
        if lowered.endswith(suffix):
            base = base[: -len(suffix)] if len(base) > len(suffix) else ""
            lowered = base.lower()
            base = base.rstrip("/")
    return base


def _http_request_json(
    *,
    method: Literal["GET", "POST"],
    url: str,
    payload: dict[str, Any] | None,
    token: str,
    timeout: float,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["X-Bridge-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to connect {url}: {exc}") from exc


@dataclass(slots=True)
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 18766
    bridge_mode: str = "receiver"  # receiver | relay
    remote_target_url: str = ""
    remote_token: str = ""
    remote_timeout_seconds: float = 8.0
    remote_retry_count: int = 3
    remote_retry_delay_seconds: float = 2.0
    ingest_complete_delay_seconds: float = 0.0
    bridge_token: str = ""
    teleagent_data_dir: str = ""
    channel: str = "wecom"
    allow_unconfigured_channel: bool = True
    new_session_per_event: bool = True
    focus_teleagent_on_submit: bool = True
    task_timeout_seconds: int = 900
    pickup_timeout_seconds: int = 30
    default_audience: str = "椤圭洰鍥㈤槦鍜岀鐞嗗眰"
    default_style: str = "商务简约"
    default_slides: int = 7
    default_output: str = "会议PPT.pptx"
    job_db: str = ""
    dry_run: bool = False

    @classmethod
    def load(cls, path: Path) -> "ServiceConfig":
        raw: dict[str, Any] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
        valid = cls.__dataclass_fields__.keys()
        config = cls(**{key: value for key, value in raw.items() if key in valid})
        config.bridge_mode = os.environ.get("AUTO_PPT_MODE", config.bridge_mode).strip().lower()
        if config.bridge_mode not in {"receiver", "relay"}:
            config.bridge_mode = "receiver"
        config.host = os.environ.get("MOBEN_PPT_HOST", config.host)
        config.port = int(os.environ.get("MOBEN_PPT_PORT", config.port))
        config.bridge_token = os.environ.get("MOBEN_PPT_TOKEN", config.bridge_token)
        config.remote_target_url = os.environ.get(
            "AUTO_PPT_REMOTE_TARGET_URL", config.remote_target_url
        )
        config.remote_token = os.environ.get("AUTO_PPT_REMOTE_TOKEN", config.remote_token)
        config.remote_timeout_seconds = float(
            os.environ.get("AUTO_PPT_REMOTE_TIMEOUT_SECONDS", config.remote_timeout_seconds)
        )
        config.remote_retry_count = int(os.environ.get("AUTO_PPT_REMOTE_RETRY_COUNT", config.remote_retry_count))
        config.remote_retry_delay_seconds = float(
            os.environ.get("AUTO_PPT_REMOTE_RETRY_DELAY_SECONDS", config.remote_retry_delay_seconds)
        )
        config.ingest_complete_delay_seconds = float(
            os.environ.get(
                "AUTO_PPT_INGEST_COMPLETE_DELAY_SECONDS",
                config.ingest_complete_delay_seconds,
            )
        )
        config.teleagent_data_dir = os.environ.get(
            "TELEAGENT_DATA_DIR", config.teleagent_data_dir
        )
        return config


def detect_teleagent_data_dir(explicit: str = "") -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    env_path = os.environ.get("TELEAGENT_DATA_DIR", "")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.extend(
        [
            Path.home() / ".local" / "share" / "TeleAgent",
            Path.home() / ".local" / "share" / "teleai-super-agent",
        ]
    )
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidates.extend([Path(local_app) / "TeleAgent", Path(local_app) / "teleai-super-agent"])
    for candidate in candidates:
        if (candidate / "im-service" / "im-service.db").exists():
            return candidate.resolve()
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"鏈壘鍒?TeleAgent im-service.db: {checked}")


def normalise_event(payload: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(payload.get("recording_id") or payload.get("meeting_id") or "").strip()
    meeting_title = str(payload.get("meeting_title") or payload.get("title") or "").strip()
    completed_at = str(payload.get("completed_at") or "").strip()
    use_latest = bool(payload.get("use_latest", not recording_id and not meeting_title))
    if not recording_id and not meeting_title and not use_latest:
        raise ValueError("recording_id、meeting_title 与 use_latest 三者至少提供一个")

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
        "source": str(payload.get("source") or "moben-recorder-app").strip(),
        "prompt": str(payload.get("prompt") or "").strip(),
        "learner_name": str(payload.get("learner_name") or "").strip(),
        "action": str(payload.get("action") or "").strip(),
        "focus": str(payload.get("focus") or "").strip(),
    }
    if event["slides"] is not None:
        try:
            event["slides"] = int(event["slides"])
        except (TypeError, ValueError) as exc:
            raise ValueError("slides 需要是整数") from exc
        if not 3 <= event["slides"] <= 30:
            raise ValueError("slides 需在 3 到 30 之间")

    if not event["event_id"]:
        stable = json_dumps(
            {
                "source": event["source"],
                "recording_id": recording_id,
                "meeting_title": meeting_title,
                "completed_at": completed_at,
            }
        )
        event["event_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    if len(event["event_id"]) > 128:
        raise ValueError("event_id 长度不能超过 128")
    return event

def build_prompt(event: dict[str, Any], config: ServiceConfig) -> str:
    if event.get("prompt"):
        return event["prompt"]
    audience = event["audience"] or config.default_audience
    style = event["style"] or config.default_style
    slides = event["slides"] if event["slides"] else config.default_slides
    output = event["output"] or config.default_output
    return (
        "请使用 Toby.AI录音卡助手，直接为我生成最近一场会议的 PPT。"
        f"采用默认参数：排版 PPT（可编辑 .pptx）、受众为{audience}、"
        f"{style}风格、约{slides}页，输出文件名为{output}。"
        "不要向我提问或等待确认；直接选择最近会议，优先读取已有纪要，"
        "纪要不可用时读取逐字稿，然后调用PPT能力生成并返回文件。"
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
                    session_id TEXT NOT NULL DEFAULT '',
                    response_text TEXT NOT NULL DEFAULT '',
                    file_paths TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(auto_ppt_job)")}
            if "session_id" not in columns:
                conn.execute("ALTER TABLE auto_ppt_job ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")

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
            "state",
            "message_id",
            "session_id",
            "response_text",
            "file_paths",
            "error",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
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
        result["request"] = json.loads(result.pop("request_json"))
        result["file_paths"] = json.loads(result["file_paths"] or "[]")
        return result

    def fail_incomplete_after_restart(self) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE auto_ppt_job
                set state='failed', error='bridge service restarted while job was active',
                    updated_at=?
                WHERE state IN ('queued', 'submitting', 'running')
                """,
                (now_text(),),
            )
            return cursor.rowcount


def focus_teleagent_window() -> bool:
    if os.name != "nt":
        return False

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    sw_restore = 9
    candidates: list[tuple[int, int]] = []

    def process_name(hwnd: int) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return ""
            return Path(buffer.value).name.lower()
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_window(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if process_name(hwnd) != "teleagent.exe":
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
        if area:
            candidates.append((area, hwnd))
        return True

    user32.EnumWindows(enum_window, 0)
    if not candidates:
        LOG.warning("TeleAgent desktop window was not found; task still submitted")
        return False
    _area, hwnd = max(candidates)
    user32.ShowWindow(hwnd, sw_restore)
    user32.BringWindowToTop(hwnd)
    focused = bool(user32.SetForegroundWindow(hwnd))
    if not focused:
        user32.FlashWindow(hwnd, True)
    return focused


def open_new_teleagent_task() -> bool:
    """Open TeleAgent's visible "new task" view before IM bridge injection.

    TeleAgent 2.1.x does not expose a public local API for creating and selecting a
    renderer session.  Clearing ``im_channel_profile.session_id`` alone therefore
    reuses the currently selected historical conversation.  The desktop's new-task
    control is stable in the left sidebar, so click it relative to the main window
    and let TeleAgent create the real session when the injected prompt is submitted.
    """
    if os.name != "nt" or not focus_teleagent_window():
        return False

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width = max(0, rect.right - rect.left)
    height = max(0, rect.bottom - rect.top)
    if width < 640 or height < 480:
        return False

    old_position = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old_position))
    # TeleAgent 2.1.5: the "new task" entry is centred at roughly 5.8% x,
    # 11.2% y of the application window. Relative coordinates also work when
    # Windows display scaling or the window size changes.
    target_x = rect.left + int(width * 0.058)
    target_y = rect.top + int(height * 0.112)
    user32.SetCursorPos(target_x, target_y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    user32.SetCursorPos(old_position.x, old_position.y)
    time.sleep(0.8)
    LOG.info("Opened TeleAgent new-task view at relative desktop coordinate")
    return True


class BridgeModeError(RuntimeError):
    pass


class TeleAgentBridge:
    TERMINAL = {"to_deliver", "delivered", "skipped", "failed"}

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.data_dir = detect_teleagent_data_dir(config.teleagent_data_dir)
        self.im_db = self.data_dir / "im-service" / "im-service.db"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.im_db, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_health(self) -> dict[str, Any]:
        with self.connect() as conn:
            profile = conn.execute(
                "SELECT channel, enabled, auth_status, session_id "
                "FROM im_channel_profile WHERE channel=?",
                (self.config.channel,),
            ).fetchone()
        return {
            "data_dir": str(self.data_dir),
            "im_db": str(self.im_db),
            "channel": dict(profile) if profile else None,
            "ready": bool(profile and profile["enabled"]),
            "local_unconfigured_mode": bool(profile and profile["auth_status"] != "valid"),
        }

    def _latest_visible_session_id(self) -> str:
        teleagent_db = self.data_dir / "teleagent.db"
        if not teleagent_db.exists():
            return ""
        conn = sqlite3.connect(teleagent_db, timeout=10)
        try:
            row = conn.execute(
                "SELECT id FROM session WHERE title NOT LIKE '_SYS_%' "
                "ORDER BY time_updated DESC LIMIT 1"
            ).fetchone()
            return str(row[0]) if row else ""
        finally:
            conn.close()

    def _create_visible_session(
        self, event_id: str, event: dict[str, Any] | None = None
    ) -> str:
        """Create an isolated TeleAgent session that is visible in the sidebar."""
        teleagent_db = self.data_dir / "teleagent.db"
        if not teleagent_db.exists():
            raise RuntimeError(f"TeleAgent 主数据库不存在: {teleagent_db}")

        session_id = f"ses_{uuid.uuid4().hex}"
        slug = f"toby-recording-{uuid.uuid4().hex[:12]}"
        recording_id = str((event or {}).get("recording_id") or "").strip()
        meeting_title = str((event or {}).get("meeting_title") or "").strip()
        learner_name = str((event or {}).get("learner_name") or "学习者").strip()
        action = str((event or {}).get("action") or "学习任务").strip()
        label = meeting_title or recording_id or event_id
        title = f"智云课迹 · {learner_name} · {action} · {label}"
        timestamp_ms = int(time.time() * 1000)

        conn = sqlite3.connect(teleagent_db, timeout=10)
        try:
            template = conn.execute(
                "SELECT project_id, directory, version FROM session "
                "WHERE parent_id IS NULL AND directory <> '' "
                "ORDER BY time_updated DESC LIMIT 1"
            ).fetchone()
            project_id = template[0] if template else "global"
            directory = (
                template[1]
                if template
                else str(self.data_dir / "TeleAgent的工作空间")
            )
            version = template[2] if template else "1.2.27"
            teleagent_config_root = (Path.home() / ".config" / "TeleAgent").as_posix()
            permissions = json_dumps([
                {"permission": "external_directory", "pattern": f"{teleagent_config_root}/*", "action": "allow"},
                {"permission": "question", "pattern": "*", "action": "deny"},
            ])
            conn.execute(
                """
                INSERT INTO session (
                    id, project_id, parent_id, slug, directory, title, version,
                    permission, time_created, time_updated, time_archived
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    project_id,
                    slug,
                    directory,
                    title,
                    version,
                    permissions,
                    timestamp_ms,
                    timestamp_ms,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return session_id

    def _profile(self) -> sqlite3.Row:
        with self.connect() as conn:
            profile = conn.execute(
                "SELECT * FROM im_channel_profile WHERE channel=?",
                (self.config.channel,),
            ).fetchone()
        if not profile:
            raise RuntimeError(f"TeleAgent IM channel 涓嶅瓨鍦? {self.config.channel}")
        if not profile["enabled"]:
            raise RuntimeError(f"TeleAgent IM channel 宸插仠鐢? {self.config.channel}")
        if profile["auth_status"] != "valid" and not self.config.allow_unconfigured_channel:
            raise RuntimeError(
                f"TeleAgent IM channel {self.config.channel} 鏈牎楠屾湁鏁堬紝"
                "浠呭厑璁稿厑璁?allow_unconfigured_channel 鏃?POC 缁х画杩愯"
            )
        return profile

    def submit(self, event_id: str, prompt: str, event: dict[str, Any] | None = None) -> str:
        profile = self._profile()
        external_id = f"zhiyun-keji:{event_id}"
        prior_session_id = self._latest_visible_session_id()
        if self.config.new_session_per_event and self.config.focus_teleagent_on_submit:
            if not open_new_teleagent_task():
                raise RuntimeError("TeleAgent 新建任务页未能打开，本次任务未投递")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM im_message WHERE channel=? "
                "AND inbound_external_message_id=?",
                (self.config.channel, external_id),
            ).fetchone()
            if existing:
                if self.config.focus_teleagent_on_submit:
                    focus_teleagent_window()
                return str(existing["id"])

            session_id = profile["session_id"] or ""
            desired_title = ""
            if self.config.new_session_per_event:
                # TeleAgent 2.1.x 的渲染进程必须自己创建会话。把手工写入
                # teleagent.db 的 session_id 交给 IM 服务，会取走任务却不会
                # 真正提交给 Agent，最终触发 renderer_idle_collecting_watchdog。
                # 先清空路由，wait() 再接管渲染进程创建的真实会话。
                session_id = ""
                meeting_title = str((event or {}).get("meeting_title") or "").strip()
                learner_name = str((event or {}).get("learner_name") or "学习者").strip()
                action = str((event or {}).get("action") or "学习任务").strip()
                label = meeting_title or str((event or {}).get("recording_id") or event_id)
                desired_title = f"智云课迹 · {learner_name} · {action} · {label}"
                conn.execute(
                    "UPDATE im_channel_profile SET session_id='' WHERE channel=?",
                    (self.config.channel,),
                )

            message_id = f"msg_{uuid.uuid4().hex}"
            request_id = str(uuid.uuid4())
            now = now_text()
            conn.execute(
                """
                INSERT INTO im_message (
                    id, channel, session_id, inbound_source, inbound_text,
                    inbound_external_message_id, inbound_sender_user_id,
                    inbound_sender_account_id, route_target, status,
                    opencode_error, submitted_at, outbound_text, file_paths,
                    result_error, result_completed_at, delivered_at,
                    deliver_error, request_id, extra, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 'desktop', ?, ?, 'moben-recorder', 'moben-recorder',
                    '{}', 'to_submit', '', '', '', '[]', '', '', '', '', ?, ?, ?, ?
                )
                """,
                (
                    message_id,
                    self.config.channel,
                    session_id,
                    prompt,
                    external_id,
                    request_id,
                    json_dumps(
                        {
                            "source": "zhiyun-keji-platform",
                            "event_id": event_id,
                            "new_session": self.config.new_session_per_event,
                            "prior_session_id": prior_session_id,
                            "desired_title": desired_title,
                            "injected_at": now,
                        }
                    ),
                    now,
                    now,
                ),
            )
        if self.config.focus_teleagent_on_submit:
            focus_teleagent_window()
        return message_id

    def _adopt_renderer_session(self, message_id: str) -> None:
        """Rename the real renderer-created session and grant education-skill access."""
        with self.connect() as conn:
            message = conn.execute(
                "SELECT extra FROM im_message WHERE id=?", (message_id,)
            ).fetchone()
            profile = conn.execute(
                "SELECT session_id FROM im_channel_profile WHERE channel=?",
                (self.config.channel,),
            ).fetchone()
        if not message or not profile:
            return
        try:
            extra = json.loads(message["extra"] or "{}")
        except json.JSONDecodeError:
            extra = {}
        title = str(extra.get("desired_title") or "").strip()
        if not title:
            return
        teleagent_db = self.data_dir / "teleagent.db"
        session_id = str(profile["session_id"] or "")
        if not session_id:
            # 2.1.x 在本地未配置 IM 渠道下不会回写 profile.session_id，
            # 但会更新真实处理会话的 time_updated。Receiver 单任务串行，取最近
            # 更新的非系统会话即可把业务标题与任务记录对齐。
            lookup = sqlite3.connect(teleagent_db, timeout=10)
            try:
                recent = lookup.execute(
                    "SELECT id FROM session WHERE title NOT LIKE '_SYS_%' "
                    "ORDER BY time_updated DESC LIMIT 1"
                ).fetchone()
                session_id = str(recent[0]) if recent else ""
            finally:
                lookup.close()
        prior_session_id = str(extra.get("prior_session_id") or "")
        if extra.get("new_session") and session_id == prior_session_id:
            # The renderer is still processing the previously selected history
            # item. Do not relabel it or report a false persistent conversation.
            return
        if not session_id:
            return
        teleagent_config_root = (Path.home() / ".config" / "TeleAgent").as_posix()
        permissions = json_dumps([
            {"permission": "external_directory", "pattern": f"{teleagent_config_root}/*", "action": "allow"},
            {"permission": "question", "pattern": "*", "action": "deny"},
        ])
        conn = sqlite3.connect(teleagent_db, timeout=10)
        try:
            conn.execute(
                "UPDATE session SET title=?, permission=?, time_updated=? WHERE id=?",
                (title, permissions, int(time.time() * 1000), session_id),
            )
            conn.commit()
        finally:
            conn.close()
        with self.connect() as conn:
            conn.execute(
                "UPDATE im_message SET session_id=? WHERE id=?",
                (session_id, message_id),
            )

    def read_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM im_message WHERE id=?", (message_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["file_paths"] = json.loads(result["file_paths"] or "[]")
        except json.JSONDecodeError:
            result["file_paths"] = []
        return result

    def wait(self, message_id: str) -> dict[str, Any]:
        started = time.monotonic()
        picked_up = False
        last_status = ""
        while time.monotonic() - started < self.config.task_timeout_seconds:
            message = self.read_message(message_id)
            if not message:
                raise RuntimeError("TeleAgent 本地任务不存在")
            status = message["status"]
            if status != last_status:
                LOG.info("TeleAgent message %s status=%s", message_id, status)
                last_status = status
            if status != "to_submit":
                picked_up = True
                self._adopt_renderer_session(message_id)
            if status in self.TERMINAL:
                # _adopt_renderer_session may have persisted the new ID after the
                # message snapshot above was read; reload it before validation.
                message = self.read_message(message_id) or message
                try:
                    extra = json.loads(message.get("extra") or "{}")
                except json.JSONDecodeError:
                    extra = {}
                if extra.get("new_session") and not message.get("session_id"):
                    raise RuntimeError(
                        "TeleAgent 已生成回答，但未创建可找回的独立会话；"
                        "本次不标记为成功"
                    )
                if status == "failed":
                    if (
                        (message.get("file_paths") or message.get("outbound_text"))
                        and not message.get("result_error")
                        and not message.get("opencode_error")
                    ):
                        LOG.warning(
                            "TeleAgent generated a result but channel delivery failed: %s",
                            message.get("deliver_error", ""),
                        )
                        return message
                    error = (
                        message.get("result_error")
                        or message.get("opencode_error")
                        or message.get("deliver_error")
                        or "TeleAgent 浠诲姟澶辫触"
                    )
                    raise RuntimeError(error)
                return message
            if not picked_up and time.monotonic() - started > self.config.pickup_timeout_seconds:
                raise TimeoutError("TeleAgent IM 服务长时间未接收任务")
            time.sleep(1 if not picked_up else 3)
        raise TimeoutError("TeleAgent 鐢熸垚 PPT 瓒呮椂")


class RemoteDisplayBridge:
    TERMINAL = {"completed", "failed", "skipped"}

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.base = _normalize_remote_base(config.remote_target_url)
        if not self.base:
            raise BridgeModeError("AUTO_PPT_REMOTE_TARGET_URL 未配置")
        self.events_url = f"{self.base}/events/recording-completed"
        self.timeout = max(1.0, float(config.remote_timeout_seconds))
        self.retries = max(0, int(config.remote_retry_count))
        self.retry_delay = max(0.0, float(config.remote_retry_delay_seconds))

    def submit(self, event_id: str, prompt: str, event: dict[str, Any] | None = None) -> str:
        if self.config.ingest_complete_delay_seconds > 0:
            time.sleep(self.config.ingest_complete_delay_seconds)
        payload = dict(event or {})
        payload["prompt"] = prompt
        payload["event_id"] = event_id
        payload["source"] = payload.get("source") or "recording-server-bridge"
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = _http_request_json(
                    method="POST",
                    url=self.events_url,
                    payload=payload,
                    token=self.config.remote_token,
                    timeout=self.timeout,
                )
                return str(response.get("event_id") or event_id)
            except Exception as exc:  # pragma: no cover - defensive
                last = exc
                if _ == self.retries:
                    break
                time.sleep(self.retry_delay)
        raise BridgeModeError(f"relay submit failed: {last}")

    def read_job(self, event_id: str) -> dict[str, Any]:
        return _http_request_json(
            method="GET",
            url=f"{self.base}/jobs/{event_id}",
            payload=None,
            token=self.config.remote_token,
            timeout=self.timeout,
        )

    def wait(self, message_id: str) -> dict[str, Any]:
        started = time.monotonic()
        while time.monotonic() - started < self.config.task_timeout_seconds:
            job = self.read_job(message_id)
            state = str(job.get("state") or "")
            if state in self.TERMINAL:
                if state == "failed":
                    error = job.get("error") or "remote task failed"
                    raise RuntimeError(error)
                return {
                    "outbound_text": job.get("response_text", ""),
                    "file_paths": job.get("file_paths", []),
                    "status": state,
                }
            time.sleep(2)
        raise TimeoutError("display bridge job timeout")

    def get_health(self) -> dict[str, Any]:
        return _http_request_json(
            method="GET",
            url=f"{self.base}/health",
            payload=None,
            token=self.config.remote_token,
            timeout=self.timeout,
        )


def build_bridge(config: ServiceConfig):
    if config.bridge_mode == "relay":
        return RemoteDisplayBridge(config)
    if config.bridge_mode == "receiver":
        return TeleAgentBridge(config)
    raise BridgeModeError(f"unsupported bridge_mode={config.bridge_mode}")


class AutoPptService:
    def __init__(self, config: ServiceConfig):
        self.config = config
        db_path = Path(config.job_db).expanduser() if config.job_db else SCRIPT_DIR / ".auto_ppt_jobs.db"
        self.store = JobStore(db_path)
        interrupted = self.store.fail_incomplete_after_restart()
        if interrupted:
            LOG.warning("marked %s interrupted jobs as failed", interrupted)
        self.bridge = build_bridge(config)
        self.jobs: queue.Queue[str | None] = queue.Queue()
        self.worker = threading.Thread(target=self._work_loop, daemon=True)
        self.worker.start()

    def submit(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        event = normalise_event(payload)
        prompt = build_prompt(event, self.config)
        created = self.store.create(event, prompt)
        if created:
            self.jobs.put(event["event_id"])
        job = self.store.get(event["event_id"])
        assert job is not None
        return job, created

    def _work_loop(self) -> None:
        while True:
            event_id = self.jobs.get()
            if event_id is None:
                return
            try:
                job = self.store.get(event_id)
                if not job or job["state"] != "queued":
                    continue
                if self.config.dry_run:
                    self.store.update(
                        event_id,
                        state="completed",
                        response_text="dry-run: skip submit",
                    )
                    continue
                self.store.update(event_id, state="submitting")
                message_id = self.bridge.submit(event_id, job["prompt"], job["request"])
                self.store.update(event_id, state="running", message_id=message_id)
                result = self.bridge.wait(message_id)
                self.store.update(
                    event_id,
                    state="completed",
                    session_id=result.get("session_id", ""),
                    response_text=result.get("outbound_text", ""),
                    file_paths=json_dumps(result.get("file_paths", [])),
                )
                if self.config.focus_teleagent_on_submit:
                    focus_teleagent_window()
            except Exception as exc:
                LOG.exception("job %s failed", event_id)
                self.store.update(event_id, state="failed", error=str(exc))
            finally:
                self.jobs.task_done()

    def stop(self) -> None:
        self.jobs.put(None)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "MobenAutoPpt/0.2"

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
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "zhiyun-keji-teleagent-receiver",
                        "mode": self.app.config.bridge_mode,
                        "remote_target_url": self.app.config.remote_target_url,
                        "dry_run": self.app.config.dry_run,
                        "bridge": self.app.bridge.get_health(),
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
        if path == "/focus":
            focused = focus_teleagent_window()
            self._json(HTTPStatus.OK if focused else HTTPStatus.SERVICE_UNAVAILABLE,
                       {"focused": focused})
            return
        if path not in {"/events/recording-completed", "/events/learning-task"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("璇锋眰闀垮害搴斿湪 1~65536 瀛楄妭涔嬮棿")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("璇锋眰浣撳繀椤绘槸 JSON 瀵硅薄")
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
    parser = argparse.ArgumentParser(description="浼氳褰曢煶鍗?-> TeleAgent 鑷姩鐢熸垚 PPT 鏈嶅姟")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--mode")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="妫€鏌?TeleAgent / 杩滅杩炴帴")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = ServiceConfig.load(args.config)
    if args.mode:
        config.bridge_mode = args.mode.strip().lower()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.dry_run:
        config.dry_run = True

    if config.bridge_mode == "relay" and not config.remote_target_url:
        raise SystemExit("relay 妯″紡蹇呴』璁剧疆 AUTO_PPT_REMOTE_TARGET_URL 鎴?config 涓?remote_target_url")

    app = AutoPptService(config)
    if args.check:
        print(json.dumps(app.bridge.get_health(), ensure_ascii=False, indent=2))
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
    LOG.info("mode=%s remote_target_url=%s", config.bridge_mode, config.remote_target_url)
    if config.bridge_mode == "receiver":
        LOG.info("TeleAgent data dir: %s", app.bridge.data_dir)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()

