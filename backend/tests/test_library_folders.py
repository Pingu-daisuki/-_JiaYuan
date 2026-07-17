import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest import mock

from fastapi import HTTPException


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from routes import library, rag


class NestedFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, "library.db")
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_name TEXT NOT NULL,
                    parent_id INTEGER DEFAULT NULL
                );
                CREATE TABLE knowledge_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_name TEXT NOT NULL,
                    course_id INTEGER DEFAULT NULL,
                    updated_at TEXT DEFAULT NULL
                );
                INSERT INTO knowledge_files (file_name) VALUES ('nested.pdf');
                """
            )
            connection.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def test_creates_child_and_moves_file_into_it(self):
        with mock.patch.object(library, "get_db_connection", side_effect=self.connect):
            parent = library.create_folder(library.CourseCreate(course_name="父目录", parent_id=0))
            child = library.create_folder(
                library.CourseCreate(course_name="子目录", parent_id=parent["id"])
            )
            with mock.patch.object(library, "_sync_file_course_metadata") as sync_vectors:
                result = library.move_file(1, library.MoveFileReq(course_id=child["id"]))

        with closing(self.connect()) as connection:
            stored_course_id = connection.execute(
                "SELECT course_id FROM knowledge_files WHERE id = 1"
            ).fetchone()["course_id"]

        self.assertEqual(child["parent_id"], parent["id"])
        self.assertEqual(result["course_id"], child["id"])
        self.assertEqual(stored_course_id, child["id"])
        sync_vectors.assert_called_once_with(1, child["id"])

    def test_rejects_missing_target_folder(self):
        with (
            mock.patch.object(library, "get_db_connection", side_effect=self.connect),
            mock.patch.object(library, "_sync_file_course_metadata") as sync_vectors,
        ):
            with self.assertRaises(HTTPException) as raised:
                library.move_file(1, library.MoveFileReq(course_id=999))

        self.assertEqual(raised.exception.status_code, 404)
        sync_vectors.assert_not_called()

    def test_duplicate_import_moves_existing_file_to_requested_child(self):
        with closing(self.connect()) as connection:
            parent_id = connection.execute(
                "INSERT INTO courses (course_name) VALUES ('父目录')"
            ).lastrowid
            child_id = connection.execute(
                "INSERT INTO courses (course_name, parent_id) VALUES ('子目录', ?)",
                (parent_id,),
            ).lastrowid
            connection.commit()

        record = {"id": 1, "course_id": None, "file_name": "nested.pdf"}
        with (
            mock.patch.object(rag, "get_db_connection", side_effect=self.connect),
            mock.patch.object(rag, "update_vector_course_metadata") as sync_vectors,
        ):
            moved = rag._move_reused_file_to_course(record, child_id)

        with closing(self.connect()) as connection:
            stored_course_id = connection.execute(
                "SELECT course_id FROM knowledge_files WHERE id = 1"
            ).fetchone()["course_id"]

        self.assertEqual(moved["course_id"], child_id)
        self.assertEqual(stored_course_id, child_id)
        sync_vectors.assert_called_once_with(1, child_id)


if __name__ == "__main__":
    unittest.main()
