import os
import sys
import threading
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core import engine_init


class ProcessStreamingTests(unittest.TestCase):
    def test_streams_output_and_returns_exit_code(self):
        events = list(
            engine_init._stream_process_events(
                [sys.executable, "-u", "-c", "print('ready')"],
                env=os.environ.copy(),
                timeout_seconds=10,
                stall_timeout_seconds=5,
            )
        )

        self.assertIn(("line", "ready"), events)
        self.assertEqual(events[-1], ("exit", 0))

    def test_stalled_process_is_terminated(self):
        events = list(
            engine_init._stream_process_events(
                [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                env=os.environ.copy(),
                timeout_seconds=10,
                stall_timeout_seconds=1,
            )
        )

        self.assertTrue(any(event == "stalled" for event, _ in events))
        self.assertIsNotNone(events[-1][1])

    def test_cancel_event_terminates_process(self):
        cancel_event = threading.Event()
        timer = threading.Timer(0.2, cancel_event.set)
        timer.start()
        try:
            events = list(
                engine_init._stream_process_events(
                    [sys.executable, "-u", "-c", "import time; time.sleep(30)"],
                    env=os.environ.copy(),
                    timeout_seconds=10,
                    stall_timeout_seconds=5,
                    cancel_event=cancel_event,
                )
            )
        finally:
            timer.cancel()

        self.assertTrue(any(event == "cancelled" for event, _ in events))

    def test_pip_install_uses_visible_progress_and_network_limits(self):
        captured = {}

        def fake_events(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            yield "line", "Progress 524288 of 1048576"
            yield "exit", 0

        with (
            mock.patch.object(engine_init, "_stream_process_events", side_effect=fake_events),
            mock.patch.object(engine_init, "_resolve_cli_prefix", return_value=["marker_single"]),
        ):
            output = list(engine_init._stream_pip_install("marker", False))

        command = captured["cmd"]
        self.assertIn("--progress-bar", command)
        self.assertIn("raw", command)
        self.assertIn("--no-input", command)
        self.assertIn("--timeout", command)
        self.assertEqual(
            captured["kwargs"]["stall_timeout_seconds"],
            engine_init.INSTALL_STALL_TIMEOUT_SECONDS,
        )
        self.assertTrue(any("50%" in line for line in output if isinstance(line, str)))
        self.assertIn(engine_init._INSTALL_OK, output)


if __name__ == "__main__":
    unittest.main()
