import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from platform_services import AIService, CourseRepository, TeleAgentService
from platform_store import PlatformStore


class FakeCourses:
    @staticmethod
    def learner(learner_id):
        return {"learner_id": learner_id, "display_name": "小林", "phone": "13900000000"}

    @staticmethod
    def detail(learner_id, course_id):
        return {"course_id": course_id, "title": "一次函数图像的平移"}


class TeleAgentPromptTest(unittest.TestCase):
    def test_prompt_requires_education_skill_and_fixed_ids(self):
        prompt = TeleAgentService._prompt(
            "zyk_run_123",
            {"display_name": "小林"},
            {"course_id": "990101", "title": "一次函数图像的平移"},
            "course_review",
            "左右平移方向",
            {},
        )
        self.assertIn("Skill：zhiyun-keji-learning", prompt)
        self.assertIn("course_id=990101", prompt)
        self.assertIn("run_id=zyk_run_123", prompt)
        self.assertIn("只使用 zhiyun-learning MCP", prompt)
        self.assertIn("结束复盘并回流课迹", prompt)
        self.assertIn("complete_learning_interaction", prompt)
        self.assertNotIn("meeting-assistant MCP 的", prompt)

    def test_dialogue_analysis_reports_ai_timeout_without_fabricating_results(self):
        service = AIService()
        service.api_key = "test-only"
        turns = [
            {"role": "student", "content": "我还是不懂左右平移。"},
            {"role": "assistant", "content": "先比较自变量发生了什么变化。"},
        ]
        with patch("platform_services.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "AI transport error"):
                service.analyze_learning_dialogue(
                    {"display_name": "小林"},
                    {"title": "一次函数", "segments": []},
                    turns,
                    [],
                    "完成了一次课程复盘",
                )

    def test_copy_delivery_prepares_prompt_without_calling_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            service = TeleAgentService(PlatformStore(Path(directory) / "test.db"), FakeCourses())
            with patch("platform_services.http_json") as http_json:
                run = service.create({
                    "learner_id": "student-1",
                    "course_id": "course-1",
                    "action": "course_review",
                    "delivery_mode": "copy",
                })
            http_json.assert_not_called()
        self.assertEqual("prompt_ready", run["state"])
        self.assertEqual("copy", run["delivery_mode"])
        self.assertIn(f"run_id={run['run_id']}", run["prompt"])
        self.assertIn("course_id=course-1", run["prompt"])

    def test_audio_demo_uses_filename_only_as_ai_generation_seed(self):
        payload = CourseRepository.demo_audio_payload("高三物理_楞次定律与电磁感应.m4a")
        self.assertEqual("物理", payload["subject"])
        self.assertIn("楞次定律", payload["title"])
        self.assertNotIn("transcript", payload)
        self.assertNotIn("summary", payload)
        self.assertEqual("audio_transcript", payload["source_type"])

    def test_audio_demo_ai_is_driven_by_duration_and_speaker_count(self):
        service = AIService()
        service.api_key = "test-only"
        natural_line = "嗯，我先按题目条件说一遍我的理解，然后再根据公式检查哪一步需要修正，这里我刚才确实漏了一个条件。" * 2
        turns = [
            {"speaker": f"说话人{1 + index % 3}", "content": natural_line}
            for index in range(18)
        ]
        with patch.object(service, "_chat_json", return_value={
            "title": "万有引力与卫星圆轨道关系课堂讲解",
            "summary": "课堂围绕引力提供向心力展开讲解。",
            "turns": turns,
        }) as model:
            generated, mode = service.generate_demo_course(
                {"title": "高中物理万有引力与航天", "subject": "物理"},
                duration_range="5_20",
                speaker_mode="3",
            )
        self.assertEqual("ai", mode)
        self.assertIn("说话人3：", generated["transcript"])
        prompt = model.call_args.args[0]
        self.assertIn("【录音时长】5—20 分钟", prompt)
        self.assertIn("【说话人数】3 人", prompt)
        self.assertIn("2160—2880", prompt)


if __name__ == "__main__":
    unittest.main()
