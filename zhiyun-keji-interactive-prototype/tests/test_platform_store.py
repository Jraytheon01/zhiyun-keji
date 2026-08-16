from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_services import CourseRepository
from platform_store import PlatformStore


class PlatformStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = PlatformStore(Path(self.temp.name) / "test.sqlite3")
        self.store.upsert_local_learner({
            "learner_id": "1001", "phone": "13800001001",
            "display_name": "测试学生甲", "grade": "初二", "subject": "数学",
        })
        self.store.upsert_local_learner({
            "learner_id": "1002", "phone": "13800001002",
            "display_name": "测试学生乙", "grade": "初一", "subject": "数学",
        })
        self.store.insert_local_course("1001", {
            "course_id": "990101", "title": "测试课程甲", "summary": "测试摘要甲",
            "segments": [{"speaker": "说话人1", "content": "测试内容甲"}],
        })
        self.store.insert_local_course("1001", {
            "course_id": "990102", "title": "测试课程乙", "summary": "测试摘要乙",
            "segments": [{"speaker": "说话人1", "content": "测试内容乙"}],
        })
        self.store.insert_local_course("1002", {
            "course_id": "990201", "title": "测试课程丙", "summary": "测试摘要丙",
            "segments": [{"speaker": "说话人1", "content": "测试内容丙"}],
        })

    def tearDown(self):
        self.temp.cleanup()

    def test_courses_are_isolated_by_learner_without_login_layer(self):
        lin = {item["course_id"] for item in self.store.local_courses("1001")}
        yu = {item["course_id"] for item in self.store.local_courses("1002")}
        self.assertEqual(lin, {"990101", "990102"})
        self.assertEqual(yu, {"990201"})
        self.assertFalse(lin & yu)

    def test_course_import_job_is_durable_and_claimed_once(self):
        created = self.store.create_course_import_job("1001", {
            "file_name": "圆周运动.mp3", "duration_range": "under_5", "speaker_mode": "2",
        })
        self.assertEqual(created["state"], "queued")
        claimed = self.store.claim_course_import_job()
        self.assertEqual(claimed["job_id"], created["job_id"])
        self.assertEqual(claimed["state"], "generating")
        self.assertIsNone(self.store.claim_course_import_job())
        completed = self.store.update_course_import_job(
            created["job_id"], state="completed", stage=3,
            course_id="990101", course_title="圆周运动",
        )
        self.assertEqual(completed["course_id"], "990101")
        self.assertEqual(completed["stage"], 3)

    def test_delete_course_removes_only_selected_course_data(self):
        repository = CourseRepository(self.store)
        deleted = repository.delete_course("1001", "990101")
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(self.store.local_course("1001", "990101"))
        self.assertIsNotNone(self.store.local_course("1001", "990102"))
        self.assertIsNotNone(self.store.local_course("1002", "990201"))

    def test_mysql_course_does_not_change_platform_learner_id(self):
        repository = CourseRepository(self.store)
        repository.host = "mysql"
        repository.user = "test"
        repository.database = "zhiyun_learning"
        with patch.object(repository, "_mysql_learners", return_value=[{
            "learner_id": "1001-1001", "user_id": 1001,
            "phone": "13800001001", "display_name": "derived",
            "grade": "", "subject": "", "source": "mysql",
        }]):
            learner = repository.learner("1001")
        self.assertEqual("1001", learner["learner_id"])
        self.assertEqual("测试学生甲", learner["display_name"])

    def test_physics_topic_overrides_an_inaccurate_default_subject(self):
        repository = CourseRepository(self.store)
        self.assertEqual("物理", repository._infer_subject("圆周运动：向心力来源与竖直面绳杆模型"))

    def test_learning_result_is_idempotent_and_creates_evidence(self):
        run = self.store.create_run({
            "run_id": "zyk_test_run", "learner_id": "1001", "phone": "13800001001",
            "course_id": "990101", "course_title": "一次函数图像的平移",
            "action": "learning_check", "focus": "左右平移方向", "parameters": {},
            "prompt": "test", "state": "sent",
        })
        self.assertEqual(run["state"], "sent")
        result = {
            "summary": "完成两题",
            "questions": [
                {"knowledge_point": "左右平移方向", "correct": True},
                {"knowledge_point": "左右平移方向", "correct": False},
            ],
        }
        first = self.store.apply_learning_result("zyk_test_run", result)
        second = self.store.apply_learning_result("zyk_test_run", result)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        growth = self.store.growth("1001")
        self.assertEqual(len(growth["plans"]), 1)
        self.assertEqual(growth["mastery"][0]["evidence_count"], 1)
        self.assertEqual(growth["mastery"][0]["level"], "待巩固")

    def test_learning_events_do_not_leak_to_other_learner(self):
        self.store.add_event("1001", "990101", "course_reviewed", "完成课程复盘")
        self.assertEqual(len(self.store.growth("1001")["events"]), 1)
        self.assertEqual(len(self.store.growth("1002")["events"]), 0)

    def test_clearing_archive_chat_keeps_other_learner_history(self):
        self.store.add_archive_chat_message("1001", "user", "我的问题")
        self.store.add_archive_chat_message("1001", "assistant", "学习建议")
        self.store.add_archive_chat_message("1002", "user", "另一位学习者的问题")
        self.assertEqual(self.store.clear_archive_chat("1001"), 2)
        self.assertEqual(self.store.archive_chat("1001"), [])
        self.assertEqual(len(self.store.archive_chat("1002")), 1)


    def test_teleagent_session_id_is_persisted_for_visible_handoff(self):
        self.store.create_run({
            "run_id": "zyk_session_run", "learner_id": "1001", "phone": "13800001001",
            "course_id": "990101", "course_title": "course", "action": "course_review",
            "focus": "focus", "parameters": {}, "prompt": "test", "state": "running",
        })
        run = self.store.update_run(
            "zyk_session_run", bridge_event_id="zyk_session_run",
            bridge_session_id="ses_visible_123",
        )
        self.assertEqual(run["bridge_session_id"], "ses_visible_123")

    def test_delete_open_run_is_scoped_and_preserves_course(self):
        self.store.create_run({
            "run_id": "zyk_open_run", "learner_id": "1001", "phone": "13800001001",
            "course_id": "990101", "course_title": "course", "action": "course_review",
            "focus": "focus", "parameters": {}, "prompt": "test", "state": "running",
        })
        deleted = self.store.delete_open_run("1001", "zyk_open_run")
        self.assertTrue(deleted["deleted"])
        self.assertIsNone(self.store.get_run("zyk_open_run"))
        self.assertIsNotNone(self.store.local_course("1001", "990101"))

    def test_delete_open_run_rejects_completed_record(self):
        self.store.create_run({
            "run_id": "zyk_completed_run", "learner_id": "1001", "phone": "13800001001",
            "course_id": "990101", "course_title": "course", "action": "learning_check",
            "focus": "focus", "parameters": {}, "prompt": "test", "state": "completed",
        })
        with self.assertRaises(ValueError):
            self.store.delete_open_run("1001", "zyk_completed_run")
        self.assertIsNotNone(self.store.get_run("zyk_completed_run"))

    def test_completing_plan_records_reflection_without_changing_mastery(self):
        self.store.upsert_mastery("1001", "左右平移方向", False, "客观作答证据")
        before = self.store.growth("1001")["mastery"][0]
        plan = self.store.add_plan(
            "1001", "左右平移方向", "关键点验证练习", "错题证据", 10, "zyk_source"
        )
        completed = self.store.complete_plan("1001", plan["plan_id"], "完成后仍需复测")
        after = self.store.growth("1001")["mastery"][0]
        self.assertEqual(completed["status"], "done")
        self.assertEqual(before["level"], after["level"])
        self.assertEqual(before["evidence_count"], after["evidence_count"])
        growth = self.store.growth("1001")
        self.assertTrue(any(item["memory_type"] == "plan_reflection" for item in growth["memories"]))

    def test_repeated_memory_keeps_each_run_as_evidence(self):
        analysis = {"insights": [], "memory_candidates": [{
            "memory_type": "semantic", "title": "因式分解需写两个根",
            "content": "能在提示后意识到两个因式需要分别等于零。",
            "knowledge_point": "因式分解法", "confidence": 0.72,
            "evidence_turn_indexes": [1, 2],
        }]}
        first_run = {"run_id": "run_one", "learner_id": "1001", "course_id": "990101"}
        second_run = {"run_id": "run_two", "learner_id": "1001", "course_id": "990102"}
        self.store.save_dialogue_analysis(first_run, analysis)
        self.store.save_dialogue_analysis(second_run, analysis)
        memories = self.store.recent_learning_memories("1001")
        memory = next(item for item in memories if item["knowledge_point"] == "因式分解法")
        self.assertEqual(memory["evidence_count"], 2)
        self.assertEqual({item["run_id"] for item in memory["evidence_sources"]}, {"run_one", "run_two"})
        self.assertEqual(memory["status"], "active")


if __name__ == "__main__":
    unittest.main()
