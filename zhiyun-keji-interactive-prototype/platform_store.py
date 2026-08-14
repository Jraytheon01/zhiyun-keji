from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_text() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PlatformStore:
    """Small durable platform ledger for the competition build.

    Course source-of-truth remains user_meeting_info/user_meeting_content. This store
    owns only platform-local learners, reviews, TeleAgent runs and growth evidence.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS local_learner (
          learner_id TEXT PRIMARY KEY,
          phone TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL,
          grade TEXT NOT NULL DEFAULT '',
          subject TEXT NOT NULL DEFAULT '数学',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS local_course (
          course_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          title TEXT NOT NULL,
          create_time TEXT NOT NULL,
          duration_ms INTEGER NOT NULL DEFAULT 0,
          summary TEXT NOT NULL DEFAULT '',
          subject TEXT NOT NULL DEFAULT '数学',
          grade TEXT NOT NULL DEFAULT '',
          scene TEXT NOT NULL DEFAULT '学校课堂',
          source_type TEXT NOT NULL DEFAULT 'demo',
          status TEXT NOT NULL DEFAULT 'ready',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_course_learner ON local_course(learner_id, create_time DESC);
        CREATE TABLE IF NOT EXISTS local_segment (
          segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
          course_id TEXT NOT NULL,
          begin_ms INTEGER NOT NULL,
          end_ms INTEGER NOT NULL,
          speaker TEXT NOT NULL,
          content TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_local_segment_course ON local_segment(course_id, begin_ms);
        CREATE TABLE IF NOT EXISTS course_review (
          learner_id TEXT NOT NULL,
          course_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          mode TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (learner_id, course_id)
        );
        CREATE TABLE IF NOT EXISTS teleagent_run (
          run_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          phone TEXT NOT NULL DEFAULT '',
          course_id TEXT NOT NULL DEFAULT '',
          course_title TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL,
          focus TEXT NOT NULL DEFAULT '',
          parameters_json TEXT NOT NULL DEFAULT '{}',
          prompt TEXT NOT NULL,
          state TEXT NOT NULL,
          bridge_event_id TEXT NOT NULL DEFAULT '',
          bridge_session_id TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '{}',
          error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_run_learner ON teleagent_run(learner_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS learning_event (
          event_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          course_id TEXT NOT NULL DEFAULT '',
          event_type TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          evidence_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_event_learner ON learning_event(learner_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS mastery_state (
          learner_id TEXT NOT NULL,
          knowledge_point TEXT NOT NULL,
          level TEXT NOT NULL,
          evidence_count INTEGER NOT NULL DEFAULT 0,
          last_reason TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL,
          PRIMARY KEY (learner_id, knowledge_point)
        );
        CREATE TABLE IF NOT EXISTS growth_plan (
          plan_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          knowledge_point TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL,
          reason TEXT NOT NULL,
          minutes INTEGER NOT NULL DEFAULT 5,
          status TEXT NOT NULL DEFAULT 'today',
          source_run_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_plan_learner ON growth_plan(learner_id, status, created_at DESC);
        CREATE TABLE IF NOT EXISTS memory_item (
          memory_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          memory_type TEXT NOT NULL,
          content TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'active',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS growth_summary (
          learner_id TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          mode TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_dialogue_turn (
          run_id TEXT NOT NULL,
          learner_id TEXT NOT NULL,
          course_id TEXT NOT NULL DEFAULT '',
          turn_index INTEGER NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (run_id, turn_index)
        );
        CREATE INDEX IF NOT EXISTS idx_dialogue_learner ON learning_dialogue_turn(learner_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS dialogue_insight (
          insight_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          learner_id TEXT NOT NULL,
          course_id TEXT NOT NULL DEFAULT '',
          insight_type TEXT NOT NULL,
          knowledge_point TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL,
          verdict TEXT NOT NULL DEFAULT 'uncertain',
          assistance_level TEXT NOT NULL DEFAULT 'unknown',
          confidence REAL NOT NULL DEFAULT 0,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_insight_learner ON dialogue_insight(learner_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS learning_memory (
          memory_id TEXT PRIMARY KEY,
          vector_id INTEGER NOT NULL UNIQUE,
          learner_id TEXT NOT NULL,
          course_id TEXT NOT NULL DEFAULT '',
          source_run_id TEXT NOT NULL DEFAULT '',
          memory_type TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          content TEXT NOT NULL,
          knowledge_point TEXT NOT NULL DEFAULT '',
          confidence REAL NOT NULL DEFAULT 0,
          evidence_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'candidate',
          vector_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learning_memory_learner ON learning_memory(learner_id, status, updated_at DESC);
        CREATE TABLE IF NOT EXISTS learning_memory_evidence (
          memory_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          course_id TEXT NOT NULL DEFAULT '',
          turn_indexes_json TEXT NOT NULL DEFAULT '[]',
          source_quotes_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          PRIMARY KEY (memory_id, run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_evidence_run ON learning_memory_evidence(run_id);
        CREATE TABLE IF NOT EXISTS archive_chat_message (
          message_id TEXT PRIMARY KEY,
          learner_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          evidence_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_archive_chat_learner ON archive_chat_message(learner_id, created_at ASC);
        """
        with self._lock, self.connect() as connection:
            connection.executescript(schema)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(teleagent_run)")}
            if "bridge_session_id" not in columns:
                connection.execute(
                    "ALTER TABLE teleagent_run ADD COLUMN bridge_session_id TEXT NOT NULL DEFAULT ''"
                )

    def local_learners(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT learner_id, phone, display_name, grade, subject FROM local_learner ORDER BY learner_id"
            )]

    def upsert_local_learner(self, learner: dict[str, Any]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO local_learner(learner_id,phone,display_name,grade,subject,created_at)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(learner_id) DO UPDATE SET
                   phone=excluded.phone, display_name=excluded.display_name,
                   grade=excluded.grade, subject=excluded.subject""",
                (str(learner["learner_id"]), learner.get("phone", ""), learner.get("display_name", "学习者"),
                 learner.get("grade", ""), learner.get("subject", "数学"), now_text()),
            )

    def local_courses(self, learner_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM local_course WHERE learner_id=? ORDER BY create_time DESC", (learner_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def local_course(self, learner_id: str, course_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM local_course WHERE learner_id=? AND course_id=?", (learner_id, course_id)
            ).fetchone()
        return dict(row) if row else None

    def local_segments(self, course_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM local_segment WHERE course_id=? ORDER BY begin_ms, segment_id", (course_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_local_course(self, learner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        course_id = str(payload.get("course_id") or int(datetime.now().timestamp() * 1000))
        title = str(payload.get("title") or "未命名课程").strip()
        summary = str(payload.get("summary") or "").strip()
        segments = payload.get("segments") or []
        created = now_text()
        create_time = str(payload.get("create_time") or created.replace("T", " ")[:19])
        duration = max([int(item.get("end_ms") or item.get("end_time") or 0) for item in segments] or [0])
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO local_course(course_id,learner_id,title,create_time,duration_ms,summary,
                   subject,grade,scene,source_type,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (course_id, learner_id, title, create_time, duration, summary,
                 payload.get("subject", "数学"), payload.get("grade", ""),
                 payload.get("scene", "学校课堂"), payload.get("source_type", "text"), "ready", created),
            )
            for index, item in enumerate(segments):
                begin = int(item.get("begin_ms") or item.get("begin_time") or index * 15000)
                end = int(item.get("end_ms") or item.get("end_time") or begin + 14000)
                connection.execute(
                    "INSERT INTO local_segment(course_id,begin_ms,end_ms,speaker,content) VALUES (?,?,?,?,?)",
                    (course_id, begin, end, item.get("speaker", "说话人"), item.get("content", "")),
                )
        return self.local_course(learner_id, course_id) or {}

    def get_review(self, learner_id: str, course_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM course_review WHERE learner_id=? AND course_id=?", (learner_id, course_id)
            ).fetchone()
        if not row:
            return None
        return {"payload": json.loads(row["payload_json"]), "mode": row["mode"], "updated_at": row["updated_at"]}

    def save_review(self, learner_id: str, course_id: str, payload: dict[str, Any], mode: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO course_review VALUES (?,?,?,?,?)
                   ON CONFLICT(learner_id,course_id) DO UPDATE SET
                   payload_json=excluded.payload_json,mode=excluded.mode,updated_at=excluded.updated_at""",
                (learner_id, course_id, json_text(payload), mode, now_text()),
            )

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload.get("run_id") or f"zyk_{uuid.uuid4().hex}"
        timestamp = now_text()
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO teleagent_run(run_id,learner_id,phone,course_id,course_title,action,
                   focus,parameters_json,prompt,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, payload["learner_id"], payload.get("phone", ""), payload.get("course_id", ""),
                 payload.get("course_title", ""), payload["action"], payload.get("focus", ""),
                 json_text(payload.get("parameters", {})), payload["prompt"], payload.get("state", "queued"),
                 timestamp, timestamp),
            )
        return self.get_run(run_id) or {}

    def update_run(self, run_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {"state", "bridge_event_id", "bridge_session_id", "result_json", "error"}
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return self.get_run(run_id)
        if "result_json" in values and not isinstance(values["result_json"], str):
            values["result_json"] = json_text(values["result_json"])
        values["updated_at"] = now_text()
        assignments = ",".join(f"{key}=?" for key in values)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE teleagent_run SET {assignments} WHERE run_id=?", (*values.values(), run_id)
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM teleagent_run WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["parameters"] = json.loads(result.pop("parameters_json") or "{}")
        result["result"] = json.loads(result.pop("result_json") or "{}")
        result.pop("prompt", None)
        return result

    def recent_runs(self, learner_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT run_id FROM teleagent_run WHERE learner_id=? ORDER BY created_at DESC LIMIT ?",
                (learner_id, limit),
            ).fetchall()
        return [self.get_run(row["run_id"]) for row in rows if self.get_run(row["run_id"])]

    def add_archive_chat_message(self, learner_id: str, role: str, content: str,
                                 evidence: Any = None) -> dict[str, Any]:
        message = {
            "message_id": f"chat_{uuid.uuid4().hex}", "learner_id": learner_id,
            "role": role, "content": content, "evidence": evidence or [],
            "created_at": now_text(),
        }
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO archive_chat_message VALUES (?,?,?,?,?,?)",
                (message["message_id"], learner_id, role, content,
                 json_text(message["evidence"]), message["created_at"]),
            )
        return message

    def archive_chat(self, learner_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM (SELECT * FROM archive_chat_message WHERE learner_id=?
                   ORDER BY created_at DESC LIMIT ?) ORDER BY created_at ASC""",
                (learner_id, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["evidence"] = json.loads(item.pop("evidence_json") or "[]")
            items.append(item)
        return items

    def clear_archive_chat(self, learner_id: str) -> int:
        """Clear only the current learner's platform-AI conversation history."""
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM archive_chat_message WHERE learner_id=?",
                (learner_id,),
            )
        return max(0, int(cursor.rowcount or 0))

    def add_event(self, learner_id: str, course_id: str, event_type: str, title: str,
                  description: str = "", evidence: Any = None) -> str:
        event_id = f"evt_{uuid.uuid4().hex}"
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO learning_event VALUES (?,?,?,?,?,?,?,?)",
                (event_id, learner_id, course_id, event_type, title, description,
                 json_text(evidence or {}), now_text()),
            )
        return event_id

    def upsert_mastery(self, learner_id: str, knowledge_point: str, correct: bool, reason: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM mastery_state WHERE learner_id=? AND knowledge_point=?",
                (learner_id, knowledge_point),
            ).fetchone()
            previous = current["level"] if current else "待验证"
            evidence_count = int(current["evidence_count"]) + 1 if current else 1
            if correct:
                level = "掌握中" if previous in {"待验证", "已接触"} and evidence_count >= 2 else previous
                if previous not in {"待巩固", "较稳固"} and evidence_count < 2:
                    level = "待验证"
                if previous == "较稳固":
                    level = previous
            else:
                level = "待巩固"
            connection.execute(
                """INSERT INTO mastery_state VALUES (?,?,?,?,?,?)
                   ON CONFLICT(learner_id,knowledge_point) DO UPDATE SET
                   level=excluded.level,evidence_count=excluded.evidence_count,
                   last_reason=excluded.last_reason,updated_at=excluded.updated_at""",
                (learner_id, knowledge_point, level, evidence_count, reason, now_text()),
            )
        return {"knowledge_point": knowledge_point, "previous": previous, "level": level,
                "evidence_count": evidence_count, "reason": reason}

    def add_plan(self, learner_id: str, knowledge_point: str, title: str, reason: str,
                 minutes: int, source_run_id: str) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            existing = connection.execute(
                """SELECT * FROM growth_plan WHERE learner_id=? AND knowledge_point=?
                   AND status IN ('today','next') ORDER BY created_at DESC LIMIT 1""",
                (learner_id, knowledge_point),
            ).fetchone()
            if existing:
                return dict(existing)
            plan_id = f"plan_{uuid.uuid4().hex}"
            timestamp = now_text()
            connection.execute(
                "INSERT INTO growth_plan VALUES (?,?,?,?,?,?,?,?,?,?)",
                (plan_id, learner_id, knowledge_point, title, reason, minutes, "today",
                 source_run_id, timestamp, timestamp),
            )
        return self.plan(plan_id) or {}

    def complete_plan(self, learner_id: str, plan_id: str, reflection: str = "") -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            plan = connection.execute(
                "SELECT * FROM growth_plan WHERE plan_id=? AND learner_id=?", (plan_id, learner_id)
            ).fetchone()
            if not plan:
                raise KeyError("学习计划不存在")
            if plan["status"] != "done":
                connection.execute(
                    "UPDATE growth_plan SET status='done',updated_at=? WHERE plan_id=?",
                    (now_text(), plan_id),
                )
                memory_id = f"plan_memory_{plan_id}"
                content = reflection.strip() or f"已完成计划：{plan['title']}；仍需后续客观作答验证掌握状态。"
                connection.execute(
                    """INSERT INTO memory_item(memory_id,learner_id,memory_type,content,evidence_json,status,updated_at)
                       VALUES (?,?,?,?,?,'active',?) ON CONFLICT(memory_id) DO UPDATE SET
                       content=excluded.content,evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
                    (memory_id, learner_id, "plan_reflection", content,
                     json_text({"plan_id": plan_id, "knowledge_point": plan["knowledge_point"]}), now_text()),
                )
        completed = self.plan(plan_id) or {}
        self.add_event(
            learner_id, "", "plan_completed", f"完成学习计划：{completed.get('title', '')}",
            "完成记录已进入平台成长档案；掌握状态等待下一次客观互动验证。",
            {"plan_id": plan_id, "reflection": reflection},
        )
        return completed

    def plan(self, plan_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM growth_plan WHERE plan_id=?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def apply_learning_result(self, run_id: str, result: dict[str, Any]) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            raise KeyError("TeleAgent task not found")
        if run["state"] == "completed" and run.get("result"):
            return {"run": run, "changes": run["result"].get("changes", []), "idempotent": True}
        questions = [item for item in (result.get("questions") or []) if isinstance(item, dict)]
        changes = []
        plans = []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for question in questions:
            kp = str(question.get("knowledge_point") or result.get("focus") or run.get("focus") or "本课核心知识")
            grouped.setdefault(kp, []).append(question)
        for kp, evidence_items in grouped.items():
            correct_count = sum(1 for item in evidence_items if bool(item.get("correct")))
            all_correct = correct_count == len(evidence_items) and bool(evidence_items)
            reason = f"TeleAgent 学习检测共 {len(evidence_items)} 题，答对 {correct_count} 题"
            change = self.upsert_mastery(run["learner_id"], kp, all_correct, reason)
            changes.append(change)
            if not all_correct:
                plans.append(self.add_plan(
                    run["learner_id"], kp, f"再验证 {kp}", reason, 5, run_id
                ))
        enriched = dict(result)
        enriched["changes"] = changes
        enriched["plans"] = plans
        self.update_run(run_id, state="completed", result_json=enriched, error="")
        correct_count = sum(1 for question in questions if question.get("correct"))
        self.add_event(
            run["learner_id"], run["course_id"], "teleagent_result",
            f"完成 TeleAgent {self.action_label(run['action'])}",
            f"共 {len(questions)} 题，答对 {correct_count} 题。" if questions else str(result.get("summary") or "互动结果已回流。"),
            {"run_id": run_id, "changes": changes},
        )
        for change in changes:
            if change["previous"] != change["level"]:
                self.add_event(
                    run["learner_id"], run["course_id"], "mastery_changed",
                    f"{change['knowledge_point']}：{change['previous']} → {change['level']}",
                    change["reason"], {"run_id": run_id, "change": change},
                )
        return {"run": self.get_run(run_id), "changes": changes, "plans": plans, "idempotent": False}

    @staticmethod
    def action_label(action: str) -> str:
        return {
            "course_review": "课程复盘", "mind_map": "思维导图",
            "learning_check": "学习检测", "cross_course_review": "跨课回顾",
            "study_plan": "学习建议",
        }.get(action, "学习互动")

    def growth(self, learner_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            states = [dict(row) for row in connection.execute(
                "SELECT * FROM mastery_state WHERE learner_id=? ORDER BY updated_at DESC", (learner_id,)
            )]
            events = [dict(row) for row in connection.execute(
                "SELECT * FROM learning_event WHERE learner_id=? ORDER BY created_at DESC LIMIT 30", (learner_id,)
            )]
            plans = [dict(row) for row in connection.execute(
                "SELECT * FROM growth_plan WHERE learner_id=? ORDER BY created_at DESC", (learner_id,)
            )]
            memories = [dict(row) for row in connection.execute(
                "SELECT * FROM memory_item WHERE learner_id=? AND status='active' ORDER BY updated_at DESC", (learner_id,)
            )]
            summary = connection.execute(
                "SELECT * FROM growth_summary WHERE learner_id=?", (learner_id,)
            ).fetchone()
        for event in events:
            event["evidence"] = json.loads(event.pop("evidence_json") or "{}")
        for memory in memories:
            memory["evidence"] = json.loads(memory.pop("evidence_json") or "{}")
        return {
            "mastery": states,
            "events": events,
            "plans": plans,
            "memories": memories,
            "summary": json.loads(summary["payload_json"]) if summary else None,
            "summary_mode": summary["mode"] if summary else "",
        }

    def save_growth_summary(self, learner_id: str, payload: dict[str, Any], mode: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO growth_summary VALUES (?,?,?,?)
                   ON CONFLICT(learner_id) DO UPDATE SET payload_json=excluded.payload_json,
                   mode=excluded.mode,updated_at=excluded.updated_at""",
                (learner_id, json_text(payload), mode, now_text()),
            )

    def save_dialogue_turns(self, run: dict[str, Any], turns: list[dict[str, Any]]) -> None:
        with self._lock, self.connect() as connection:
            for index, turn in enumerate(turns[:80]):
                content = str(turn.get("content") or "").strip()[:4000]
                if not content:
                    continue
                connection.execute(
                    """INSERT OR REPLACE INTO learning_dialogue_turn
                       (run_id,learner_id,course_id,turn_index,role,content,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (run["run_id"], run["learner_id"], run.get("course_id", ""),
                     int(turn.get("turn_index", index)), str(turn.get("role") or "unknown")[:24],
                     content, now_text()),
                )

    def dialogue_turns(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM learning_dialogue_turn WHERE run_id=? ORDER BY turn_index", (run_id,)
            )]

    def save_dialogue_analysis(self, run: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        timestamp = now_text()
        insights: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []
        with self._lock, self.connect() as connection:
            existing = connection.execute(
                "SELECT COUNT(*) n FROM dialogue_insight WHERE run_id=?", (run["run_id"],)
            ).fetchone()["n"]
            if existing:
                return {
                    "insights": self.dialogue_insights(run["learner_id"], run_id=run["run_id"]),
                    "memories": self.memories_for_run(run["run_id"]),
                    "idempotent": True,
                }
            for item in (analysis.get("insights") or [])[:20]:
                if not isinstance(item, dict) or not str(item.get("content") or "").strip():
                    continue
                insight_id = f"ins_{uuid.uuid4().hex}"
                evidence = {
                    "turn_indexes": item.get("evidence_turn_indexes") or [],
                    "source_quotes": item.get("source_quotes") or [],
                }
                row = {
                    "insight_id": insight_id, "run_id": run["run_id"],
                    "learner_id": run["learner_id"], "course_id": run.get("course_id", ""),
                    "insight_type": str(item.get("type") or "observation")[:48],
                    "knowledge_point": str(item.get("knowledge_point") or "")[:160],
                    "content": str(item.get("content") or "")[:1600],
                    "verdict": str(item.get("verdict") or "uncertain")[:32],
                    "assistance_level": str(item.get("assistance_level") or "unknown")[:32],
                    "confidence": max(0.0, min(1.0, float(item.get("confidence") or 0))),
                    "evidence": evidence, "status": "candidate", "created_at": timestamp,
                }
                connection.execute(
                    """INSERT INTO dialogue_insight VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["insight_id"], row["run_id"], row["learner_id"], row["course_id"],
                     row["insight_type"], row["knowledge_point"], row["content"], row["verdict"],
                     row["assistance_level"], row["confidence"], json_text(evidence), row["status"], timestamp),
                )
                insights.append(row)
            for item in (analysis.get("memory_candidates") or [])[:12]:
                if not isinstance(item, dict) or not str(item.get("content") or "").strip():
                    continue
                raw_key = "|".join([
                    run["learner_id"], str(item.get("memory_type") or "episodic"),
                    str(item.get("knowledge_point") or ""), str(item.get("content") or "").strip().lower(),
                ])
                digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
                memory_id = f"mem_{digest[:24]}"
                vector_id = int.from_bytes(bytes.fromhex(digest[:16]), "big") & 0x7FFF_FFFF_FFFF_FFFF
                confidence = max(0.0, min(1.0, float(item.get("confidence") or 0)))
                status = "active" if confidence >= 0.82 and str(item.get("memory_type")) == "episodic" else "candidate"
                evidence = {"run_id": run["run_id"], "turn_indexes": item.get("evidence_turn_indexes") or []}
                connection.execute(
                    """INSERT INTO learning_memory
                       (memory_id,vector_id,learner_id,course_id,source_run_id,memory_type,title,content,
                        knowledge_point,confidence,evidence_json,status,vector_status,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(memory_id) DO UPDATE SET confidence=MAX(confidence,excluded.confidence),
                         evidence_json=excluded.evidence_json,vector_status='pending',updated_at=excluded.updated_at""",
                    (memory_id, vector_id, run["learner_id"], run.get("course_id", ""), run["run_id"],
                     str(item.get("memory_type") or "episodic")[:48], str(item.get("title") or "学习发现")[:160],
                     str(item.get("content") or "")[:2000], str(item.get("knowledge_point") or "")[:160],
                     confidence, json_text(evidence), status, "pending", timestamp, timestamp),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO learning_memory_evidence
                       (memory_id,run_id,course_id,turn_indexes_json,source_quotes_json,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (memory_id, run["run_id"], run.get("course_id", ""),
                     json_text(item.get("evidence_turn_indexes") or []),
                     json_text(item.get("source_quotes") or []), timestamp),
                )
                evidence_count = connection.execute(
                    "SELECT COUNT(*) n FROM learning_memory_evidence WHERE memory_id=?", (memory_id,)
                ).fetchone()["n"]
                if evidence_count >= 2:
                    status = "active"
                    connection.execute(
                        "UPDATE learning_memory SET status='active',updated_at=? WHERE memory_id=?",
                        (timestamp, memory_id),
                    )
                memories.append({
                    "memory_id": memory_id, "vector_id": vector_id, "learner_id": run["learner_id"],
                    "course_id": run.get("course_id", ""), "source_run_id": run["run_id"],
                    "memory_type": str(item.get("memory_type") or "episodic"),
                    "title": str(item.get("title") or "学习发现"), "content": str(item.get("content") or ""),
                    "knowledge_point": str(item.get("knowledge_point") or ""), "confidence": confidence,
                    "status": status, "evidence": evidence, "evidence_count": evidence_count,
                    "vector_status": "pending",
                })
        return {"insights": insights, "memories": memories, "idempotent": False}

    def dialogue_insights(self, learner_id: str, limit: int = 30, run_id: str = "") -> list[dict[str, Any]]:
        query = "SELECT * FROM dialogue_insight WHERE learner_id=?"
        params: list[Any] = [learner_id]
        if run_id:
            query += " AND run_id=?"
            params.append(run_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(query, params)]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
        return rows

    def memories_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT DISTINCT m.* FROM learning_memory m
                   LEFT JOIN learning_memory_evidence e ON e.memory_id=m.memory_id
                   WHERE m.source_run_id=? OR e.run_id=? ORDER BY m.updated_at DESC""", (run_id, run_id)
            )]
        return self._decode_learning_memories(rows)

    def recent_learning_memories(self, learner_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """SELECT * FROM learning_memory WHERE learner_id=? AND status IN ('active','candidate')
                   ORDER BY updated_at DESC LIMIT ?""", (learner_id, limit)
            )]
        return self._decode_learning_memories(rows)

    def learning_memories_by_vector_ids(self, vector_ids: list[int]) -> list[dict[str, Any]]:
        if not vector_ids:
            return []
        placeholders = ",".join("?" for _ in vector_ids)
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                f"SELECT * FROM learning_memory WHERE vector_id IN ({placeholders})", vector_ids
            )]
        return self._decode_learning_memories(rows)

    def _decode_learning_memories(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
            with self.connect() as connection:
                evidence_rows = [dict(item) for item in connection.execute(
                    """SELECT run_id,course_id,turn_indexes_json,source_quotes_json,created_at
                       FROM learning_memory_evidence WHERE memory_id=? ORDER BY created_at DESC""",
                    (row["memory_id"],),
                )]
            for item in evidence_rows:
                item["turn_indexes"] = json.loads(item.pop("turn_indexes_json") or "[]")
                item["source_quotes"] = json.loads(item.pop("source_quotes_json") or "[]")
            if not evidence_rows and row.get("source_run_id"):
                evidence_rows = [{
                    "run_id": row["source_run_id"], "course_id": row.get("course_id", ""),
                    "turn_indexes": row["evidence"].get("turn_indexes", []),
                    "source_quotes": [], "created_at": row.get("created_at", ""),
                }]
            row["evidence_sources"] = evidence_rows
            row["evidence_count"] = len(evidence_rows)
        return rows

    def mark_memories_indexed(self, vector_ids: list[int]) -> None:
        if not vector_ids:
            return
        placeholders = ",".join("?" for _ in vector_ids)
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE learning_memory SET vector_status='indexed',updated_at=? WHERE vector_id IN ({placeholders})",
                (now_text(), *vector_ids),
            )

    def update_mastery_from_dialogue(self, learner_id: str, update: dict[str, Any]) -> dict[str, Any] | None:
        knowledge_point = str(update.get("knowledge_point") or "").strip()[:160]
        if not knowledge_point:
            return None
        verdict = str(update.get("verdict") or "uncertain")
        assistance = str(update.get("assistance_level") or "unknown")
        corrected = bool(update.get("self_corrected"))
        reason = str(update.get("reason") or "来自一次 TeleAgent 学习对话的证据")[:500]
        with self._lock, self.connect() as connection:
            current = connection.execute(
                "SELECT * FROM mastery_state WHERE learner_id=? AND knowledge_point=?",
                (learner_id, knowledge_point),
            ).fetchone()
            previous = current["level"] if current else "待验证"
            evidence_count = int(current["evidence_count"] or 0) + 1 if current else 1
            if verdict == "incorrect":
                level = "理解形成中" if corrected else "待巩固"
            elif verdict == "partial" or assistance not in {"none", "independent"}:
                level = "理解形成中"
            elif verdict == "correct":
                level = "较稳固" if previous == "掌握中" and evidence_count >= 3 else "掌握中"
            else:
                level = previous if current else "待验证"
            connection.execute(
                """INSERT INTO mastery_state VALUES (?,?,?,?,?,?)
                   ON CONFLICT(learner_id,knowledge_point) DO UPDATE SET level=excluded.level,
                   evidence_count=excluded.evidence_count,last_reason=excluded.last_reason,
                   updated_at=excluded.updated_at""",
                (learner_id, knowledge_point, level, evidence_count, reason, now_text()),
            )
        return {"knowledge_point": knowledge_point, "previous": previous, "level": level,
                "evidence_count": evidence_count, "reason": reason}
