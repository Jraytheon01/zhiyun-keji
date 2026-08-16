#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", encoding="utf-8-sig")

from platform_services import AIService, CourseRepository, TeleAgentService  # noqa: E402
from platform_memory import LearningMemoryIndex  # noqa: E402
from platform_store import PlatformStore  # noqa: E402


class PlatformApp:
    def __init__(self):
        data_root = Path(os.environ.get("PLATFORM_DATA_DIR", "./data"))
        if not data_root.is_absolute():
            data_root = ROOT / data_root
        self.store = PlatformStore(data_root / "zhiyun_keji.sqlite3")
        self.courses = CourseRepository(self.store)
        self.ai = AIService()
        self.memory = LearningMemoryIndex(self.store)
        self.teleagent = TeleAgentService(self.store, self.courses)
        self.write_token = os.environ.get("PLATFORM_WRITE_TOKEN", "")
        self._import_wakeup = threading.Event()
        self._import_worker = threading.Thread(target=self._run_import_worker, name="course-import-worker", daemon=True)
        self._import_worker.start()

    def learner_id(self, query: dict[str, list[str]]) -> str:
        requested = str((query.get("learner_id") or [""])[0]).strip()
        learners = self.courses.learners()
        if requested and any(str(item["learner_id"]) == requested for item in learners):
            return requested
        if not learners:
            raise KeyError("当前没有可用学习者")
        return str(learners[0]["learner_id"])

    def bootstrap(self, learner_id: str) -> dict:
        learner = self.courses.learner(learner_id)
        courses = self.courses.courses(learner_id)
        growth = self.store.growth(learner_id)
        runs = self.store.recent_runs(learner_id, 8)
        teleagent_health = self.teleagent.health()
        return {
            "learner": learner,
            "learners": self.courses.learners(),
            "courses": courses,
            "recent_runs": runs,
            "growth": growth,
            "capabilities": {
                "mysql": self.courses.mysql_configured,
                "ai": bool(self.ai.api_key),
                "teleagent": bool(teleagent_health.get("ready")),
            },
            "teleagent_health": teleagent_health,
            "memory_health": self.memory.health(),
        }

    def create_import_job(self, learner_id: str, payload: dict) -> dict:
        self.courses.learner(learner_id)
        if not str(payload.get("file_name") or "").strip():
            raise ValueError("请选择录音文件")
        request = dict(payload)
        request["learner_id"] = learner_id
        request["course_id"] = str(int(time.time() * 1000))
        job = self.store.create_course_import_job(learner_id, request)
        self._import_wakeup.set()
        return job

    def _run_import_worker(self) -> None:
        while True:
            job = self.store.claim_course_import_job()
            if not job:
                self._import_wakeup.wait(1.0)
                self._import_wakeup.clear()
                continue
            self._process_import_job(job)

    def _process_import_job(self, job: dict) -> None:
        job_id = str(job["job_id"])
        payload = dict(job.get("request") or {})
        learner_id = str(job["learner_id"])
        try:
            existing_course_id = str(payload.get("course_id") or "")
            if existing_course_id:
                try:
                    existing = self.courses.detail(learner_id, existing_course_id)
                    self.store.update_course_import_job(
                        job_id, state="completed", stage=3,
                        course_id=existing_course_id,
                        course_title=str(existing.get("title") or ""), error="",
                    )
                    return
                except KeyError:
                    pass
            seed = self.courses.demo_audio_payload(str(payload.get("file_name") or ""))
            if payload.get("subject"):
                seed["subject"] = str(payload["subject"])
            if payload.get("title"):
                seed["title"] = str(payload["title"])
            generated, generation_mode = self.ai.generate_demo_course(
                seed,
                duration_range=str(payload.get("duration_range") or "under_5"),
                speaker_mode=str(payload.get("speaker_mode") or "2"),
            )
            self.store.update_course_import_job(job_id, state="saving", stage=2)
            course = self.courses.import_course(learner_id, {
                **seed,
                **generated,
                "course_id": str(payload.get("course_id") or ""),
                "generation_mode": generation_mode,
            })
            self.store.add_event(
                learner_id, course.get("course_id", ""), "course_added",
                f"课程《{course.get('title','未命名课程')}》已整理",
                "课程文字与摘要已经进入课程档案，可以继续复盘。",
                {"generation_mode": generation_mode},
            )
            self.store.update_course_import_job(
                job_id,
                state="completed",
                stage=3,
                course_id=str(course.get("course_id") or ""),
                course_title=str(course.get("title") or ""),
                error="",
            )
        except Exception as exc:
            traceback.print_exc()
            self.store.update_course_import_job(job_id, state="failed", error=str(exc))


APP = PlatformApp()


class Handler(BaseHTTPRequestHandler):
    server_version = "ZhiyunKeji/0.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    def json_response(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 4_000_000:
            raise ValueError("请求体长度必须在 1 到 4000000 字节之间")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = unquote(split.path)
        query = parse_qs(split.query)
        if path.startswith("/api/"):
            self.handle_api_get(path, query)
            return
        self.serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = unquote(split.path)
        if not path.startswith("/api/"):
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            payload = self.read_json()
            self.handle_api_post(path, payload)
        except (ValueError, KeyError, PermissionError) as exc:
            self.json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        split = urlsplit(self.path)
        path = unquote(split.path)
        query = parse_qs(split.query)
        try:
            run_match = re.fullmatch(r"/api/teleagent/runs/([^/]+)", path)
            if run_match:
                learner_id = APP.learner_id(query)
                deleted = APP.store.delete_open_run(learner_id, run_match.group(1))
                APP.memory.delete_vectors(deleted.pop("vector_ids", []))
                self.json_response(HTTPStatus.OK, deleted)
                return
            match = re.fullmatch(r"/api/courses/([^/]+)", path)
            if not match:
                self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            learner_id = APP.learner_id(query)
            deleted = APP.courses.delete_course(learner_id, match.group(1))
            APP.memory.delete_vectors(deleted.pop("vector_ids", []))
            self.json_response(HTTPStatus.OK, deleted)
        except (ValueError, KeyError, PermissionError) as exc:
            self.json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/health":
                teleagent_health = APP.teleagent.health()
                self.json_response(HTTPStatus.OK, {
                    "status": "ok", "service": "zhiyun-keji-platform",
                    "mysql_configured": APP.courses.mysql_configured,
                    "ai_configured": bool(APP.ai.api_key),
                    "teleagent_configured": bool(teleagent_health.get("ready")),
                    "teleagent": teleagent_health,
                    "memory": APP.memory.health(),
                })
                return
            if path == "/api/learners":
                self.json_response(HTTPStatus.OK, {"items": APP.courses.learners()})
                return
            learner_id = APP.learner_id(query)
            if path == "/api/bootstrap":
                self.json_response(HTTPStatus.OK, APP.bootstrap(learner_id))
                return
            if path == "/api/courses":
                self.json_response(HTTPStatus.OK, {"items": APP.courses.courses(learner_id)})
                return
            import_job_match = re.fullmatch(r"/api/courses/import-jobs/([^/]+)", path)
            if import_job_match:
                job = APP.store.course_import_job(import_job_match.group(1), learner_id)
                if not job:
                    raise KeyError("导入任务不存在")
                self.json_response(HTTPStatus.OK, job)
                return
            course_match = re.fullmatch(r"/api/courses/([^/]+)", path)
            if course_match:
                self.json_response(HTTPStatus.OK, APP.courses.detail(learner_id, course_match.group(1)))
                return
            relation_match = re.fullmatch(r"/api/courses/([^/]+)/relations", path)
            if relation_match:
                course_id = relation_match.group(1)
                course = APP.courses.detail(learner_id, course_id)
                links, mode = APP.ai.course_relations(course, APP.courses.courses(learner_id))
                self.json_response(HTTPStatus.OK, {"payload": links, "mode": mode})
                return
            run_match = re.fullmatch(r"/api/teleagent/runs/([^/]+)", path)
            if run_match:
                self.json_response(HTTPStatus.OK, APP.teleagent.refresh(run_match.group(1)))
                return
            if path == "/api/teleagent/runs":
                self.json_response(HTTPStatus.OK, {"items": APP.store.recent_runs(learner_id, 30)})
                return
            if path == "/api/growth":
                data = APP.store.growth(learner_id)
                data["dialogue_insights"] = APP.store.dialogue_insights(learner_id)
                data["learning_memories"] = APP.store.recent_learning_memories(learner_id, 30)
                data["memory_health"] = APP.memory.health()
                data["course_count"] = len(APP.courses.courses(learner_id))
                data["interaction_count"] = len([run for run in APP.store.recent_runs(learner_id, 100) if run["state"] == "completed"])
                self.json_response(HTTPStatus.OK, data)
                return
            if path == "/api/ai/archive-chat":
                self.json_response(HTTPStatus.OK, {"items": APP.store.archive_chat(learner_id)})
                return
            if path == "/api/internal/learning-context":
                expected = APP.write_token
                supplied = self.headers.get("X-Platform-Token", "")
                if expected and supplied != expected:
                    self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "invalid platform token"})
                    return
                phone = str((query.get("phone") or [""])[0]).strip()
                learner = APP.courses.learner_by_phone(phone)
                if not learner:
                    raise KeyError("学习者不存在")
                requested = str((query.get("query") or ["最近学习重点"])[0])[:500]
                top_k = max(1, min(10, int((query.get("top_k") or ["6"])[0])))
                memories = APP.memory.search(str(learner["learner_id"]), requested, top_k)
                growth = APP.store.growth(str(learner["learner_id"]))
                memory_health = APP.memory.health()
                self.json_response(HTTPStatus.OK, {
                    "learner": {"display_name": learner.get("display_name"), "grade": learner.get("grade")},
                    "query": requested,
                    "memories": memories,
                    "knowledge_states": growth.get("mastery", [])[:10],
                    "memory_retrieval": {
                        "returned": len(memories),
                        "vector_ready": bool(memory_health.get("ready")),
                        "collection": memory_health.get("collection", ""),
                        "learner_isolated": True,
                    },
                    "boundary": "这些内容来自平台可追溯学习档案，不等同于人格判断。",
                })
                return
            self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except KeyError as exc:
            self.json_response(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self.json_response(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def handle_api_post(self, path: str, payload: dict) -> None:
        if path == "/api/courses/import":
            learner_id = str(payload.get("learner_id") or "")
            if not learner_id:
                raise ValueError("learner_id is required")
            course = APP.courses.import_course(learner_id, payload)
            APP.store.add_event(learner_id, course.get("course_id", ""), "course_added",
                                f"新增课程《{course.get('title','未命名课程')}》", "课程内容已进入平台。")
            self.json_response(HTTPStatus.CREATED, course)
            return
        if path == "/api/courses/import-audio-demo":
            learner_id = str(payload.get("learner_id") or "")
            if not learner_id:
                raise ValueError("learner_id is required")
            job = APP.create_import_job(learner_id, payload)
            self.json_response(HTTPStatus.ACCEPTED, job)
            return
        review_match = re.fullmatch(r"/api/courses/([^/]+)/review", path)
        if review_match:
            learner_id = str(payload.get("learner_id") or "")
            course_id = review_match.group(1)
            if not learner_id:
                raise ValueError("learner_id is required")
            cached = APP.store.get_review(learner_id, course_id)
            if cached and not payload.get("force"):
                self.json_response(HTTPStatus.OK, cached)
                return
            course = APP.courses.detail(learner_id, course_id)
            review, mode = APP.ai.review(course)
            APP.store.save_review(learner_id, course_id, review, mode)
            APP.store.add_event(learner_id, course_id, "course_reviewed",
                                f"完成《{course['title']}》AI 复盘", "已生成课程主线、知识点和下一步。",
                                {"mode": mode})
            for point in review.get("knowledge_points", []):
                name = str(point.get("name") or "").strip()
                if name:
                    APP.store.upsert_mastery(learner_id, name, True, "课程中已接触，尚待独立作答验证")
            self.json_response(HTTPStatus.OK, {"payload": review, "mode": mode})
            return
        if path == "/api/teleagent/runs":
            run = APP.teleagent.create(payload)
            self.json_response(HTTPStatus.CREATED, run)
            return
        if path == "/api/teleagent/focus":
            self.json_response(HTTPStatus.OK, APP.teleagent.focus())
            return
        start_match = re.fullmatch(r"/api/teleagent/runs/([^/]+)/start", path)
        if start_match:
            run = APP.store.get_run(start_match.group(1))
            if not run:
                raise KeyError("学习互动不存在")
            if run.get("state") not in {"completed", "processing_result"}:
                run = APP.store.update_run(run["run_id"], state="running", error="") or run
                APP.store.add_event(
                    run["learner_id"], run.get("course_id", ""), "teleagent_started",
                    f"开始与 TeleAgent 探讨《{run.get('course_title','本课')}》",
                    "本次探讨正在进行，结束后可回流到学习档案。",
                    {"run_id": run["run_id"]},
                )
            self.json_response(HTTPStatus.OK, run)
            return
        if path == "/api/internal/learning-results":
            expected = APP.write_token
            supplied = self.headers.get("X-Platform-Token", "")
            if expected and supplied != expected:
                self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "invalid platform token"})
                return
            run_id = str(payload.get("run_id") or "")
            if not run_id:
                raise ValueError("run_id is required")
            run = APP.store.get_run(run_id)
            if not run:
                raise KeyError("TeleAgent task not found")
            phone = str(payload.get("phone") or "")
            if run.get("phone") and phone and run["phone"] != phone:
                raise PermissionError("learning result does not belong to this learner")
            course_id = str(payload.get("course_id") or "")
            if run.get("course_id") and course_id != str(run["course_id"]):
                raise PermissionError("learning result course does not match the TeleAgent task")
            action = str(payload.get("action") or run.get("action") or "")
            if action != str(run.get("action") or ""):
                raise PermissionError("learning result action does not match the TeleAgent task")
            self.json_response(HTTPStatus.OK, APP.store.apply_learning_result(run_id, payload))
            return
        if path == "/api/internal/learning-interactions":
            expected = APP.write_token
            supplied = self.headers.get("X-Platform-Token", "")
            if expected and supplied != expected:
                self.json_response(HTTPStatus.UNAUTHORIZED, {"error": "invalid platform token"})
                return
            run_id = str(payload.get("run_id") or "")
            if not run_id:
                raise ValueError("run_id is required")
            run = APP.store.get_run(run_id)
            if not run:
                raise KeyError("TeleAgent task not found")
            phone = str(payload.get("phone") or "")
            if run.get("phone") and phone and run["phone"] != phone:
                raise PermissionError("learning interaction does not belong to this learner")
            course_id = str(payload.get("course_id") or "")
            if course_id != str(run.get("course_id") or ""):
                raise PermissionError("learning interaction course does not match the task")
            if str(payload.get("action") or "") != str(run.get("action") or ""):
                raise PermissionError("learning interaction action does not match the task")
            existing = APP.store.dialogue_insights(run["learner_id"], run_id=run_id)
            if existing:
                memories = APP.store.memories_for_run(run_id)
                pending = [item for item in memories if item.get("vector_status") != "indexed"]
                index_result = APP.memory.index_memories(pending) if pending else {
                    "indexed": 0, "ready": APP.memory.health().get("ready", False), "error": ""
                }
                self.json_response(HTTPStatus.OK, {
                    "run": run, "insights": existing,
                    "memories": APP.store.memories_for_run(run_id),
                    "memory_index": index_result, "idempotent": True,
                })
                return
            turns = [item for item in (payload.get("dialogue_turns") or []) if isinstance(item, dict)]
            roles = {str(item.get("role") or "").lower() for item in turns}
            if run.get("action") in {"course_review", "learning_check"} and (
                not roles.intersection({"student", "user"})
                or not roles.intersection({"assistant", "teleagent", "teacher"})
            ):
                raise ValueError("课程复盘/学习检测必须包含学生原话和 TeleAgent 提示或回答")
            APP.store.save_dialogue_turns(run, turns)
            APP.store.update_run(run_id, state="processing_result", error="")
            learner = APP.courses.learner(run["learner_id"])
            course = APP.courses.detail(run["learner_id"], course_id)
            retrieval_query = " ".join([
                run.get("focus", ""), str(payload.get("summary") or ""),
                " ".join(str(item.get("content") or "") for item in turns if item.get("role") in {"student", "user"}),
            ])[:2000]
            related = APP.memory.search(run["learner_id"], retrieval_query, 6)
            analysis, mode = APP.ai.analyze_learning_dialogue(
                learner, course, turns, related, str(payload.get("summary") or "")
            )
            episode_summary = str(analysis.get("episode_summary") or "").strip()
            if not episode_summary:
                raise ValueError("平台 AI 未返回本次对话摘要")
            saved = APP.store.save_dialogue_analysis(run, analysis)
            index_result = APP.memory.index_memories(saved["memories"])
            changes = []
            plans = []
            for update in (analysis.get("knowledge_updates") or [])[:12]:
                if not isinstance(update, dict):
                    raise ValueError("平台 AI 返回了无效的知识状态更新")
                change = APP.store.update_mastery_from_dialogue(run["learner_id"], update)
                if change:
                    changes.append(change)
            for item in (analysis.get("next_actions") or [])[:3]:
                if not isinstance(item, dict):
                    raise ValueError("平台 AI 返回了无效的下一步建议")
                required = ("knowledge_point", "title", "reason")
                missing = [key for key in required if not item.get(key)]
                if missing:
                    raise ValueError(f"平台 AI 下一步建议缺少字段：{', '.join(missing)}")
                kp = str(item["knowledge_point"])
                plans.append(APP.store.add_plan(
                    run["learner_id"], kp, str(item["title"]),
                    str(item["reason"]), 8, run_id,
                ))
            enriched = {
                "summary": episode_summary,
                "analysis": analysis, "analysis_mode": mode, "changes": changes,
                "plans": plans, "memory_index": index_result,
            }
            APP.store.update_run(run_id, state="completed", result_json=enriched, error="")
            APP.store.add_event(
                run["learner_id"], course_id, "dialogue_analyzed",
                "平台 AI 已提炼本次 TeleAgent 学习对话",
                episode_summary,
                {"run_id": run_id, "insight_count": len(saved["insights"]), "mode": mode},
            )
            self.json_response(HTTPStatus.OK, {
                "run": APP.store.get_run(run_id), "insights": saved["insights"],
                "memories": saved["memories"], "changes": changes, "plans": plans,
                "memory_index": index_result, "idempotent": False,
            })
            return
        if path == "/api/growth/refresh":
            learner_id = str(payload.get("learner_id") or "")
            learner = APP.courses.learner(learner_id)
            growth = APP.store.growth(learner_id)
            course_count = len(APP.courses.courses(learner_id))
            run_count = len([run for run in APP.store.recent_runs(learner_id, 100) if run["state"] == "completed"])
            summary, mode = APP.ai.growth_summary(learner, growth, course_count, run_count)
            APP.store.save_growth_summary(learner_id, summary, mode)
            self.json_response(HTTPStatus.OK, {"payload": summary, "mode": mode})
            return
        if path == "/api/growth/plans/generate":
            learner_id = str(payload.get("learner_id") or "")
            learner = APP.courses.learner(learner_id)
            growth = APP.store.growth(learner_id)
            courses = APP.courses.courses(learner_id)
            run_count = len([run for run in APP.store.recent_runs(learner_id, 100) if run["state"] == "completed"])
            summary, mode = APP.ai.growth_summary(learner, growth, len(courses), run_count)
            APP.store.save_growth_summary(learner_id, summary, mode)
            recommendation = summary.get("recommended_plan")
            if not isinstance(recommendation, dict):
                raise ValueError("平台 AI 未返回可用的学习计划")
            required = ("knowledge_point", "title", "reason", "minutes")
            missing = [key for key in required if not recommendation.get(key)]
            if missing:
                raise ValueError(f"平台 AI 学习计划缺少字段：{', '.join(missing)}")
            knowledge_point = str(recommendation["knowledge_point"])
            plan = APP.store.add_plan(
                learner_id, knowledge_point,
                str(recommendation["title"]),
                str(recommendation["reason"]),
                max(3, min(30, int(recommendation["minutes"]))), "platform-ai",
            )
            APP.store.add_event(
                learner_id, "", "platform_plan_created", f"平台 AI 生成计划：{plan.get('title','')}",
                plan.get("reason", ""), {"plan_id": plan.get("plan_id"), "mode": mode},
            )
            self.json_response(HTTPStatus.OK, {"plan": plan, "analysis": summary, "mode": mode})
            return
        if path == "/api/ai/archive-query":
            learner_id = str(payload.get("learner_id") or "")
            question = str(payload.get("question") or "").strip()[:500]
            if not learner_id or not question:
                raise ValueError("learner_id and question are required")
            learner = APP.courses.learner(learner_id)
            APP.store.add_archive_chat_message(learner_id, "user", question)
            growth = APP.store.growth(learner_id)
            memories = APP.memory.search(learner_id, question, 8)
            answer, mode = APP.ai.answer_learning_archive(
                learner, question, memories, growth.get("mastery", []), growth.get("events", [])
            )
            referenced = set(answer.get("evidence_refs") or [])
            evidence = [item for item in memories if item.get("memory_id") in referenced]
            evidence.extend({
                "title": f"知识状态 · {item.get('knowledge_point', '')}",
                "knowledge_point": item.get("knowledge_point", ""),
                "content": item.get("last_reason", ""),
                "source_run_id": "",
            } for item in growth.get("mastery", [])
                if f"knowledge:{item.get('knowledge_point', '')}" in referenced)
            evidence.extend({
                "title": item.get("title", "学习事件"),
                "content": item.get("description", ""),
                "source_run_id": (item.get("evidence") or {}).get("run_id", ""),
            } for item in growth.get("events", [])
                if f"event:{item.get('event_id', '')}" in referenced)
            if not evidence:
                answer_text = str(answer.get("answer") or "")
                evidence.extend({
                    "title": f"知识状态 · {item.get('knowledge_point', '')}",
                    "knowledge_point": item.get("knowledge_point", ""),
                    "content": item.get("last_reason", ""),
                    "source_run_id": "",
                } for item in growth.get("mastery", [])
                    if item.get("knowledge_point") and item["knowledge_point"] in answer_text)
                evidence.extend(item for item in memories
                    if (item.get("knowledge_point") and item["knowledge_point"] in answer_text)
                    or (item.get("title") and item["title"] in answer_text))
            answer["evidence"] = evidence[:5]
            answer["retrieval_meta"] = {
                "memory_count": len(memories),
                "knowledge_state_count": len(growth.get("mastery", [])),
                "course_count": len(APP.courses.courses(learner_id)),
            }
            APP.store.add_archive_chat_message(
                learner_id, "assistant", str(answer.get("answer") or ""), answer["evidence"]
            )
            self.json_response(HTTPStatus.OK, {"payload": answer, "mode": mode})
            return
        if path == "/api/ai/archive-chat/clear":
            learner_id = str(payload.get("learner_id") or "").strip()
            if not learner_id:
                raise ValueError("learner_id is required")
            APP.courses.learner(learner_id)
            deleted = APP.store.clear_archive_chat(learner_id)
            self.json_response(HTTPStatus.OK, {"cleared": True, "deleted": deleted})
            return
        complete_match = re.fullmatch(r"/api/growth/plans/([^/]+)/complete", path)
        if complete_match:
            learner_id = str(payload.get("learner_id") or "")
            plan = APP.store.complete_plan(learner_id, complete_match.group(1), str(payload.get("reflection") or ""))
            self.json_response(HTTPStatus.OK, {"plan": plan})
            return
        self.json_response(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = ROOT / "zhiyun-keji-prototype.html"
        else:
            relative = path.lstrip("/")
            file_path = (ROOT / relative).resolve()
            try:
                file_path.relative_to(ROOT)
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Cache-Control", "no-store" if file_path.suffix in {".html", ".js", ".css"} else "public, max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="智云课迹本地平台服务")
    parser.add_argument("--host", default=os.environ.get("PLATFORM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PLATFORM_PORT", "18910")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"智云课迹：http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
