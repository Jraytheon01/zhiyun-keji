# -*- coding: utf-8 -*-
"""Small client example for recorder App integration."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET", payload=None, token: str = ""):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["X-Bridge-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接桥接服务: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="发送录音完成事件")
    parser.add_argument("--url", default="http://127.0.0.1:18766")
    parser.add_argument("--token", default="")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--recording-id", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--audience", default="项目团队和管理层")
    parser.add_argument("--style", default="商务简约")
    parser.add_argument("--slides", type=int, default=7)
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    payload = {
        "event_id": args.event_id,
        "recording_id": args.recording_id,
        "meeting_title": args.title,
        "use_latest": args.latest or not (args.recording_id or args.title),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "audience": args.audience,
        "style": args.style,
        "slides": args.slides,
        "source": "moben-recorder-app-example",
    }
    _, result = request_json(
        f"{args.url.rstrip('/')}/events/recording-completed",
        method="POST",
        payload=payload,
        token=args.token,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.wait:
        return
    event_id = result["event_id"]
    while True:
        time.sleep(3)
        _, job = request_json(
            f"{args.url.rstrip('/')}/jobs/{event_id}", token=args.token
        )
        print(f"state={job['state']}")
        if job["state"] in {"completed", "failed"}:
            print(json.dumps(job, ensure_ascii=False, indent=2))
            return


if __name__ == "__main__":
    main()
