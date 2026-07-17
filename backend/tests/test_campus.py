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

from routes import campus


class CampusSchemaMigrationTests(unittest.TestCase):
    def test_legacy_authenticated_account_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "campus.db")
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "CREATE TABLE campus_config (student_id TEXT PRIMARY KEY, password TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO campus_config (student_id, password) VALUES (?, ?)",
                    ("22920000000000", "secret"),
                )
                connection.commit()

            with mock.patch.object(
                campus,
                "get_db_connection",
                side_effect=lambda: sqlite3.connect(database_path),
            ):
                campus.ensure_campus_table()

            with closing(sqlite3.connect(database_path)) as connection:
                row = connection.execute(
                    "SELECT student_id, password, real_name, mode FROM campus_config"
                ).fetchone()

        self.assertEqual(row, ("22920000000000", "secret", "", "default"))


if __name__ == "__main__":
    unittest.main()
