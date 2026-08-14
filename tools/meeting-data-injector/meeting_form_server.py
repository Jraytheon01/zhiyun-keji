#!/usr/bin/env python3
"""Local form for inserting demo meetings into the MySQL source tables."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from inject_meeting import insert_meeting, meeting_from_text


ROOT = Path(__file__).resolve().parent
HTML = ROOT / "meeting_form.html"


class Handler(BaseHTTPRequestHandler):
    server_version = "TobyMeetingForm/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/", "/meeting_form.html"}:
            body = HTML.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "ok"})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path not in {"/api/meetings", "/api/meetings/from-text"}:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2_000_000:
                raise ValueError("请求体长度必须在 1 到 2000000 字节之间")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            replace = bool(payload.pop("replace", False))
            if path == "/api/meetings/from-text":
                payload = meeting_from_text(payload)
            result = insert_meeting(payload, replace=replace)
            result["summary"] = payload["summary"]
            result["segments"] = payload["segments"]
            self.send_json(HTTPStatus.CREATED, result)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Toby demo meeting injection form")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18880)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Meeting form: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
