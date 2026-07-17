import sqlite3
import tempfile
import unittest
from unittest import mock

from core import tasks


class BackgroundTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = f"{self.temp_dir.name}/tasks.db"

        def connect():
            conn = sqlite3.connect(self.database_path, timeout=30)
            conn.row_factory = sqlite3.Row
            return conn

        self.connection_patch = mock.patch.object(tasks, "get_db_connection", side_effect=connect)
        self.connection_patch.start()
        tasks._CANCEL_CALLBACKS.clear()
        tasks._CANCEL_EVENTS.clear()
        tasks._RETRY_HANDLERS.clear()
        tasks.ensure_task_table()

    def tearDown(self):
        tasks._CANCEL_CALLBACKS.clear()
        tasks._CANCEL_EVENTS.clear()
        tasks._RETRY_HANDLERS.clear()
        self.connection_patch.stop()
        self.temp_dir.cleanup()

    def test_task_stream_persists_progress_and_completion(self):
        task_id = tasks.create_task("document_ingestion", "测试入库", retryable=True)
        output = list(tasks.track_stream(task_id, iter(["[状态] uploaded → parsing\n", "[状态] indexing → ready\n"])))
        self.assertEqual(len(output), 2)
        task = tasks.get_task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 100)
        self.assertIn("ready", task["log_text"])

    def test_cancel_invokes_callback_and_stops_stream(self):
        task_id = tasks.create_task("engine_init", "测试取消")
        called = []
        tasks.register_cancel_callback(task_id, lambda: called.append(True))
        tasks.update_task(task_id, status="running")
        tasks.request_cancel(task_id)
        self.assertEqual(called, [True])
        self.assertEqual(list(tasks.track_stream(task_id, iter(["不应输出\n"]))), [])
        self.assertEqual(tasks.get_task(task_id)["status"], "cancelled")

    def test_running_tasks_are_recovered_as_interrupted(self):
        task_id = tasks.create_task("data_backup", "测试恢复", retryable=True)
        tasks.update_task(task_id, status="running")
        self.assertEqual(tasks.recover_interrupted_tasks(), 1)
        self.assertEqual(tasks.get_task(task_id)["status"], "interrupted")

    def test_retry_dispatches_persisted_payload(self):
        task_id = tasks.create_task("example", "测试重试", payload={"value": 7}, retryable=True)
        tasks.update_task(task_id, status="failed", message="失败")
        tasks.register_retry_handler("example", lambda payload: f"new-{payload['value']}")
        self.assertEqual(tasks.retry_task(task_id), "new-7")


if __name__ == "__main__":
    unittest.main()
