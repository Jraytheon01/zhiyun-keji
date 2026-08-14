#!/usr/bin/env python3
"""Insert one demo course into the isolated Zhiyun Learning MySQL database."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SPEAKER_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?([\u4e00-\u9fffA-Za-z0-9_.·（）() -]{1,24})[：:]\s*(.+?)\s*$"
)
NON_SPEAKER_LABELS = {
    "会议主题", "主题", "背景", "目标", "摘要", "纪要", "核心内容", "核心讨论",
    "决策", "决定", "结论", "行动项", "待办", "风险", "问题", "时间", "地点",
}


def _sentences(text: str) -> list[str]:
    return [part.strip(" \t-*•") for part in re.split(r"(?<=[。！？!?；;])\s*|\n+", text) if part.strip(" \t-*•")]


def _split_long_text(text: str, limit: int = 260) -> list[str]:
    sentences = _sentences(text)
    if not sentences:
        return []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        chunks.append(current)
    return chunks


def parse_unstructured_transcript(raw_text: str) -> list[dict[str, Any]]:
    """Turn pasted prose into ordered rows named speaker 1, speaker 2, etc."""
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw_text:
        raise ValueError("原始会议文本不能为空")

    parsed: list[tuple[str, str]] = []
    speaker_numbers: dict[str, str] = {}
    current_speaker = "说话人1"
    for block in [part.strip() for part in re.split(r"\n+", raw_text) if part.strip()]:
        match = SPEAKER_RE.match(block)
        if match and match.group(1).strip() not in NON_SPEAKER_LABELS:
            source_speaker, content = match.group(1).strip(), match.group(2).strip()
            if source_speaker.startswith("说话人") and source_speaker[3:].isdigit():
                speaker = source_speaker
            else:
                speaker = speaker_numbers.setdefault(
                    source_speaker, f"说话人{len(speaker_numbers) + 1}"
                )
            current_speaker = speaker
        else:
            speaker, content = current_speaker, block
        for chunk in _split_long_text(content):
            if parsed and parsed[-1][0] == speaker and len(parsed[-1][1]) + len(chunk) <= 260:
                parsed[-1] = (speaker, parsed[-1][1] + chunk)
            else:
                parsed.append((speaker, chunk))

    segments: list[dict[str, Any]] = []
    cursor = 0
    for index, (speaker, content) in enumerate(parsed, start=1):
        duration = max(6_000, min(60_000, round(len(content) / 4 * 1000)))
        segments.append({
            "begin_time": cursor,
            "end_time": cursor + duration,
            "speaker": speaker,
            "content": content,
            "code": str(index),
        })
        cursor += duration + 500
    return segments


def meeting_from_text(payload: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(payload.get("raw_text") or "").strip()
    now = datetime.now()
    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    if not title:
        raise ValueError("录音标题不能为空")
    if not summary:
        raise ValueError("内容摘要不能为空，请使用 AI 生成后粘贴")
    if not raw_text:
        raise ValueError("录音逐字稿不能为空")
    meeting_id = payload.get("meeting_id") or int(time.time() * 1000)
    return {
        "meeting_id": meeting_id,
        "user_id": payload.get("user_id") or 1001,
        "phone": str(payload.get("phone") or "13800001001").strip(),
        "title": title,
        "create_time": str(payload.get("create_time") or now.strftime("%Y-%m-%d %H:%M:%S")),
        "summary": summary,
        "segments": parse_unstructured_transcript(raw_text),
    }


def utf8_sql(value: Any) -> str:
    if value is None or value == "":
        return "NULL"
    encoded = str(value).encode("utf-8").hex()
    return f"CONVERT(0x{encoded} USING utf8mb4)"


def integer(value: Any, name: str, minimum: int = 0) -> int:
    result = int(value)
    if result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def container_environment(container: str) -> dict[str, str]:
    completed = subprocess.run(
        ["docker", "inspect", container],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    inspected = json.loads(completed.stdout)[0]
    pairs = {}
    for entry in inspected["Config"].get("Env", []):
        key, _, value = entry.partition("=")
        pairs[key] = value
    return pairs


def build_sql(meeting: dict[str, Any], replace: bool) -> tuple[str, int]:
    meeting_id = integer(meeting["meeting_id"], "meeting_id", 1)
    user_id = integer(meeting["user_id"], "user_id", 1)
    phone = str(meeting["phone"]).strip()
    title = str(meeting["title"]).strip()
    summary = str(meeting["summary"]).strip()
    segments = meeting.get("segments") or []
    if not phone or not title or not summary or not segments:
        raise ValueError("phone, title, summary and at least one transcript segment are required")

    create_time = str(meeting.get("create_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
    transcript = "\n".join(
        f"{str(row.get('speaker') or '未知说话人').strip()}：{str(row['content']).strip()}"
        for row in segments
    )
    duration = max(integer(row.get("end_time", 0), "end_time") for row in segments)

    statements = ["SET NAMES utf8mb4;", "START TRANSACTION;"]
    if replace:
        statements.extend([
            f"DELETE FROM user_meeting_content WHERE meet_id={meeting_id};",
            f"DELETE FROM user_meeting_info WHERE id={meeting_id};",
        ])
    statements.append(
        "INSERT INTO user_meeting_info "
        "(id,meeting_name,user_id,phone,create_time,update_time,during,title,content,"
        "abstract_text,abstract_content,status,del_flag,rebuild_status) VALUES ("
        f"{meeting_id},{utf8_sql(title)},{user_id},{utf8_sql(phone)},{utf8_sql(create_time)},"
        f"{utf8_sql(create_time)},{duration},{utf8_sql(title)},{utf8_sql(transcript)},"
        f"{utf8_sql(summary)},{utf8_sql(summary)},'2','0','0');"
    )
    for index, row in enumerate(segments, start=1):
        begin = integer(row.get("begin_time", 0), "begin_time")
        end = integer(row.get("end_time", begin), "end_time")
        if end < begin:
            raise ValueError(f"segment {index}: end_time must be >= begin_time")
        speaker = str(row.get("speaker") or "未知说话人").strip()
        content = str(row["content"]).strip()
        if not content:
            raise ValueError(f"segment {index}: content is required")
        code = str(row.get("code") or index)[:2]
        statements.append(
            "INSERT INTO user_meeting_content "
            "(begin_time,end_time,speaker,content,meet_id,create_time,code,type) VALUES ("
            f"{begin},{end},{utf8_sql(speaker)},{utf8_sql(content)},{meeting_id},"
            f"{utf8_sql(create_time)},{utf8_sql(code)},'1');"
        )
    statements.append("COMMIT;")
    return "\n".join(statements), meeting_id


def insert_meeting(
    meeting: dict[str, Any],
    replace: bool = False,
    container: str = "meeting-assistant-mysql-1",
    database: str = "",
) -> dict[str, Any]:
    sql, meeting_id = build_sql(meeting, replace)
    container_env = container_environment(container)
    password = container_env.get("MYSQL_ROOT_PASSWORD", "")
    database = database or "zhiyun_learning"
    if not password:
        raise RuntimeError("MYSQL_ROOT_PASSWORD is not configured in the MySQL container")

    command = [
        "docker", "exec", "-i", "-e", f"MYSQL_PWD={password}", container,
        "mysql", "--default-character-set=utf8mb4", "-uroot", database,
    ]
    completed = subprocess.run(
        command,
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=os.environ.copy(),
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "MySQL insert failed")
    return {
        "inserted": True,
        "meeting_id": str(meeting_id),
        "user_id": int(meeting["user_id"]),
        "phone": str(meeting["phone"]),
        "title": meeting["title"],
        "segment_count": len(meeting["segments"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert a demo transcript and summary into MySQL")
    parser.add_argument("input", type=Path, help="meeting JSON file")
    parser.add_argument("--container", default="meeting-assistant-mysql-1")
    parser.add_argument("--database", default="")
    parser.add_argument("--replace", action="store_true", help="replace the same meeting_id")
    args = parser.parse_args()

    meeting = json.loads(args.input.read_text(encoding="utf-8-sig"))
    result = insert_meeting(
        meeting,
        replace=args.replace,
        container=args.container,
        database=args.database,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
