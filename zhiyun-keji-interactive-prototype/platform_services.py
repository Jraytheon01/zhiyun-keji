from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from platform_store import PlatformStore


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def format_duration(milliseconds: int | None) -> str:
    total = max(0, int(milliseconds or 0)) // 1000
    minutes, seconds = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分钟"
    return f"{minutes} 分钟" if not seconds else f"{minutes}:{seconds:02d}"


def format_clock(milliseconds: int | None) -> str:
    total = max(0, int(milliseconds or 0)) // 1000
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


class MySQLUnavailable(RuntimeError):
    pass


class CourseRepository:
    def __init__(self, store: PlatformStore):
        self.store = store
        self.host = os.environ.get("MYSQL_HOST", "").strip()
        self.port = int(os.environ.get("MYSQL_PORT", "3306"))
        if os.name == "nt" and self.host == "mysql":
            self.host = "127.0.0.1"
            if self.port == 3306:
                self.port = 3307
        self.user = os.environ.get("MYSQL_USER", "").strip()
        self.password = os.environ.get("MYSQL_PASSWORD", "")
        self.database = os.environ.get("MYSQL_DATABASE", "").strip()
        self.show_non_education = parse_bool(os.environ.get("SHOW_NON_EDUCATION_RECORDS"), False)

    @staticmethod
    def _looks_educational(item: dict[str, Any]) -> bool:
        text = f"{item.get('title', '')} {item.get('summary', '')[:240]}"
        excluded = ("项目会", "复盘会", "确认会", "展会", "竞品", "会议纪要", "架构选型", "进度同步", "资源协调")
        if any(word in text for word in excluded):
            return False
        education = (
            "课程", "课堂", "上课", "补习", "辅导", "学习", "复习", "练习", "例题",
            "数学", "物理", "化学", "语文", "英语", "函数", "方程", "几何", "定律",
            "平移", "坐标", "电磁感应", "初一", "初二", "初三", "高一", "高二", "高三",
        )
        return any(word in text for word in education)

    @staticmethod
    def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(row.get("data_json") or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _infer_subject(text: str) -> str:
        value = str(text or "")
        if any(word in value for word in ("物理", "力学", "电磁", "电路", "楞次", "牛顿", "万有引力", "航天")):
            return "物理"
        if any(word in value for word in ("化学", "元素", "反应", "方程式")):
            return "化学"
        if any(word in value for word in ("英语", "English", "语法")):
            return "英语"
        if any(word in value for word in ("语文", "古诗", "文言文")):
            return "语文"
        if any(word in value for word in ("数学", "函数", "方程", "几何", "坐标")):
            return "数学"
        return ""

    @property
    def mysql_configured(self) -> bool:
        return bool(self.host and self.user and self.database)

    def connect(self):
        if not self.mysql_configured:
            raise MySQLUnavailable("MySQL is not configured")
        try:
            import pymysql
        except ImportError as exc:
            raise MySQLUnavailable("pymysql is not installed") from exc
        try:
            return pymysql.connect(
                host=self.host, port=self.port, user=self.user, password=self.password,
                database=self.database, charset="utf8mb4", autocommit=False,
                cursorclass=pymysql.cursors.DictCursor, connect_timeout=4,
            )
        except Exception as exc:
            raise MySQLUnavailable(str(exc)) from exc

    def _mysql_learners(self) -> list[dict[str, Any]]:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'edu_learner'")
            if cursor.fetchone():
                try:
                    cursor.execute(
                        """SELECT CAST(learner_id AS CHAR) learner_id, learner_id user_id,
                                  phone, display_name, COALESCE(grade,'') grade
                           FROM edu_learner ORDER BY learner_id"""
                    )
                    rows = cursor.fetchall()
                    return [{**row, "subject": "数学", "source": "mysql"} for row in rows]
                except Exception:
                    connection.rollback()
            cursor.execute(
                """SELECT CONCAT(CAST(MIN(COALESCE(user_id,id)) AS CHAR),'-',RIGHT(phone,4)) learner_id,
                          MIN(COALESCE(user_id,id)) user_id, phone,
                          CONCAT('学习者 ', MIN(COALESCE(user_id,id))) display_name,
                          '' grade, COUNT(*) course_count
                   FROM user_meeting_info
                   WHERE phone IS NOT NULL AND phone<>'' AND (del_flag='0' OR del_flag IS NULL)
                   GROUP BY phone ORDER BY MIN(COALESCE(user_id,id))"""
            )
            return [{**row, "subject": "", "source": "mysql"} for row in cursor.fetchall()]

    def learners(self) -> list[dict[str, Any]]:
        local = self.store.local_learners()
        rows: list[dict[str, Any]] = []
        if self.mysql_configured:
            rows = self._mysql_learners()
        mysql_phones = {str(item.get("phone") or "") for item in rows if item.get("phone")}
        merged: dict[str, dict[str, Any]] = {
            str(item["learner_id"]): {**item, "source": "local"}
            for item in local if not item.get("phone") or str(item.get("phone")) not in mysql_phones
        }
        for item in rows:
            learner_id = str(item["learner_id"])
            local_match = next((candidate for candidate in local if candidate.get("phone") and candidate.get("phone") == item.get("phone")), None)
            if not local_match:
                local_match = merged.get(learner_id)
            if local_match:
                # Keep the no-login platform identity stable after this learner's
                # first course appears in MySQL. The legacy source query derives a
                # composite id, which must not replace the local learner id.
                item["learner_id"] = str(local_match["learner_id"])
                item["display_name"] = local_match.get("display_name") or item.get("display_name")
                item["grade"] = local_match.get("grade") or item.get("grade")
                item["subject"] = local_match.get("subject") or item.get("subject")
                learner_id = str(item["learner_id"])
            merged[learner_id] = item
        return list(merged.values())

    def learner(self, learner_id: str) -> dict[str, Any]:
        for item in self.learners():
            if str(item["learner_id"]) == str(learner_id):
                return item
        raise KeyError("学习者不存在")

    def learner_by_phone(self, phone: str) -> dict[str, Any] | None:
        return next((item for item in self.learners() if item.get("phone") == phone), None)

    def _mysql_courses(self, learner: dict[str, Any]) -> list[dict[str, Any]]:
        phone = learner.get("phone", "")
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, meeting_name, title, create_time, during, abstract_content,
                          abstract_text, record_url, file_type, device_id, data_json, status, rebuild_status,
                          EXISTS(SELECT 1 FROM user_meeting_content c WHERE c.meet_id=m.id
                                 AND c.content IS NOT NULL AND c.content<>'') has_transcript
                   FROM user_meeting_info m
                   WHERE phone=%s AND status='2' AND (del_flag='0' OR del_flag IS NULL)
                   ORDER BY create_time IS NULL, create_time DESC""",
                (phone,),
            )
            rows = cursor.fetchall()
            job_status: dict[str, str] = {}
            try:
                cursor.execute(
                    """SELECT recording_id,status FROM ingest_jobs WHERE phone=%s
                       ORDER BY updated_at DESC""", (phone,)
                )
                for job in cursor.fetchall():
                    job_status.setdefault(str(job["recording_id"]), job["status"])
            except Exception:
                connection.rollback()
        result = []
        for row in rows:
            metadata = self._row_metadata(row)
            title = row.get("title") or row.get("meeting_name") or f"课程 {row['id']}"
            course_id = str(row["id"])
            ingest = job_status.get(course_id, "done" if row.get("has_transcript") else "pending")
            content_ready = bool(
                row.get("has_transcript")
                and (row.get("abstract_content") or row.get("abstract_text"))
            )
            result.append({
                "course_id": course_id,
                "learner_id": str(learner["learner_id"]),
                "title": title,
                "create_time": row["create_time"].strftime("%Y-%m-%d %H:%M:%S") if row.get("create_time") else "",
                "duration_ms": int(row.get("during") or 0),
                "duration_text": format_duration(row.get("during")),
                "summary": row.get("abstract_content") or row.get("abstract_text") or "",
                "subject": metadata.get("subject") or self._infer_subject(f"{title} {row.get('abstract_content') or row.get('abstract_text') or ''}") or learner.get("subject") or "课程",
                "grade": metadata.get("grade") or learner.get("grade") or "",
                "scene": metadata.get("scene") or "课堂记录",
                "source_type": metadata.get("source_type") or row.get("device_id") or row.get("file_type") or "course_text",
                # 展示层以真实可用内容为准。即使一次向量重建任务失败，只要
                # 逐字稿与摘要已存在，课程复盘和 TeleAgent 读取仍然可用。
                "status": "ready" if content_ready or ingest in {"done", "succeeded", "processed"} else ingest,
                "has_transcript": bool(row.get("has_transcript")),
                "has_summary": bool(row.get("abstract_content") or row.get("abstract_text")),
                "has_audio": bool(row.get("record_url")),
                "source": "mysql",
            })
        return result

    @staticmethod
    def _map_local(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["duration_text"] = format_duration(row.get("duration_ms"))
        result["has_transcript"] = True
        result["has_summary"] = bool(row.get("summary"))
        result["has_audio"] = False
        result["source"] = "local"
        return result

    def courses(self, learner_id: str) -> list[dict[str, Any]]:
        learner = self.learner(learner_id)
        if self.mysql_configured and learner.get("phone"):
            result = self._mysql_courses(learner)
        else:
            result = [self._map_local(row) for row in self.store.local_courses(learner_id)]
        if not self.show_non_education:
            result = [item for item in result if self._looks_educational(item)]
        return sorted(result, key=lambda item: item.get("create_time") or "", reverse=True)

    def _mysql_detail(self, learner: dict[str, Any], course_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        phone = learner.get("phone", "")
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT id,meeting_name,title,create_time,during,abstract_content,abstract_text,
                          record_url,file_type,device_id,data_json,status,rebuild_status
                   FROM user_meeting_info WHERE id=%s AND phone=%s
                   AND status='2' AND (del_flag='0' OR del_flag IS NULL)""",
                (course_id, phone),
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError("课程不存在")
            cursor.execute(
                """SELECT id segment_id,begin_time begin_ms,end_time end_ms,speaker,content
                   FROM user_meeting_content WHERE meet_id=%s
                   ORDER BY begin_time IS NULL,begin_time,id""", (course_id,)
            )
            segments = cursor.fetchall()
        metadata = self._row_metadata(row)
        title = row.get("title") or row.get("meeting_name") or f"课程 {course_id}"
        course = {
            "course_id": str(row["id"]), "learner_id": str(learner["learner_id"]),
            "title": title,
            "create_time": row["create_time"].strftime("%Y-%m-%d %H:%M:%S") if row.get("create_time") else "",
            "duration_ms": int(row.get("during") or 0), "duration_text": format_duration(row.get("during")),
            "summary": row.get("abstract_content") or row.get("abstract_text") or "",
            "subject": metadata.get("subject") or self._infer_subject(f"{title} {row.get('abstract_content') or row.get('abstract_text') or ''}") or learner.get("subject") or "课程",
            "grade": metadata.get("grade") or learner.get("grade") or "",
            "scene": metadata.get("scene") or "课堂记录",
            "source_type": metadata.get("source_type") or row.get("device_id") or row.get("file_type") or "course_text",
            "status": "ready", "has_transcript": bool(segments), "has_summary": bool(row.get("abstract_content") or row.get("abstract_text")),
            "has_audio": bool(row.get("record_url")), "audio_url": row.get("record_url") or "", "source": "mysql",
        }
        return course, self._map_segments(segments)

    @staticmethod
    def _map_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            item = dict(row)
            item["begin_ms"] = int(item.get("begin_ms") or 0)
            item["end_ms"] = int(item.get("end_ms") or item["begin_ms"])
            item["time_text"] = format_clock(item["begin_ms"])
            item["speaker"] = item.get("speaker") or "说话人"
            item["content"] = item.get("content") or ""
            result.append(item)
        return result

    def detail(self, learner_id: str, course_id: str) -> dict[str, Any]:
        learner = self.learner(learner_id)
        if self.mysql_configured and learner.get("phone"):
            course, segments = self._mysql_detail(learner, course_id)
            course["segments"] = segments
            course["review"] = self.store.get_review(learner_id, course_id)
            return course
        local = self.store.local_course(learner_id, course_id)
        if not local:
            raise KeyError("课程不存在")
        course = self._map_local(local)
        course["segments"] = self._map_segments(self.store.local_segments(course_id))
        course["review"] = self.store.get_review(learner_id, course_id)
        return course

    @staticmethod
    def _segments_from_text(text: str) -> list[dict[str, Any]]:
        blocks = [line.strip() for line in re.split(r"\n+", text) if line.strip()]
        segments = []
        cursor = 0
        for index, block in enumerate(blocks):
            match = re.match(r"^([^：:]{1,20})[：:]\s*(.+)$", block)
            speaker, content = (match.group(1), match.group(2)) if match else ("说话人", block)
            duration = max(6000, min(60000, len(content) * 280))
            segments.append({"begin_ms": cursor, "end_ms": cursor + duration, "speaker": speaker, "content": content})
            cursor += duration + 500
        return segments

    @staticmethod
    def demo_audio_payload(file_name: str) -> dict[str, Any]:
        """Infer only the generation variables from a selected file name."""
        base = re.sub(r"\.(mp3|wav|m4a|aac|flac|mp4|mov)$", "", str(file_name), flags=re.I)
        base = re.sub(r"[_]+", " ", base).strip(" -—_")
        base = re.sub(r"\b20\d{2}[-.]?\d{1,2}[-.]?\d{1,2}\b", "", base).strip(" -—_")
        title = base or "课堂学习记录"
        subject = "数学"
        if any(word in title for word in ("物理", "力学", "电磁", "电路", "楞次", "牛顿")):
            subject = "物理"
        elif any(word in title for word in ("英语", "English", "阅读", "语法")):
            subject = "英语"
        elif any(word in title for word in ("语文", "古诗", "文言文", "阅读理解")):
            subject = "语文"

        return {
            "title": title,
            "subject": subject,
            "source_type": "audio_transcript",
            "source_file_name": str(file_name)[:240],
        }

    def import_demo_audio(self, learner_id: str, file_name: str) -> dict[str, Any]:
        if not str(file_name).strip():
            raise ValueError("请选择音频文件")
        payload = self.demo_audio_payload(file_name)
        return self.import_course(learner_id, payload)

    def import_course(self, learner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        learner = self.learner(learner_id)
        transcript = str(payload.get("transcript") or "").strip()
        segments = payload.get("segments") or self._segments_from_text(transcript)
        normalized = {**payload, "segments": segments, "grade": payload.get("grade") or learner.get("grade", "")}
        if self.mysql_configured and learner.get("phone"):
            return self._insert_mysql(learner, normalized)
        raise MySQLUnavailable("共享课程库未配置，课程未保存")

    def delete_course(self, learner_id: str, course_id: str) -> dict[str, Any]:
        learner = self.learner(learner_id)
        course = self.detail(learner_id, course_id)
        if self.mysql_configured and learner.get("phone"):
            with self.connect() as connection, connection.cursor() as cursor:
                try:
                    for table in ("facts", "todos", "chunks"):
                        cursor.execute(
                            f"DELETE FROM {table} WHERE recording_id=%s AND phone=%s",
                            (course_id, learner["phone"]),
                        )
                    cursor.execute(
                        "DELETE FROM recordings WHERE recording_id=%s AND phone=%s",
                        (course_id, learner["phone"]),
                    )
                    cursor.execute(
                        """DELETE content FROM user_meeting_content content
                           INNER JOIN user_meeting_info info ON info.id=content.meet_id
                           WHERE info.id=%s AND info.phone=%s""",
                        (course_id, learner["phone"]),
                    )
                    cursor.execute(
                        "DELETE FROM ingest_jobs WHERE recording_id=%s AND phone=%s",
                        (course_id, learner["phone"]),
                    )
                    cursor.execute(
                        """DELETE FROM user_meeting_info WHERE id=%s AND phone=%s
                           AND status='2' AND (del_flag='0' OR del_flag IS NULL)""",
                        (course_id, learner["phone"]),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError("课程不存在或不可删除")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            self._notify_ingest(learner["phone"], course_id, operation="delete")
        else:
            local = self.store.local_course(learner_id, course_id)
            if not local:
                raise KeyError("课程不存在或不可删除")
        vector_ids = self.store.delete_course_data(learner_id, course_id)
        return {"deleted": True, "course_id": course_id, "title": course.get("title", ""), "vector_ids": vector_ids}

    def _insert_mysql(self, learner: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload.get("course_id") or int(time.time() * 1000))
        title = str(payload.get("title") or "未命名课程")
        summary = str(payload.get("summary") or "")
        segments = payload.get("segments") or []
        transcript = "\n".join(f"{item.get('speaker','说话人')}：{item.get('content','')}" for item in segments)
        duration = max([int(item.get("end_ms") or 0) for item in segments] or [0])
        create_time = str(payload.get("create_time") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        metadata = json.dumps({
            "subject": str(payload.get("subject") or "课程"),
            "grade": str(payload.get("grade") or ""),
            "scene": str(payload.get("scene") or "课堂记录"),
            "source_type": str(payload.get("source_type") or "course_text"),
            "source_file_name": str(payload.get("source_file_name") or ""),
            "generation_mode": str(payload.get("generation_mode") or ""),
        }, ensure_ascii=False)
        user_id = learner.get("user_id") or str(learner.get("learner_id") or "").split("-", 1)[0]
        if not str(user_id).isdigit():
            raise MySQLUnavailable("当前学习者没有可写入课程主库的用户编号")
        with self.connect() as connection, connection.cursor() as cursor:
            try:
                cursor.execute(
                    """INSERT INTO user_meeting_info
                       (id,meeting_name,user_id,phone,create_time,update_time,during,title,content,
                        abstract_text,abstract_content,file_type,device_id,data_json,status,del_flag,rebuild_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'txt','zhiyun',%s,'2','0','0')""",
                     (course_id, title, int(user_id), learner.get("phone", ""), create_time,
                     create_time, duration, title, transcript, summary, summary, metadata),
                )
                for index, item in enumerate(segments, start=1):
                    cursor.execute(
                        """INSERT INTO user_meeting_content
                           (begin_time,end_time,speaker,content,meet_id,create_time,code,type)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,'1')""",
                        (int(item.get("begin_ms") or 0), int(item.get("end_ms") or 0),
                         item.get("speaker", "说话人"), item.get("content", ""), course_id,
                         create_time, str(index)[:2]),
                    )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise MySQLUnavailable(str(exc)) from exc
        course = self.detail(str(learner["learner_id"]), course_id)
        self._notify_ingest(learner.get("phone", ""), course_id)
        return course

    def replace_course_content(self, learner_id: str, course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Atomically replace one owned course's generated text and summary."""
        learner = self.learner(learner_id)
        if not self.mysql_configured or not learner.get("phone"):
            raise MySQLUnavailable("共享课程库未配置，课程未更新")
        current = self.detail(learner_id, course_id)
        transcript = str(payload.get("transcript") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        segments = self._segments_from_text(transcript)
        if not summary or not segments:
            raise ValueError("平台 AI 未返回可保存的课程摘要与课程文字")
        duration = max(int(item.get("end_ms") or 0) for item in segments)
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadata = json.dumps({
            "subject": str(payload.get("subject") or current.get("subject") or "课程"),
            "grade": str(payload.get("grade") or current.get("grade") or ""),
            "scene": str(payload.get("scene") or current.get("scene") or "课堂记录"),
            "source_type": "ai_generated_text",
            "source_file_name": str(payload.get("source_file_name") or ""),
            "generation_mode": "ai",
        }, ensure_ascii=False)
        with self.connect() as connection, connection.cursor() as cursor:
            try:
                cursor.execute(
                    """UPDATE user_meeting_info
                       SET update_time=%s,during=%s,content=%s,abstract_text=%s,abstract_content=%s,
                           file_type='txt',device_id='zhiyun',data_json=%s
                       WHERE id=%s AND phone=%s AND status='2' AND (del_flag='0' OR del_flag IS NULL)""",
                    (create_time, duration, transcript, summary, summary, metadata, course_id, learner["phone"]),
                )
                if cursor.rowcount != 1:
                    raise KeyError("课程不存在或不可更新")
                cursor.execute("DELETE FROM user_meeting_content WHERE meet_id=%s", (course_id,))
                for index, item in enumerate(segments, start=1):
                    cursor.execute(
                        """INSERT INTO user_meeting_content
                           (begin_time,end_time,speaker,content,meet_id,create_time,code,type)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,'1')""",
                        (int(item["begin_ms"]), int(item["end_ms"]), item["speaker"], item["content"],
                         course_id, create_time, str(index)[:2]),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        self._notify_ingest(learner["phone"], course_id)
        return self.detail(learner_id, course_id)

    @staticmethod
    def _notify_ingest(phone: str, course_id: str, operation: str = "upsert") -> None:
        base = os.environ.get("INGEST_API_URL", "").strip().rstrip("/")
        if not base:
            return
        body = {"phone": phone, "meeting_id": course_id, "operation": operation,
                "transcript_status": "none" if operation == "delete" else "created",
                "summary_status": "none" if operation == "delete" else "created"}
        try:
            http_json("POST", f"{base}/api/v1/ingest/notifications", body, timeout=3)
        except Exception:
            return


class AIService:
    def __init__(self):
        self.api_key = os.environ.get("AI_API_KEY") or os.environ.get("ARK_API_KEY") or ""
        self.base_url = os.environ.get("AI_BASE_URL") or os.environ.get("ARK_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3"
        self.model = os.environ.get("AI_MODEL", "deepseek-v4-flash-ga-260731")

    def _chat_json(
        self,
        prompt: str,
        temperature: float = 0.1,
        timeout_seconds: int = 90,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if stream:
            request_body["stream"] = True
        if max_tokens:
            request_body["max_tokens"] = int(max_tokens)
        request = Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "text/event-stream" if stream else "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                if stream:
                    parts: list[str] = []
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        event = json.loads(payload)
                        delta = event.get("choices", [{}])[0].get("delta", {})
                        if delta.get("content"):
                            parts.append(str(delta["content"]))
                    content = "".join(parts)
                    if not content:
                        raise RuntimeError("AI 流式响应未返回课程内容")
                    return parse_json_object(content)
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI HTTP {exc.code}: {detail[:500]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"AI transport error: {exc}") from exc
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return parse_json_object(content)

    def generate_demo_course(
        self,
        seed: dict[str, Any],
        duration_range: str = "under_5",
        speaker_mode: str = "2",
    ) -> tuple[dict[str, Any], str]:
        """Use Ark to generate simulated ASR content from scene variables."""
        duration_profiles = {
            "under_5": ("5 分钟以下", 4),
            "5_20": ("5—20 分钟", 12),
            "20_40": ("20—40 分钟", 30),
            "over_40": ("40 分钟以上", 42),
        }
        speaker_profiles = {
            "2": ("2 人", 2),
            "3": ("3 人", 3),
            "4": ("4 人", 4),
            "multi": ("多人", 5),
        }
        if duration_range not in duration_profiles:
            raise ValueError("录音时长范围无效")
        if speaker_mode not in speaker_profiles:
            raise ValueError("说话人数选项无效")
        duration_label, duration_minutes = duration_profiles[duration_range]
        speaker_label, speaker_count = speaker_profiles[speaker_mode]
        min_chars = duration_minutes * 180
        max_chars = duration_minutes * 240
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法生成课程文字内容")

        prompt = f"""请生成一份用于录音转写系统联调的虚构录音转文本数据。

你只根据以下变量生成内容：
【课程主题】《{seed.get('title', '课堂学习记录')}》
【学科】{seed.get('subject', '课程')}
【录音时长】{duration_label}
【说话人数】{speaker_label}

请根据课程主题和学科，自行判断最合理的具体教学场景，并自行确定参与者关系、交流目标、内容结构、专业细节和对话发展。

内容要求：
1. 生成准确、具体、便于检索的课程标题，不使用“测试录音”“模拟数据”等空泛标题。
2. 内容摘要必须完整，长度约为逐字稿的 10%—20%，且所有事实都能在逐字稿中找到依据；摘要使用“本课”“课程内容”等产品语言，不使用“本段录音”“录音中”等表述。
3. 逐字稿总长度按自然中文交流每分钟约 180—240 个汉字估算，本次目标为 {min_chars}—{max_chars} 个汉字，不得用明显过短的内容冒充指定时长。
4. 说话人标签只能是“说话人1”至“说话人{speaker_count}”，数量必须严格一致；不使用老师、学生或姓名作为标签，身份和关系通过对话自然体现。
5. 每个说话人至少发言 3 次；对话围绕场景持续展开，有自然的开始、推进和结束，不得变成一人连续长篇讲述。
6. 逐字稿必须模拟真实录音转写效果，口语特征须覆盖至少 40% 的发言轮次，且类型必须包含以下全部五类：（a）填充词与口头禅：嗯、啊、呃、哦、哈、那个、就是、就是说、其实就是、然后、对吧、是吧、对对对、好好好、怎么讲呢、等一下啊、这样一个、这样一个东西、你看啊、你想想、我说、对了我说、换句话说、也就是说、怎么说呢、反正、大概、差不多、你懂我意思吧，可连续出现（如“嗯……那个就是说”“就是……就是这样一个东西”），也可出现在句中任何位置，尤其频繁出现在句首和话题切换处；（b）重复与磕巴：字词或短语的即刻重复（如“我我我觉得”“这个这个”“就是就是”“然后然后”），以及说到一半重新组织（如“这个是——应该说它是”）；（c）自我纠正：说错后纠正（如“不对，应该是一九——二九”），纠正内容必须保留原错误，不得事后抹除；（d）未完成句与停顿：句子被自己打断、思路切换或用破折号收尾（如“所以这个系数就是——嗯你先说”），句中停顿用省略号表示；（e）含混与跳步：缩读（如“zheige”“nèige”）、吞音、跳过中间步骤直接给结论后补过程（如“等于五……因为三加二嘛”）。同一条发言可同时包含多种特征；也有部分发言完全流畅——两种都要有，但口头禅、磕巴和含混占比应显著高于丝滑发言。口头禅出现频率应接近真实口语：平均每 3—5 句话至少出现 1 次口头禅，不要大面积连续无口头词的流畅段落。
7. 专业内容、知识点和术语必须基本准确，但要体现真实认知过程而非逐字念稿：讲解者可以偶尔记错细节后自行纠正（如“等一下，那个常数应该是 6.626 不是 6.62”）；学习者可以说出大致方向但术语不精确（如用“那个相乘的东西”指代交叉项），等待讲解者补充正式术语；允许“边想边说”（如“我记得好像是……嗯对，就是那个判定条件”）；关键定义和最终结论必须正确，但到达结论的过程应包含犹豫、试错和修正。
8. 教学场景必须包含以下动态：（a）核心教学环节：讲解、提问、作答、错误/困惑、纠正与进一步解释、练习或应用、理解确认与后续建议；（b）打断与抢话：讲解者说到一半被学习者打断追问至少 2 次，打断处用破折号截断，接话者直接切入；（c）同时发言：至少 1 处两人几乎同时开口，其中一方让话或短暂重叠后一方继续；（d）理解偏差与纠正链：学习者至少出现 1 次对核心概念的理解偏差，需经多轮追问和举例才纠正过来；（e）节奏变化：须有“快问快答”段落和“卡壳深挖”段落的交替。不得省略为概述式描述。
9. 不得出现“作为 AI”“以下是生成内容”等元信息，不生成时间戳、序号、旁白、动作说明或舞台提示。
10. 分段规则：真实录音转写中停顿即分段，因此同一说话人连续说话时，如果中间有明显停顿、换气或思路切换，应拆成多条连续同说话人标签的 turn；不要把长段讲话合并为一条，应按自然停顿频率拆分，使同一说话人连续出现多条短 turn 成为常态（类似 VAD 静音检测切分效果）。
11. 角色化口语差异：对话中存在讲解者（如教师、家教）与学习者（如学生）两种角色，虽然标签统一为“说话人X”，但口语特征密度必须按角色区分——（a）讲解者：口语特征以填充词和引导式口头禅为主（如“嗯……”“你看啊”“你想想”“对吧”“也就是说”），重复与磕巴极少出现，自我纠正仅限细节级（如记错一个数字后立即修正），不含低级口误，整体表达偏流畅但保留自然停顿和偶尔的思路组织词；（b）学习者：口语特征全面且高频，磕巴与重复明显多于讲解者（如“我我我觉得”“就是就是”“呃……那个”），含混缩读（如“zheige”“nèige”）频繁出现，自我纠正含低级错误（如单位搞混、概念记反），未完成句和思路卡壳更常见，总体磕巴占比应显著高于讲解者。简言之：讲解者像在边想边讲但专业可信，学习者像在边想边说且经常犯错。

为便于系统入库，必须严格输出以下 JSON，不要输出 Markdown 或其他文字：
{{"title":"课程标题","summary":"内容摘要","turns":[{{"speaker":"说话人1","content":"发言内容"}}]}}
"""
        result = self._chat_json(
            prompt,
            temperature=0.55,
            timeout_seconds=300,
            max_tokens=16384,
            stream=True,
        )
        turns = result.get("turns") or []
        if not isinstance(turns, list):
            raise ValueError("平台 AI 返回的课程对话格式无效")
        allowed = {f"说话人{index}" for index in range(1, speaker_count + 1)}
        cleaned: list[str] = []
        used: set[str] = set()
        for item in turns:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or "").strip()
            content = str(item.get("content") or "").strip()
            if speaker in allowed and content:
                used.add(speaker)
                cleaned.append(f"{speaker}：{content}")
        transcript = "\n\n".join(cleaned)
        han_count = len(re.findall(r"[\u4e00-\u9fff]", transcript))
        if used != allowed or han_count < int(min_chars * 0.72):
            raise ValueError("平台 AI 生成的课程文字未达到说话人数或时长要求，请重试")
        summary = str(result.get("summary") or "").strip()
        if not summary:
            raise ValueError("平台 AI 未生成课程摘要，请重试")
        return {
            "title": str(result.get("title") or seed.get("title") or "课堂学习记录").strip()[:160],
            "summary": summary[:1600],
            "transcript": transcript,
        }, "ai"

    def review(self, course: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法生成课程复盘与知识脉络")
        transcript = "\n".join(
            f"[{item['time_text']}] {item['speaker']}：{item['content']}" for item in course.get("segments", [])
        )[:24000]
        prompt = f"""你是智云课迹的课程复盘与知识结构引擎。只依据给定课程摘要和逐字稿，为学生生成可追溯的课后复盘。
不要评价人格、情绪或智力，不要把课堂中讲过等同于掌握。
知识节点的类型、与主题的关系和子概念必须根据这堂课的真实内容动态提取，不得套用固定三分类。
输出严格 JSON：
{{"structure_version":2,"summary":"不超过180字","objectives":["..."],"knowledge_points":[{{"name":"...","node_type":"根据本课内容命名的类型","relation_to_course":"与课程主题的关系，6字内","explanation":"...","children":["子概念或关键步骤"],"evidence_quote":"逐字稿中的短句","review_prompt":"建议如何验证"}}],"misconceptions":[{{"name":"...","explanation":"...","evidence_quote":"..."}}],"next_action":{{"title":"...","reason":"...","minutes":5}}}}

课程：{course['title']}
已有摘要：{course.get('summary','')}
逐字稿：
{transcript}"""
        review = self._chat_json(prompt)
        if not review.get("knowledge_points"):
            raise ValueError("平台 AI 未生成可用的知识脉络，请重试")
        return review, "ai"

    def growth_summary(self, learner: dict[str, Any], growth: dict[str, Any], course_count: int,
                       run_count: int) -> tuple[dict[str, Any], str]:
        evidence = {
            "course_count": course_count,
            "interaction_count": run_count,
            "mastery": growth.get("mastery", []),
            "recent_events": growth.get("events", [])[:8],
            "plans": growth.get("plans", [])[:6],
        }
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法生成个人成长总结")
        prompt = f"""你是智云课迹的个人成长总结引擎。根据结构化证据生成简洁、克制的中文总结。
不使用人格标签，不预测分数，不编造。输出严格 JSON：
{{"headline":"一句话","narrative":"80字以内，说明进展和依据","strengths":["最多3项"],"watchlist":["最多3项"],"learning_patterns":["仅写有证据的行为模式"],"next_step":"一个可执行动作","recommended_plan":{{"knowledge_point":"...","title":"...","reason":"...","minutes":8}},"evidence_stats":{{"courses":0,"interactions":0,"events":0}}}}
学习者：{learner.get('display_name')}，{learner.get('grade')}
证据：{json.dumps(evidence, ensure_ascii=False)}"""
        return self._chat_json(prompt), "ai"

    def course_relations(self, course: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
        candidates = [item for item in candidates if str(item.get("course_id")) != str(course.get("course_id"))][:20]
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法生成跨课程关联")
        prompt = f"""你是课程关系分析器。只根据课程标题和摘要识别前置、补充、对照或易混淆关系。
输出严格 JSON：{{"links":[{{"course_id":"...","title":"...","relation":"前置|补充|对照|易混淆","reason":"40字以内","shared_concepts":["..."],"confidence":"高|中|低"}}],"explanation":"一句边界说明"}}。
不得把文本相似描述成因果或掌握状态。
当前课程：{json.dumps({key: course.get(key) for key in ('course_id','title','summary')}, ensure_ascii=False)}
候选课程：{json.dumps([{key: item.get(key) for key in ('course_id','title','summary')} for item in candidates], ensure_ascii=False)}"""
        return self._chat_json(prompt), "ai"

    def analyze_learning_dialogue(
        self,
        learner: dict[str, Any],
        course: dict[str, Any],
        turns: list[dict[str, Any]],
        related_memories: list[dict[str, Any]],
        teleagent_summary: str = "",
    ) -> tuple[dict[str, Any], str]:
        """Extract evidence-bearing learning events from a complete interaction."""
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法分析 TeleAgent 学习对话")
        transcript = "\n".join(
            f"[{item.get('time_text','')}] {item.get('speaker','说话人')}：{item.get('content','')}"
            for item in course.get("segments", [])
        )[:18000]
        dialogue = "\n".join(
            f"#{int(item.get('turn_index', index))} {item.get('role','unknown')}：{item.get('content','')}"
            for index, item in enumerate(turns)
        )[:20000]
        memory_context = [
            {key: item.get(key) for key in (
                "memory_type", "title", "content", "knowledge_point", "confidence", "evidence_count"
            )}
            for item in related_memories[:8]
        ]
        prompt = f"""你是智云课迹的平台学习证据分析引擎。你的任务不是简单判对错，而是把一段
TeleAgent 学习对话提炼成可追溯的学习事件和长期记忆候选。

严格规则：
1. 课程原文是知识判断依据；TeleAgent 总结和历史记忆只作线索。
2. 每项洞察必须给出 evidence_turn_indexes；涉及课程事实时给 source_quotes。
3. 区分独立完成、提示后完成、自我纠正和证据不足。证据不足写 uncertain/待验证。
4. 不推断人格、智力、家庭情况或情绪，不因一次表现生成稳定偏好。
5. memory_candidates 只保留对下一次学习真正有用的信息，避免把整段对话改写一遍。
6. 稳定偏好通常需要重复证据；本次只能作为 candidate。一次具体经历可记为 episodic。

输出严格 JSON：
{{
  "episode_summary":"100字内，说明讨论了什么和发生了什么变化",
  "topics":["知识点"],
  "questions_asked":["学生真实提出的问题"],
  "insights":[{{
    "type":"misconception|understanding|question|strategy|self_correction|needs_validation",
    "knowledge_point":"...","content":"具体、克制的发现",
    "verdict":"correct|partial|incorrect|uncertain",
    "assistance_level":"none|one_hint|multiple_hints|direct_answer|unknown",
    "confidence":0.0,"evidence_turn_indexes":[0],"source_quotes":["课程原文短句"]
  }}],
  "memory_candidates":[{{
    "memory_type":"episodic|semantic|preference","title":"短标题","content":"...",
    "knowledge_point":"...","confidence":0.0,"evidence_turn_indexes":[0]
  }}],
  "knowledge_updates":[{{
    "knowledge_point":"...","verdict":"correct|partial|incorrect|uncertain",
    "assistance_level":"none|one_hint|multiple_hints|direct_answer|unknown",
    "self_corrected":false,"reason":"状态变化的证据说明"
  }}],
  "next_actions":[{{"title":"...","knowledge_point":"...","reason":"...","action":"review|verify|compare"}}]
}}

学习者：{learner.get('display_name','当前学习者')}（仅用于数据归属）
课程：{course.get('title','')}
TeleAgent 初步摘要：{teleagent_summary[:3000]}
历史相关记忆：{json.dumps(memory_context, ensure_ascii=False)}
课程原文：
{transcript}

对话原文：
{dialogue}
"""
        return self._chat_json(prompt), "ai"

    def answer_learning_archive(
        self,
        learner: dict[str, Any],
        question: str,
        memories: list[dict[str, Any]],
        mastery: list[dict[str, Any]],
        recent_events: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        context = {
            "memories": [{key: item.get(key) for key in (
                "memory_id", "memory_type", "title", "content", "knowledge_point", "confidence",
                "course_id", "source_run_id", "evidence_count"
            )} for item in memories[:8]],
            "knowledge_states": [
                {**item, "evidence_ref": f"knowledge:{item.get('knowledge_point', '')}"}
                for item in mastery[:10]
            ],
            "recent_events": [
                {**item, "evidence_ref": f"event:{item.get('event_id', '')}"}
                for item in recent_events[:8]
            ],
        }
        if not self.api_key:
            raise RuntimeError("平台 AI 未配置，无法回答长期学习档案问题")
        prompt = f"""你是智云课迹界面中的平台 AI。只依据给定的个人学习档案回答用户问题，
不得使用人格标签、预测分数或编造经历。回答应解释“依据是什么”，并允许证据不足。
输出严格 JSON：{{"answer":"120字内","evidence_refs":["memory_id"],"boundary":"一句边界说明","next_action":"一个可执行动作"}}。
学习者：{learner.get('display_name','当前学习者')}
问题：{question}
学习档案：{json.dumps(context, ensure_ascii=False)}"""
        return self._chat_json(prompt), "ai"


def parse_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        raw = match.group(0)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("AI response is not a JSON object")
    return data


ACTION_LABELS = {
    "course_review": "复盘课程",
    "mind_map": "生成思维导图",
    "learning_check": "学习检测",
    "cross_course_review": "跨课回顾",
    "study_plan": "生成学习建议",
}


class TeleAgentService:
    def __init__(self, store: PlatformStore, courses: CourseRepository):
        self.store = store
        self.courses = courses
        self.receiver_url = os.environ.get(
            "TELEAGENT_RECEIVER_URL", "http://127.0.0.1:18768"
        ).strip().rstrip("/")
        self.token = os.environ.get("TELEAGENT_RECEIVER_TOKEN", "")

    def health(self) -> dict[str, Any]:
        if not self.receiver_url:
            return {"ready": False, "error": "Receiver URL 未配置"}
        try:
            data = http_json("GET", f"{self.receiver_url}/health", token=self.token, timeout=1.5)
            bridge = data.get("bridge") or {}
            return {"ready": data.get("status") == "ok" and bool(bridge.get("ready", True)), **data}
        except Exception as exc:
            return {"ready": False, "error": str(exc), "receiver_url": self.receiver_url}

    def focus(self) -> dict[str, Any]:
        if not self.receiver_url:
            raise RuntimeError("TeleAgent Bridge 未配置")
        return http_json("POST", f"{self.receiver_url}/focus", {}, token=self.token, timeout=4)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "learning_check")
        if action not in ACTION_LABELS:
            raise ValueError("不支持的 TeleAgent 任务")
        learner = self.courses.learner(str(payload["learner_id"]))
        course_id = str(payload.get("course_id") or "")
        course = self.courses.detail(str(learner["learner_id"]), course_id) if course_id else None
        run_id = f"zyk_{uuid.uuid4().hex}"
        focus = str(payload.get("focus") or "本课核心内容")[:120]
        parameters = payload.get("parameters") or {}
        prompt = self._prompt(run_id, learner, course, action, focus, parameters)
        delivery_mode = str(payload.get("delivery_mode") or "copy").strip().lower()
        if delivery_mode not in {"copy", "bridge"}:
            raise ValueError("不支持的 TeleAgent 交付方式")
        run = self.store.create_run({
            "run_id": run_id, "learner_id": str(learner["learner_id"]), "phone": learner.get("phone", ""),
            "course_id": course_id, "course_title": course.get("title", "") if course else "",
            "action": action, "focus": focus, "parameters": parameters, "prompt": prompt,
            "state": "prompt_ready" if delivery_mode == "copy" else (
                "submitting" if self.receiver_url else "demo_ready"
            ),
        })
        if delivery_mode == "copy":
            # Keep a durable run_id before the user enters TeleAgent so the Skill
            # can later return the dialogue to the correct learner/course. The
            # prompt is exposed only in this preparation response, not in run lists.
            return {**run, "prompt": prompt, "delivery_mode": "copy"}
        if not self.receiver_url:
            return run
        try:
            response = http_json(
                "POST", f"{self.receiver_url}/events/learning-task",
                {"event_id": run_id, "recording_id": course_id,
                 "meeting_title": course.get("title", "") if course else "",
                 "learner_name": learner.get("display_name", "学习者"),
                 "action": ACTION_LABELS[action], "focus": focus,
                 "source": "zhiyun-keji", "prompt": prompt},
                token=self.token, timeout=8,
            )
            event_id = str(response.get("event_id") or run_id)
            return self.store.update_run(run_id, state="sent", bridge_event_id=event_id, error="") or run
        except Exception as exc:
            return self.store.update_run(run_id, state="failed", error=str(exc)) or run

    def refresh(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError("TeleAgent task not found")
        if not self.receiver_url or not run.get("bridge_event_id"):
            return run
        if run["state"] in {"completed", "failed"} and run.get("bridge_session_id"):
            return run
        try:
            job = http_json("GET", f"{self.receiver_url}/jobs/{run['bridge_event_id']}", token=self.token, timeout=5)
            state = str(job.get("state") or job.get("status") or run["state"])
            terminal_state = "awaiting_result" if run.get("action") == "learning_check" else "completed"
            mapped = {"queued": "sent", "submitting": "sent", "running": "running",
                      "completed": terminal_state, "failed": "failed", "skipped": "failed"}.get(state, state)
            response_text = job.get("response_text") or job.get("outbound_text") or ""
            session_id = str(job.get("session_id") or "")
            if run.get("result", {}).get("analysis"):
                return self.store.update_run(
                    run_id, bridge_session_id=session_id, error=str(job.get("error") or "")
                ) or run
            if mapped in {"awaiting_result", "completed"} and response_text:
                result = {
                    "summary": response_text, "source": "bridge_text", "questions": [],
                    "teleagent_session_id": session_id,
                }
                return self.store.update_run(
                    run_id, state=mapped, bridge_session_id=session_id, result_json=result
                ) or run
            return self.store.update_run(
                run_id, state=mapped, bridge_session_id=session_id,
                error=str(job.get("error") or ""),
            ) or run
        except Exception as exc:
            return self.store.update_run(run_id, error=str(exc)) or run

    @staticmethod
    def _prompt(run_id: str, learner: dict[str, Any], course: dict[str, Any] | None,
                action: str, focus: str, parameters: dict[str, Any]) -> str:
        course_id = course.get("course_id", "") if course else ""
        title = course.get("title", "当前学习记录") if course else "当前学习记录"
        count = max(1, min(5, int(parameters.get("question_count") or 3)))
        difficulty = str(parameters.get("difficulty") or "跟随课堂")
        task = ACTION_LABELS[action]
        common = (
            "【智云课迹平台任务｜必须按以下协议执行】\n"
            "1. 必须加载并严格执行 TeleAgent Skill：zhiyun-keji-learning；不要按普通聊天直接作答。\n"
            "2. 该 Skill 的课程读取、对话组织和回流规范优先；只使用 zhiyun-learning MCP，"
            "不要调用 meeting-assistant MCP。\n"
            f"3. 固定任务标识：course_id={course_id}；run_id={run_id}；action={action}。"
            "后续所有课程工具和 complete_learning_interaction 都必须原样使用这些标识。\n"
            f"4. 学习者：{learner.get('display_name','当前学生')}；课程：《{title}》；"
            f"本次任务：{task}；重点：{focus}。\n"
            "5. 开始时先使用 get_course_summary(course_id)，涉及细节再使用 get_course_transcript "
            "或 search_course_content(query, course_id=course_id) 读取课程依据；"
            "重要结论标注课程原文或时间点。\n"
            "6. 若 Skill 未加载、课程无权限或 course_id 不存在，请明确报告错误，不要编造课程内容。\n"
        )
        multi_turn_rule = (
            "这是平台发起的多轮学习会话。首轮只需给出简短开场并提出一个问题，"
            "同时告诉学习者：交流完成后发送‘结束复盘并回流课迹’。"
            "在学习者明确结束前，不要调用 complete_learning_interaction，也不要声称平台已更新。"
            "整个会话中持续保留学生问题、回答、你的提示和学生纠正，回流时按发生顺序提交。"
        )
        if action == "learning_check":
            return common + multi_turn_rule + (
                f"请围绕重点进行不超过 {count} 个回合的自然检测，问题层次为“{difficulty}”，每次只问一个问题；"
                "回合数是上限，不要为凑数而重复出题。"
                "既记录答案，也关注学生如何解释、是否使用提示、是否自我纠正。"
                "结束时总结本次讨论发生了什么，不要直接修改长期画像。"
                f"最后必须调用 complete_learning_interaction，run_id={run_id}，course_id={course_id}，"
                "dialogue_turns 按顺序提交学生问题、回答、你的提示及学生纠正等关键原文。"
                "平台 AI 会结合课程原文独立提炼误区、提示依赖、待验证项和长期记忆候选。"
            )
        if action == "course_review":
            return common + multi_turn_rule + (
                "请先邀请学生提出最想弄懂的问题，再围绕课程主线进行复盘和追问。"
                f"结束后调用 complete_learning_interaction，run_id={run_id}，course_id={course_id}，"
                "回流关键对话原文、复盘摘要和生成产物。"
            )
        if action == "mind_map":
            return common + (
                "请生成不超过三层的课程思维导图，重要节点附来源；完成后调用 "
                f"complete_learning_interaction，run_id={run_id}，course_id={course_id}，"
                "把关键对话和思维导图作为 artifact 回流平台。"
            )
        if action == "cross_course_review":
            return common + (
                "请使用 find_related_courses 找到相关历史讲解，说明联系和差异；结束后调用 "
                f"complete_learning_interaction，run_id={run_id}，course_id={course_id} 回流关键对话。"
            )
        return common + (
            "请先使用 get_learning_context 读取相关学习档案，再给出一个十分钟以内、可执行的建议；"
            f"结束后调用 complete_learning_interaction，run_id={run_id}，course_id={course_id}。"
        )


def http_json(method: str, url: str, payload: dict[str, Any] | None = None,
              token: str = "", timeout: float = 8) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["X-Bridge-Token"] = token
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"连接失败：{exc.reason}") from exc
    return json.loads(body or "{}")
