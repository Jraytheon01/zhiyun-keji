import importlib.util
import sqlite3
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
        payload = {"recording_id": "2", "completed_at": "2026-08-10T10:00:00+08:00"}
        self.assertEqual(MODULE.normalise_event(payload)["event_id"], MODULE.normalise_event(payload)["event_id"])

    def test_custom_learning_prompt_is_forwarded_unchanged(self):
        event = MODULE.normalise_event(
            {"event_id": "evt-1", "recording_id": "2", "prompt": "智云课迹课程复盘"}
        )
        self.assertEqual(MODULE.build_prompt(event, MODULE.ServiceConfig()), "智云课迹课程复盘")

    def test_new_session_is_enabled_by_default(self):
        self.assertTrue(MODULE.ServiceConfig().new_session_per_event)

    def test_focus_teleagent_is_enabled_by_default(self):
        self.assertTrue(MODULE.ServiceConfig().focus_teleagent_on_submit)

    def test_submit_leaves_session_creation_to_renderer(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            db = Path(directory) / "im-service.db"
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "CREATE TABLE im_channel_profile (channel TEXT PRIMARY KEY, enabled INTEGER, "
                    "auth_status TEXT, session_id TEXT)"
                )
                conn.execute("INSERT INTO im_channel_profile VALUES ('wecom',1,'unconfigured','ses_old')")
                conn.execute(
                    "CREATE TABLE im_message (id TEXT, channel TEXT, session_id TEXT, inbound_source TEXT, "
                    "inbound_text TEXT, inbound_external_message_id TEXT, inbound_sender_user_id TEXT, "
                    "inbound_sender_account_id TEXT, route_target TEXT, status TEXT, opencode_error TEXT, "
                    "submitted_at TEXT, outbound_text TEXT, file_paths TEXT, result_error TEXT, "
                    "result_completed_at TEXT, delivered_at TEXT, deliver_error TEXT, request_id TEXT, "
                    "extra TEXT, created_at TEXT, updated_at TEXT)"
                )
            bridge = MODULE.TeleAgentBridge.__new__(MODULE.TeleAgentBridge)
            bridge.config = MODULE.ServiceConfig(new_session_per_event=True, focus_teleagent_on_submit=False)
            bridge.im_db = db
            bridge.data_dir = Path(directory)
            bridge.submit("evt-new-session", "prompt", {"meeting_title": "课程"})
            with sqlite3.connect(db) as conn:
                profile_session = conn.execute(
                    "SELECT session_id FROM im_channel_profile WHERE channel='wecom'"
                ).fetchone()[0]
                message_session = conn.execute("SELECT session_id FROM im_message").fetchone()[0]
            self.assertEqual(profile_session, "")
            self.assertEqual(message_session, "")

    def test_job_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MODULE.JobStore(Path(directory) / "jobs.db")
            event = MODULE.normalise_event({"event_id": "evt-1", "recording_id": "2"})
            self.assertTrue(store.create(event, "prompt"))
            self.assertFalse(store.create(event, "prompt"))
            self.assertEqual(store.get("evt-1")["state"], "queued")
            self.assertEqual(store.fail_incomplete_after_restart(), 1)
            self.assertEqual(store.get("evt-1")["state"], "failed")


if __name__ == "__main__":
    unittest.main()
