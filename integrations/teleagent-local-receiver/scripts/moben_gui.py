# -*- coding: utf-8 -*-
"""
墨本AI消息监控 - 图形化界面版
功能：定时检查墨本AI新消息，预览拉取的文本，调整间隔，一键启停
核心：通过墨本AI REST API获取消息，通过IM SQLite注入转发给TeleClaw AI

泛化版本：所有路径自动探测，不硬编码用户目录。
"""
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
from datetime import datetime

try:
    import requests
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"], capture_output=True)
    import requests

try:
    import websocket
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "websocket-client", "-q"], capture_output=True)
    import websocket

# ============ 路径自动探测 ============
def _detect_teleclaw_data_dir():
    """自动探测TeleClaw数据目录。"""
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(local_app, "teleai-super-agent"),
        os.path.join(os.path.expanduser("~"), ".local", "share", "teleai-super-agent"),
    ]
    for d in candidates:
        im_db = os.path.join(d, "im-service", "im-service.db")
        if os.path.exists(im_db):
            return d
    # 默认返回第一个候选
    return candidates[0] if candidates else ""

TELECLAW_DATA_DIR = _detect_teleclaw_data_dir()
IM_DB = os.path.join(TELECLAW_DATA_DIR, "im-service", "im-service.db")
OPENCODE_DB = os.path.join(TELECLAW_DATA_DIR, "opencode-dev.db")
IM_HTTP = "http://127.0.0.1:17802"

# ============ 配置 ============
MOBEN_BASE = "https://moben.cn"
CDP_PORT = 9222  # 仅用于首次获取JWT token
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, ".moben_state")
CONFIG_FILE = os.path.join(SCRIPT_DIR, ".moben_gui_config")
TOKEN_FILE = os.path.join(SCRIPT_DIR, ".moben_token")


# ============ 墨本AI API 客户端 ============
def _fetch_token_from_cdp():
    """通过 Edge CDP 从 localStorage 获取 JWT token（备用方式）。"""
    try:
        import urllib.request
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5)
        pages = json.loads(resp.read())
        moben_pages = [p for p in pages if "moben" in p.get("url", "") and p.get("type") == "page"]
        if not moben_pages:
            return None
        ws_url = moben_pages[0]["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url, timeout=10)
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": "localStorage.getItem('pocket-sage-token')"}
        }))
        result = json.loads(ws.recv())
        ws.close()
        value = result.get("result", {}).get("result", {}).get("value")
        return value if value else None
    except Exception:
        return None


def _login_via_sms(phone):
    """通过手机验证码登录墨本AI，返回 (JWT token, error)。

    流程：1) 发送验证码 2) 弹窗输入验证码 3) 登录获取token
    手机号自动转为 E.164 格式（如 +8613992193562）。
    """
    # 自动补 +86 前缀
    if phone and not phone.startswith("+"):
        phone = f"+86{phone}"

    # 发送验证码
    try:
        r = requests.post(f"{MOBEN_BASE}/api/auth/send-code",
                          json={"phone": phone}, timeout=15)
        data = r.json()
        if not data.get("success"):
            return None, f"发送验证码失败: {data.get('message', data.get('error', '未知错误'))}"
    except Exception as e:
        return None, f"网络请求失败: {e}"

    # 弹窗输入验证码
    code = tk.simpledialog.askstring("验证码", f"已向 {phone} 发送验证码，请输入6位数字：",
                                      parent=None)
    if not code:
        return None, "已取消"

    # 登录
    try:
        r = requests.post(f"{MOBEN_BASE}/api/auth/login",
                          json={"phone": phone, "code": code}, timeout=15)
        data = r.json()
        if data.get("success"):
            token = data.get("data", {}).get("token", "")
            if token:
                return token, None
            return None, "登录响应中无token"
        return None, f"登录失败: {data.get('message', data.get('error', '未知错误'))}"
    except Exception as e:
        return None, f"登录请求失败: {e}"


def get_moben_token(force_refresh=False):
    """获取墨本AI的JWT token。

    获取优先级：本地缓存 → CDP(Edge) → 手机验证码登录
    """
    if not force_refresh and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            token = cached.get("token", "")
            expires = cached.get("expires", 0)
            if token and time.time() < expires - 86400:
                return token
        except Exception:
            pass

    # 尝试CDP方式
    token = _fetch_token_from_cdp()
    if token:
        _save_token(token)
        return token

    # CDP失败，不在此处弹登录窗口（留给GUI层处理）
    return None


def _save_token(token):
    """保存token到本地文件。"""
    try:
        import base64
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        expires = data.get("exp", 0)
    except Exception:
        expires = 0

    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"token": token, "expires": expires}, f)
    except Exception:
        pass


def api_request(method, path, token, params=None, json_data=None, timeout=15):
    """发送墨本AI API请求。"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{MOBEN_BASE}{path}"
    new_token = token
    try:
        r = getattr(requests, method)(url, headers=headers, params=params,
                                       json=json_data, timeout=timeout)
        if r.status_code == 401:
            new_token = get_moben_token(force_refresh=True)
            if new_token and new_token != token:
                headers["Authorization"] = f"Bearer {new_token}"
                r = getattr(requests, method)(url, headers=headers, params=params,
                                               json=json_data, timeout=timeout)
        return r, new_token
    except Exception as e:
        return None, token


def get_conversations(token, limit=10, offset=0):
    """获取对话列表（按最新排序）。返回 (conversations, new_token, error)"""
    r, new_token = api_request("get", "/api/history/conversations", token,
                                params={"limit": limit, "offset": offset})
    if r is None:
        return [], token, "网络请求失败"
    if r.status_code != 200:
        return [], new_token, f"API返回 {r.status_code}"
    try:
        data = r.json()
        if data.get("success"):
            return data["data"].get("conversations", []), new_token, None
        return [], new_token, data.get("error", "未知错误")
    except Exception as e:
        return [], new_token, f"解析响应失败: {e}"


def get_conversation_messages(token, chat_id, limit=20, before_id=None, after_id=None):
    """获取单个对话的消息列表。返回 (messages, conversation, new_token, error)"""
    params = {"limit": limit}
    if before_id:
        params["beforeId"] = before_id
    if after_id:
        params["afterId"] = after_id

    r, new_token = api_request("get", f"/api/history/conversations/{chat_id}", token,
                                params=params)
    if r is None:
        return [], {}, token, "网络请求失败"
    if r.status_code != 200:
        return [], {}, new_token, f"API返回 {r.status_code}"
    try:
        data = r.json()
        if data.get("success"):
            conv = data["data"].get("conversation", {})
            msgs = data["data"].get("messages", [])
            return msgs, conv, new_token, None
        return [], {}, new_token, data.get("error", "未知错误")
    except Exception as e:
        return [], {}, new_token, f"解析响应失败: {e}"


# ============ 状态管理 ============
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_chat_id": "", "last_message_id": 0, "last_message": ""}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("interval", 0) < 10:
                    cfg["interval"] = cfg["interval"] * 60
                return cfg
        except Exception:
            pass
    return {"interval": 30, "auto_send": True}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ============ TeleClaw 发送（IM SQLite 注入方案） ============
def _load_wecom_config():
    """从 IM 服务配置文件读取 WeCom 渠道信息。"""
    im_dir = os.path.join(TELECLAW_DATA_DIR, "im-service")
    try:
        with open(os.path.join(im_dir, "wecom-state.json"), "r", encoding="utf-8") as f:
            wecom_state = json.load(f)
        with open(os.path.join(im_dir, "conversation-sessions.json"), "r", encoding="utf-8") as f:
            conv_sessions = json.load(f)
        session_id = wecom_state.get("sessionId", "")
        route_map_path = os.path.join(im_dir, "route-map.json")
        route_target = {}
        if os.path.exists(route_map_path):
            with open(route_map_path, "r", encoding="utf-8") as f:
                route_map = json.load(f)
            wecom_routes = route_map.get("wecom", [])
            if wecom_routes:
                latest = wecom_routes[-1]
                route_target = {
                    "chatId": latest.get("targetChatId", ""),
                    "fromUserId": latest.get("targetUserId", ""),
                }
        return {
            "connected": wecom_state.get("connected", False),
            "session_id": session_id,
            "user_id": wecom_state.get("userId", ""),
            "account_id": wecom_state.get("accountId", ""),
            "route_target": route_target,
        }
    except Exception:
        return {"connected": False, "session_id": "", "user_id": "",
                "account_id": "", "route_target": {}}


def is_teleclaw_busy():
    """检查 TeleClaw 是否正在处理任务。"""
    import sqlite3
    try:
        conn = sqlite3.connect(IM_DB)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, status, inbound_text FROM im_message "
            "WHERE status IN ('to_submit', 'collecting') "
            "ORDER BY created_at DESC LIMIT 3"
        )
        rows = cursor.fetchall()
        conn.close()
        if rows:
            detail = ", ".join(f"{r[1]}" for r in rows)
            return True, detail
        return False, ""
    except Exception as e:
        return False, f"查询失败: {e}"


def send_to_teleclaw(text, timeout=120):
    """通过 IM SQLite 注入将消息发送给 TeleClaw AI。返回 (success, response)"""
    import sqlite3
    import uuid

    wecom = _load_wecom_config()
    if not wecom["connected"] or not wecom["session_id"]:
        return False, "WeCom 渠道未连接或 session_id 为空"

    msg_id = f"msg_{uuid.uuid4().hex[:12]}{uuid.uuid4().hex[:12]}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    submit_ts = int(time.time() * 1000)

    message = {
        "id": msg_id,
        "channel": "wecom",
        "session_id": wecom["session_id"],
        "inbound_source": "channel_bot",
        "inbound_text": text,
        "inbound_external_message_id": f"moben_{int(time.time())}",
        "inbound_sender_user_id": wecom["user_id"],
        "inbound_sender_account_id": wecom["account_id"],
        "route_target": json.dumps(wecom["route_target"]) if wecom["route_target"] else "{}",
        "status": "to_submit",
        "opencode_error": "",
        "submitted_at": "",
        "outbound_text": "",
        "file_paths": "[]",
        "result_error": "",
        "result_completed_at": "",
        "delivered_at": "",
        "deliver_error": "",
        "request_id": str(uuid.uuid4()),
        "extra": json.dumps({"source": "moben_monitor", "injected_at": now_str}),
        "created_at": now_str,
        "updated_at": now_str,
    }

    try:
        conn = sqlite3.connect(IM_DB)
        cursor = conn.cursor()
        cols = ", ".join(message.keys())
        placeholders = ", ".join(["?"] * len(message))
        cursor.execute(f"INSERT INTO im_message ({cols}) VALUES ({placeholders})", list(message.values()))
        conn.commit()
        conn.close()
    except Exception as e:
        return False, f"写入 IM 数据库失败: {e}"

    for _ in range(15):
        time.sleep(1)
        try:
            conn = sqlite3.connect(IM_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT status, opencode_error FROM im_message WHERE id = ?", (msg_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0] != "to_submit":
                break
        except Exception:
            pass
    else:
        return False, "超时：IM 服务未捡起消息"

    if row[0] == "failed":
        return False, f"OpenCode 处理失败: {row[1]}"

    deadline = time.time() + timeout
    response_text = ""
    while time.time() < deadline:
        time.sleep(3)
        try:
            conn = sqlite3.connect(OPENCODE_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.data FROM part p
                JOIN message m ON p.message_id = m.id AND p.session_id = m.session_id
                WHERE m.session_id = ? AND m.time_created > ? AND m.time_created < ? + 300000
                  AND p.data LIKE '%"type":"text"%'
                ORDER BY p.time_created DESC LIMIT 3
            """, (wecom["session_id"], submit_ts, submit_ts))
            parts = cursor.fetchall()
            conn.close()
            for part in parts:
                try:
                    data = json.loads(part[0])
                    if data.get("type") == "text" and data.get("text", "").strip():
                        response_text = data["text"].strip()
                        break
                except Exception:
                    continue
            if response_text:
                break
        except Exception:
            continue

        try:
            conn = sqlite3.connect(IM_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT status, outbound_text, result_error FROM im_message WHERE id = ?", (msg_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0] in ("to_deliver", "delivered"):
                response_text = row[1] or response_text
                break
            if row and row[0] == "failed":
                return False, f"AI 处理失败: {row[2]}"
        except Exception:
            pass

    if not response_text:
        return False, "超时：AI 未生成回复"

    try:
        requests.post(f"{IM_HTTP}/im/common/submit-result", json={
            "channel": "wecom",
            "sessionId": wecom["session_id"],
            "status": "success",
            "text": response_text,
            "files": [],
        }, timeout=10)
    except Exception:
        pass

    return True, response_text


# ============ 核心检查逻辑（API方式） ============
def do_check():
    """通过墨本AI REST API检查新消息。返回 (has_new, message_text, error)"""
    token = get_moben_token()
    if not token:
        return False, "", "无法获取墨本AI token（请确保Edge浏览器打开moben.cn且已登录）"

    convs, token, err = get_conversations(token, limit=5)
    if err:
        return False, "", f"获取对话列表失败: {err}"

    if not convs:
        return False, "", ""

    latest = convs[0]
    chat_id = latest["chatId"]
    msgs, conv_info, token, err = get_conversation_messages(token, chat_id, limit=20)
    if err:
        return False, "", f"获取消息失败: {err}"

    user_msgs = [m for m in msgs if m.get("role") == "user"]
    if not user_msgs:
        return False, "", ""

    latest_user_msg = user_msgs[-1]
    msg_text = (latest_user_msg.get("content") or "").strip()
    msg_id = latest_user_msg.get("id", 0)

    if not msg_text:
        return False, "", ""

    state = load_state()
    last_chat_id = state.get("last_chat_id", "")
    last_msg_id = state.get("last_message_id", 0)

    has_new = (chat_id != last_chat_id) or (msg_id > last_msg_id)

    if has_new:
        save_state({
            "last_chat_id": chat_id,
            "last_message_id": msg_id,
            "last_message": msg_text,
            "timestamp": time.time(),
        })

    return has_new, msg_text if has_new else "", ""


# ============ GUI 应用 ============
class MobenMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("墨本AI消息监控")
        self.root.geometry("620x780")
        self.root.resizable(True, True)

        self.bg = "#1a1a2e"
        self.card_bg = "#16213e"
        self.accent = "#0f3460"
        self.highlight = "#e94560"
        self.text_color = "#eaeaea"
        self.dim_text = "#8899aa"
        self.green = "#00d672"
        self.orange = "#ff9f43"

        self.root.configure(bg=self.bg)

        self.config = load_config()
        self.monitoring = False
        self.monitor_thread = None
        self.last_message = ""
        self.last_check_time = ""
        self.history = []
        self._token_ok = False

        self._build_ui()
        self._load_state_to_ui()

    def _build_ui(self):
        top_frame = tk.Frame(self.root, bg=self.accent, height=56)
        top_frame.pack(fill="x")
        top_frame.pack_propagate(False)

        self.status_dot = tk.Canvas(top_frame, width=18, height=18, bg=self.accent, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(16, 8), pady=18)
        self.dot_id = self.status_dot.create_oval(2, 2, 16, 16, fill=self.dim_text, outline="")

        self.status_label = tk.Label(top_frame, text="未启动", font=("Microsoft YaHei", 13, "bold"),
                                      bg=self.accent, fg=self.text_color)
        self.status_label.pack(side="left", pady=18)

        self.time_label = tk.Label(top_frame, text="", font=("Microsoft YaHei", 10),
                                    bg=self.accent, fg=self.dim_text)
        self.time_label.pack(side="right", padx=16, pady=18)

        ctrl_frame = tk.Frame(self.root, bg=self.card_bg, bd=0)
        ctrl_frame.pack(fill="x", padx=12, pady=(12, 6))

        row1 = tk.Frame(ctrl_frame, bg=self.card_bg)
        row1.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(row1, text="检查间隔", font=("Microsoft YaHei", 10), bg=self.card_bg, fg=self.dim_text).pack(side="left")
        self.interval_var = tk.IntVar(value=self.config.get("interval", 30))
        self.interval_spin = tk.Spinbox(row1, from_=10, to=600, increment=10,
                                          textvariable=self.interval_var,
                                          width=5, font=("Consolas", 12), justify="center",
                                          bg="#0d1b2a", fg=self.text_color, insertbackground=self.text_color,
                                          buttonbackground=self.accent, relief="flat")
        self.interval_spin.pack(side="left", padx=(8, 4))
        tk.Label(row1, text="秒", font=("Microsoft YaHei", 10), bg=self.card_bg, fg=self.dim_text).pack(side="left")

        self.auto_send_var = tk.BooleanVar(value=self.config.get("auto_send", True))
        self.auto_send_cb = tk.Checkbutton(row1, text="自动发送到TeleClaw", variable=self.auto_send_var,
                                            font=("Microsoft YaHei", 10), bg=self.card_bg, fg=self.text_color,
                                            selectcolor=self.accent, activebackground=self.card_bg,
                                            activeforeground=self.text_color)
        self.auto_send_cb.pack(side="right")

        row2 = tk.Frame(ctrl_frame, bg=self.card_bg)
        row2.pack(fill="x", padx=16, pady=(6, 14))

        self.start_btn = tk.Button(row2, text="启动监控", font=("Microsoft YaHei", 11, "bold"),
                                     bg=self.highlight, fg="white", activebackground="#c73e54",
                                     relief="flat", cursor="hand2", padx=20, pady=4,
                                     command=self.toggle_monitor)
        self.start_btn.pack(side="left")

        self.check_btn = tk.Button(row2, text="立即检查", font=("Microsoft YaHei", 10),
                                     bg=self.accent, fg=self.text_color, activebackground="#1a4a7a",
                                     relief="flat", cursor="hand2", padx=14, pady=4,
                                     command=self.manual_check)
        self.check_btn.pack(side="left", padx=(10, 0))

        self.init_btn = tk.Button(row2, text="初始化基线", font=("Microsoft YaHei", 10),
                                    bg=self.accent, fg=self.text_color, activebackground="#1a4a7a",
                                    relief="flat", cursor="hand2", padx=14, pady=4,
                                    command=self.init_baseline)
        self.init_btn.pack(side="left", padx=(10, 0))

        conn_frame = tk.Frame(self.root, bg=self.card_bg, bd=0)
        conn_frame.pack(fill="x", padx=12, pady=(0, 6))

        self.conn_label = tk.Label(conn_frame, text="API: 未连接", font=("Microsoft YaHei", 9),
                                    bg=self.card_bg, fg=self.dim_text)
        self.conn_label.pack(side="left", padx=16, pady=6)

        self.refresh_token_btn = tk.Button(conn_frame, text="刷新Token", font=("Microsoft YaHei", 9),
                                             bg=self.accent, fg=self.dim_text, activebackground=self.accent,
                                             relief="flat", cursor="hand2", padx=8,
                                             command=self.refresh_token)
        self.refresh_token_btn.pack(side="right", padx=16, pady=6)

        msg_frame = tk.Frame(self.root, bg=self.card_bg, bd=0)
        msg_frame.pack(fill="both", expand=True, padx=12, pady=6)

        msg_header = tk.Frame(msg_frame, bg=self.card_bg)
        msg_header.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(msg_header, text="最新消息预览", font=("Microsoft YaHei", 11, "bold"),
                  bg=self.card_bg, fg=self.text_color).pack(side="left")

        self.new_badge = tk.Label(msg_header, text="", font=("Microsoft YaHei", 9, "bold"),
                                    bg=self.card_bg, fg=self.orange)
        self.new_badge.pack(side="right")

        self.msg_text = tk.Text(msg_frame, height=4, font=("Microsoft YaHei", 12),
                                  bg="#0d1b2a", fg=self.text_color, insertbackground=self.text_color,
                                  relief="flat", wrap="word", padx=12, pady=10)
        self.msg_text.pack(fill="x", padx=16, pady=(8, 8))
        self.msg_text.insert("1.0", "暂无消息")
        self.msg_text.config(state="disabled")

        send_row = tk.Frame(msg_frame, bg=self.card_bg)
        send_row.pack(fill="x", padx=16, pady=(0, 12))

        self.send_progress = tk.Label(send_row, text="", font=("Microsoft YaHei", 9),
                                        bg=self.card_bg, fg=self.orange)
        self.send_progress.pack(side="left")

        self.send_btn = tk.Button(send_row, text="发送到 TeleClaw", font=("Microsoft YaHei", 10),
                                    bg=self.accent, fg=self.text_color, activebackground="#1a4a7a",
                                    relief="flat", cursor="hand2", padx=14, pady=3,
                                    command=self.send_message)
        self.send_btn.pack(side="right")

        resp_frame = tk.Frame(self.root, bg=self.card_bg, bd=0)
        resp_frame.pack(fill="both", expand=True, padx=12, pady=6)

        resp_header = tk.Frame(resp_frame, bg=self.card_bg)
        resp_header.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(resp_header, text="AI 回复", font=("Microsoft YaHei", 11, "bold"),
                  bg=self.card_bg, fg=self.text_color).pack(side="left")

        self.resp_status = tk.Label(resp_header, text="", font=("Microsoft YaHei", 9),
                                      bg=self.card_bg, fg=self.dim_text)
        self.resp_status.pack(side="right")

        self.resp_text = tk.Text(resp_frame, height=5, font=("Microsoft YaHei", 11),
                                   bg="#0d1b2a", fg="#b8e6c8", insertbackground=self.text_color,
                                   relief="flat", wrap="word", padx=12, pady=10)
        self.resp_text.pack(fill="both", expand=True, padx=16, pady=(8, 12))
        self.resp_text.insert("1.0", "等待发送...")
        self.resp_text.config(state="disabled")

        log_frame = tk.Frame(self.root, bg=self.card_bg, bd=0)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        log_header = tk.Frame(log_frame, bg=self.card_bg)
        log_header.pack(fill="x", padx=16, pady=(10, 0))

        tk.Label(log_header, text="运行日志", font=("Microsoft YaHei", 11, "bold"),
                  bg=self.card_bg, fg=self.text_color).pack(side="left")

        tk.Button(log_header, text="清空", font=("Microsoft YaHei", 9),
                  bg=self.accent, fg=self.dim_text, activebackground=self.accent,
                  relief="flat", cursor="hand2", padx=8,
                  command=self.clear_log).pack(side="right")

        self.log_area = scrolledtext.ScrolledText(log_frame, height=8, font=("Consolas", 9),
                                                     bg="#0d1b2a", fg=self.dim_text,
                                                     insertbackground=self.text_color,
                                                     relief="flat", wrap="word",
                                                     padx=10, pady=8)
        self.log_area.pack(fill="both", expand=True, padx=16, pady=(8, 12))
        self.log_area.config(state="disabled")

    def _load_state_to_ui(self):
        state = load_state()
        msg = state.get("last_message", "")
        if msg:
            self.last_message = msg
            self.msg_text.config(state="normal")
            self.msg_text.delete("1.0", "end")
            self.msg_text.insert("1.0", msg)
            self.msg_text.config(state="disabled")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_area.config(state="normal")
        self.log_area.insert("end", line)
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def clear_log(self):
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.config(state="disabled")

    def set_status(self, status, color):
        self.status_dot.itemconfig(self.dot_id, fill=color)
        self.status_label.config(text=status)

    def set_message_preview(self, msg, is_new=False):
        self.last_message = msg
        self.msg_text.config(state="normal")
        self.msg_text.delete("1.0", "end")
        self.msg_text.insert("1.0", msg if msg else "暂无消息")
        self.msg_text.config(state="disabled")
        if is_new:
            self.new_badge.config(text="NEW")
            self.root.after(10000, lambda: self.new_badge.config(text=""))
        else:
            self.new_badge.config(text="")

    def save_current_config(self):
        self.config["interval"] = self.interval_var.get()
        self.config["auto_send"] = self.auto_send_var.get()
        save_config(self.config)

    def refresh_token(self):
        self.log("正在刷新Token...")
        token = get_moben_token(force_refresh=True)
        if token:
            self._token_ok = True
            self.conn_label.config(text="API: 已连接", fg=self.green)
            self.log("Token刷新成功")
        else:
            # CDP失败，尝试手机验证码登录
            phone = tk.simpledialog.askstring("手机号",
                "CDP方式刷新Token失败。\n请输入墨本AI绑定的手机号进行验证码登录：",
                parent=self.root)
            if phone:
                self.log(f"正在发送验证码到 {phone}...")
                token, err = _login_via_sms(phone)
                if token:
                    _save_token(token)
                    self._token_ok = True
                    self.conn_label.config(text="API: 已连接", fg=self.green)
                    self.log("手机验证码登录成功")
                else:
                    self._token_ok = False
                    self.conn_label.config(text="API: 登录失败", fg=self.highlight)
                    self.log(f"登录失败: {err}")
            else:
                self._token_ok = False
                self.conn_label.config(text="API: Token获取失败", fg=self.highlight)
                self.log("Token刷新取消")

    def toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        token = get_moben_token()
        if not token:
            # Token不可用，提供手机验证码登录选项
            answer = messagebox.askyesnocancel(
                "Token不可用",
                "无法获取墨本AI token。\n\n"
                "选择登录方式：\n"
                "· 是 → 手机验证码登录（无需Edge）\n"
                "· 否 → 通过Edge浏览器CDP获取\n"
                "· 取消 → 放弃启动"
            )
            if answer is True:
                # 手机验证码登录
                phone = tk.simpledialog.askstring("手机号", "请输入墨本AI绑定的手机号：",
                                                   parent=self.root)
                if phone:
                    self.log(f"正在发送验证码到 {phone}...")
                    token, err = _login_via_sms(phone)
                    if token:
                        _save_token(token)
                        self.log("手机验证码登录成功")
                    else:
                        messagebox.showerror("登录失败", err or "未知错误")
                        self.log(f"登录失败: {err}")
                        return
                else:
                    return
            elif answer is False:
                # CDP方式
                token = get_moben_token(force_refresh=True)
                if not token:
                    messagebox.showwarning("CDP获取失败",
                        "无法通过Edge获取Token。\n请确保Edge已打开moben.cn且已登录。")
                    self.log("启动失败：Token不可用")
                    return
            else:
                return

        self._token_ok = True
        self.conn_label.config(text="API: 已连接", fg=self.green)
        self.save_current_config()
        self.monitoring = True
        self.set_status("监控中", "#00d672")
        self.start_btn.config(text="停止监控", bg="#c73e54")
        self.check_btn.config(state="disabled")
        self.log("监控已启动（API模式，无需Edge浏览器保持打开）")

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.monitoring = False
        self.set_status("已停止", "#ff9f43")
        self.start_btn.config(text="启动监控", bg="#e94560")
        self.check_btn.config(state="normal")
        self.log("监控已停止")

    def _monitor_loop(self):
        while self.monitoring:
            try:
                interval = max(self.interval_var.get(), 10)
            except Exception:
                interval = 30

            self.root.after(0, self._do_check_ui)

            wait_end = time.time() + interval
            while self.monitoring and time.time() < wait_end:
                remaining = int(wait_end - time.time())
                m, s = divmod(remaining, 60)
                self.root.after(0, lambda m=m, s=s: self.time_label.config(
                    text=f"下次检查: {m}:{s:02d}"))
                time.sleep(1)

        self.root.after(0, lambda: self.time_label.config(text=""))

    def _do_check_ui(self):
        def run():
            has_new, msg, error = do_check()
            self.root.after(0, lambda: self._on_check_result(has_new, msg, error))
        threading.Thread(target=run, daemon=True).start()

    def _on_check_result(self, has_new, msg, error):
        if error:
            self.log(f"检查出错: {error}")
            if "token" in error.lower() or "无法获取" in error:
                self._token_ok = False
                self.conn_label.config(text="API: Token失效", fg=self.highlight)
                self.set_status("Token失效", self.highlight)
            else:
                self.set_status("检查出错", self.highlight)
        elif has_new:
            self.log(f"发现新消息: {msg}")
            self.set_message_preview(msg, is_new=True)
            self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
            if self.auto_send_var.get():
                busy, detail = is_teleclaw_busy()
                if busy:
                    self.log(f"TeleClaw 正忙({detail})，跳过此消息")
                    self.set_status("TeleClaw正忙", "#ff9f43")
                else:
                    self.log("自动发送中...")
                    self._do_send(msg)
            else:
                self.set_status("监控中", "#00d672")

    def manual_check(self):
        self.log("手动检查...")
        self.set_status("检查中...", "#ffdd57")

        def run():
            has_new, msg, error = do_check()
            self.root.after(0, lambda: self._on_manual_result(has_new, msg, error))
        threading.Thread(target=run, daemon=True).start()

    def _on_manual_result(self, has_new, msg, error):
        if error:
            self.log(f"检查出错: {error}")
            self.set_status("未启动", "#8899aa")
        elif has_new:
            self.log(f"发现新消息: {msg}")
            self.set_message_preview(msg, is_new=True)
            self.history.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg})
        else:
            self.log("没有新消息")
        if not self.monitoring:
            self.set_status("未启动", "#8899aa")

    def init_baseline(self):
        self.log("正在初始化基线...")

        def run():
            has_new, msg, error = do_check()
            if not error:
                state = load_state()
                self.log(f"基线已初始化, 最新消息: {state.get('last_message', '无')[:50]}")
                if state.get("last_message"):
                    self.set_message_preview(state["last_message"])
            else:
                self.log(f"初始化失败: {error}")
            if not self.monitoring:
                self.root.after(0, lambda: self.set_status("未启动", "#8899aa"))
        threading.Thread(target=run, daemon=True).start()

    def send_message(self):
        msg = self.last_message
        if not msg or msg == "暂无消息":
            messagebox.showinfo("提示", "没有可发送的消息")
            return
        busy, detail = is_teleclaw_busy()
        if busy:
            messagebox.showwarning("TeleClaw 正忙",
                f"TeleClaw 正在处理任务({detail})，请稍后再试。")
            return
        self.log(f"手动发送到TeleClaw: {msg[:50]}...")
        self._do_send(msg)

    def _do_send(self, msg):
        self.send_btn.config(state="disabled")
        self.send_progress.config(text="发送中...")
        self.resp_status.config(text="等待AI回复...", fg=self.orange)
        self.resp_text.config(state="normal")
        self.resp_text.delete("1.0", "end")
        self.resp_text.insert("1.0", "等待AI回复中...\n(最长可能需要 120 秒)")
        self.resp_text.config(state="disabled")
        self.set_status("发送中...", "#ffdd57")

        self._animate_progress = True
        self._animate_dots = 0

        def animate():
            if not self._animate_progress:
                return
            self._animate_dots = (self._animate_dots + 1) % 4
            self.send_progress.config(text="发送中" + "." * self._animate_dots)
            self.root.after(500, animate)
        animate()

        def run():
            success, response = send_to_teleclaw(msg)
            self._animate_progress = False
            self.root.after(0, lambda: self._on_send_result(success, response))
        threading.Thread(target=run, daemon=True).start()

    def _on_send_result(self, success, response):
        self.send_btn.config(state="normal")
        self.send_progress.config(text="")

        if success:
            self.log(f"发送成功，AI 已回复 ({len(response)} 字)")
            self.resp_status.config(text="回复完成", fg="#00d672")
            self.set_status("监控中" if self.monitoring else "未启动",
                            "#00d672" if self.monitoring else "#8899aa")
        else:
            self.log(f"发送失败: {response}")
            self.resp_status.config(text="发送失败", fg="#e94560")
            self.set_status("监控中" if self.monitoring else "未启动",
                            "#00d672" if self.monitoring else "#8899aa")

        self.resp_text.config(state="normal")
        self.resp_text.delete("1.0", "end")
        display = response if response else "(无回复内容)"
        self.resp_text.insert("1.0", display)
        self.resp_text.config(state="disabled")

    def on_close(self):
        self.monitoring = False
        self.save_current_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = MobenMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
