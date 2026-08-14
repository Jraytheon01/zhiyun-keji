import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "auto_ppt_service.py"
SPEC = importlib.util.spec_from_file_location("auto_ppt_service", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class EventTests(unittest.TestCase):
    def test_normalise_event_generates_stable_id(self):
        payload = {
            "recording_id": "2",
            "completed_at": "2026-08-10T10:00:00+08:00",
        }
        first = MODULE.normalise_event(payload)
        second = MODULE.normalise_event(payload)
        self.assertEqual(first["event_id"], second["event_id"])

    def test_prompt_delegates_orchestration_to_skill(self):
        config = MODULE.ServiceConfig()
        event = MODULE.normalise_event(
            {"event_id": "evt-1", "recording_id": "2", "slides": 8}
        )
        prompt = MODULE.build_prompt(event, config)
        self.assertIn("Toby.AI录音卡助手", prompt)
        self.assertIn("最近一场会议", prompt)
        self.assertIn("可编辑 .pptx", prompt)
        self.assertIn("项目团队和管理层", prompt)
        self.assertIn("商务简约风格", prompt)
        self.assertIn("约8页", prompt)
        self.assertIn("不要向我提问或等待确认", prompt)
        self.assertIn("优先读取已有纪要", prompt)
        self.assertIn("纪要不可用时读取逐字稿", prompt)
        self.assertIn("直接返回可编辑PPT文件及其绝对路径", prompt)
        self.assertIn("无需额外展示缩略图、逐页视觉复核", prompt)
        self.assertNotIn("meeting-assistant", prompt)
        self.assertNotIn("ai-recorder-assistant", prompt)

    def test_display_bridge_forwards_structured_event_and_prompt(self):
        config = MODULE.ServiceConfig(
            display_bridge_url="http://display-pc.local:18767",
            display_bridge_trigger_delay_seconds=0,
        )
        client = MODULE.DisplayBridgeClient(config)
        captured = {}

        def fake_request(method, path, payload=None):
            captured.update(method=method, path=path, payload=payload)
            return {"event_id": payload["event_id"]}

        client._request = fake_request
        event = MODULE.normalise_event(
            {"event_id": "evt-forward", "recording_id": "meeting-2"}
        )
        message_id = client.submit(event, "built-in prompt")

        self.assertEqual(message_id, "evt-forward")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/events/recording-completed")
        self.assertEqual(captured["payload"]["recording_id"], "meeting-2")
        self.assertEqual(captured["payload"]["prompt"], "built-in prompt")

    def test_job_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MODULE.JobStore(Path(directory) / "jobs.db")
            event = MODULE.normalise_event(
                {"event_id": "evt-1", "recording_id": "2"}
            )
            self.assertTrue(store.create(event, "prompt"))
            self.assertFalse(store.create(event, "prompt"))
            self.assertEqual(store.get("evt-1")["state"], "queued")
            self.assertEqual(store.fail_incomplete_after_restart(), 1)
            self.assertEqual(store.get("evt-1")["state"], "failed")

    def test_failed_display_delivery_retries_independently(self):
        class FlakyDisplayBridge:
            def __init__(self):
                self.submits = 0

            def submit(self, event, prompt):
                self.submits += 1
                if self.submits == 1:
                    raise RuntimeError("temporary display connection failure")
                return event["event_id"]

            def wait(self, message_id):
                return {
                    "state": "completed",
                    "outbound_text": "PPT generated",
                    "file_paths": ["meeting.pptx"],
                }

        with tempfile.TemporaryDirectory() as directory:
            service = MODULE.AutoPptService(
                MODULE.ServiceConfig(
                    job_db=str(Path(directory) / "jobs.db"),
                    display_bridge_retries=1,
                    display_bridge_retry_delay_seconds=0,
                )
            )
            flaky = FlakyDisplayBridge()
            service.bridge = flaky
            service.submit({"event_id": "evt-retry", "use_latest": True})
            service.jobs.join()

            job = service.store.get("evt-retry")
            self.assertEqual(flaky.submits, 2)
            self.assertEqual(job["state"], "completed")
            self.assertEqual(job["attempts"], 2)
            self.assertEqual(job["file_paths"], ["meeting.pptx"])
            service.stop()


if __name__ == "__main__":
    unittest.main()
