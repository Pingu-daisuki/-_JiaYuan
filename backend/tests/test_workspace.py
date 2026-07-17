import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core import db, tasks
from routes import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "workspace.db")
        self.db_path_patch = mock.patch.object(db, "DB_PATH", self.database_path)
        self.db_path_patch.start()
        db.init_db()

        def connect():
            connection = sqlite3.connect(self.database_path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        self.workspace_connection = mock.patch.object(workspace, "get_db_connection", side_effect=connect)
        self.task_connection = mock.patch.object(tasks, "get_db_connection", side_effect=connect)
        self.workspace_connection.start()
        self.task_connection.start()

    def tearDown(self):
        self.task_connection.stop()
        self.workspace_connection.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_conversation_messages_scope_and_markdown_export(self):
        conversation = workspace.create_conversation(workspace.ConversationCreate(
            title="高数复习", retrieval_scope={"mode": "files", "file_ids": [3, 5]},
        ))
        user = workspace.create_message(conversation["id"], workspace.MessageCreate(role="user", content="解释极限"))
        assistant = workspace.create_message(conversation["id"], workspace.MessageCreate(
            role="assistant", content="极限描述趋近过程。", sources=[{"file_name": "lecture.pdf"}],
        ))

        loaded = workspace.get_conversation(conversation["id"])
        self.assertEqual([user["id"], assistant["id"]], [item["id"] for item in loaded["messages"]])
        self.assertEqual({"mode": "files", "file_ids": [3, 5]}, loaded["conversation"]["retrieval_scope"])
        exported = workspace.export_conversation(conversation["id"])
        self.assertIn("# 高数复习", exported)
        self.assertIn("lecture.pdf", exported)

    def test_dashboard_reports_failed_documents_and_tasks(self):
        with closing(workspace.get_db_connection()) as connection:
            connection.execute(
                "INSERT INTO knowledge_files (file_name,file_path,status,error_message) VALUES ('bad.pdf','missing.pdf','failed','OCR 失败')"
            )
            connection.commit()
        tasks.ensure_task_table()
        task_id = tasks.create_task("document_ingestion", "失败文档", retryable=True)
        tasks.update_task(task_id, status="failed", message="解析失败")
        health = {"healthy": False, "stats": {}, "issues": [{"message": "源文件缺失"}]}
        with mock.patch.object(workspace, "run_data_check", return_value=health):
            result = workspace.dashboard()
        self.assertEqual("failed", result["documents"][0]["status"])
        self.assertEqual(1, result["task_summary"]["failed"])
        self.assertEqual(1, result["task_summary"]["retryable"])


if __name__ == "__main__":
    unittest.main()
