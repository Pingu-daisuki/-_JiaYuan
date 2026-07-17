import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.campus_core import XmuNativeBot, extract_answered_count, extract_rollcalls


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.requested_url = None

    def get(self, url, timeout):
        self.requested_url = url
        self.timeout = timeout
        return _FakeResponse(self.payload)


class AnsweredCountTests(unittest.TestCase):
    def test_reads_nested_and_string_count(self):
        self.assertEqual(extract_answered_count({"rollcall": {"answerCount": "12"}}), 12)

    def test_counts_student_rollcall_statuses(self):
        payload = {
            "student_rollcalls": [
                {"status": "present"},
                {"status": "answered"},
                {"status": "absent"},
            ]
        }
        self.assertEqual(extract_answered_count(payload), 2)

    def test_unknown_payload_does_not_default_to_zero(self):
        self.assertIsNone(extract_answered_count({"course_title": "Test"}))

    def test_reads_generic_nested_attendance_total(self):
        self.assertEqual(
            extract_answered_count({"data": {"attendance": {"total": "8"}}}),
            8,
        )

    def test_extracts_wrapped_rollcall_list(self):
        rollcalls = [{"rollcall_id": 42}]
        self.assertEqual(extract_rollcalls({"data": {"rollcalls": rollcalls}}), rollcalls)

    def test_fetches_detail_when_radar_item_has_no_count(self):
        bot = XmuNativeBot("student", "password", answer_threshold=3)
        bot.session = _FakeSession({"data": {"answered_students": [{}, {}, {}]}})

        count = bot.get_answered_count({"rollcall_id": 42, "status": "absent"})

        self.assertEqual(count, 3)
        self.assertTrue(bot.session.requested_url.endswith("/api/rollcall/42/student_rollcalls"))
        self.assertEqual(bot.session.timeout, 10)


if __name__ == "__main__":
    unittest.main()
