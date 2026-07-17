import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from unittest import mock

from core import maintenance


class DataMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = self.temp_dir.name
        self.paths = {
            "DATA_DIR": root,
            "DATABASE_PATH": os.path.join(root, "campus_assistant.db"),
            "BACKUP_DIR": os.path.join(root, "backups"),
            "UPLOAD_DIR": os.path.join(root, "uploads"),
            "VECTOR_DB_DIR": os.path.join(root, "vector_db"),
            "ENGINE_CONFIG_DIR": os.path.join(root, "engine_config"),
            "ENGINE_FLAG_DIR": os.path.join(root, "engine_flags"),
        }
        for path in self.paths.values():
            if not os.path.splitext(path)[1]:
                os.makedirs(path, exist_ok=True)
        self.patches = [mock.patch.object(maintenance, key, value) for key, value in self.paths.items()]
        for patcher in self.patches:
            patcher.start()
        maintenance.BACKUP_PARTS = {
            "uploads": self.paths["UPLOAD_DIR"],
            "vector_db": self.paths["VECTOR_DB_DIR"],
            "engine_config": self.paths["ENGINE_CONFIG_DIR"],
            "engine_flags": self.paths["ENGINE_FLAG_DIR"],
        }
        maintenance.PENDING_RESTORE_PATH = os.path.join(self.paths["BACKUP_DIR"], "pending-restore.json")
        maintenance.RESTORE_RESULT_PATH = os.path.join(self.paths["BACKUP_DIR"], "restore-result.json")
        with closing(sqlite3.connect(self.paths["DATABASE_PATH"])) as conn:
            conn.executescript(
                """
                CREATE TABLE courses (id INTEGER PRIMARY KEY, course_name TEXT, parent_id INTEGER);
                CREATE TABLE knowledge_files (
                    id INTEGER PRIMARY KEY, file_name TEXT, file_path TEXT,
                    status TEXT, chunk_count INTEGER
                );
                INSERT INTO knowledge_files VALUES (1, 'demo.pdf', 'uploads/demo.pdf', 'ready', 1);
                """
            )
        with open(os.path.join(self.paths["UPLOAD_DIR"], "demo.pdf"), "wb") as file:
            file.write(b"demo")

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_backup_contains_consistent_database_and_manifest(self):
        result = maintenance.create_backup("test")
        archive_path = maintenance.backup_path(result["name"])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("campus_assistant.db", archive.namelist())
            self.assertIn("uploads/demo.pdf", archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["format"], maintenance.BACKUP_FORMAT)

    def test_quick_check_reports_missing_source_file(self):
        os.remove(os.path.join(self.paths["UPLOAD_DIR"], "demo.pdf"))
        result = maintenance.run_data_check(False)
        self.assertFalse(result["healthy"])
        self.assertIn("missing_files", {issue["code"] for issue in result["issues"]})

    def test_restore_is_validated_and_applied_on_next_start(self):
        backup = maintenance.create_backup("restore")
        with closing(sqlite3.connect(self.paths["DATABASE_PATH"])) as conn:
            conn.execute("DELETE FROM knowledge_files")
            conn.commit()
        maintenance.queue_restore(backup["name"])
        result = maintenance.apply_pending_restore()
        self.assertIsNone(result["error"])
        with closing(sqlite3.connect(self.paths["DATABASE_PATH"])) as conn:
            count = conn.execute("SELECT COUNT(*) FROM knowledge_files").fetchone()[0]
        self.assertEqual(count, 1)

    def test_zip_path_traversal_is_rejected(self):
        archive_path = os.path.join(self.paths["BACKUP_DIR"], "bad.zip")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        with self.assertRaises(ValueError):
            maintenance.validate_and_store_backup(archive_path, "bad.zip")


if __name__ == "__main__":
    unittest.main()
