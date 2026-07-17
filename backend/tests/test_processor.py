import os
import io
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core import processor


class _FakePixmap:
    def save(self, path):
        with open(path, "wb") as image:
            image.write(b"image")


class _FakePage:
    def get_pixmap(self, **_kwargs):
        return _FakePixmap()


class _FakeProcess:
    def __init__(self):
        self.stdout = io.StringIO("")
        self.returncode = None
        self.pid = 12345

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise processor.subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


class ProcessorLifecycleTests(unittest.TestCase):
    def test_vector_collection_is_lazy(self):
        self.assertIsNone(processor._VECTOR_COLLECTION)

    def test_parse_failure_before_indexing_does_not_load_vector_runtime(self):
        with (
            mock.patch.object(processor, "delete_vectors_for_file") as delete_vectors,
            mock.patch.object(processor, "update_file_ingestion"),
        ):
            processor._mark_ingestion_failed(
                1,
                "pymupdf",
                processor.time.monotonic(),
                "OCR failed",
                cleanup_vectors=False,
            )

        delete_vectors.assert_not_called()

    def test_tesseract_retries_with_fallback_layout(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="layout failed")
        succeeded = mock.Mock(returncode=0, stdout="识别成功", stderr="")
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "page.png")
            with mock.patch.object(processor.subprocess, "run", side_effect=[failed, succeeded]) as run:
                text = processor._ocr_page_with_tesseract(
                    _FakePage(), image_path, "tesseract.exe"
                )

        self.assertEqual(text, "识别成功")
        self.assertEqual(run.call_count, 2)
        self.assertIn("3", run.call_args_list[0].args[0])
        self.assertIn("6", run.call_args_list[1].args[0])

    def test_external_engine_reclaims_process_after_stdout_closes(self):
        fake_process = _FakeProcess()

        def terminate(process):
            process.returncode = 1

        with (
            mock.patch.object(processor, "is_initialized", return_value=True),
            mock.patch.object(processor, "get_engine_device", return_value="cpu"),
            mock.patch.object(processor, "build_engine_command", return_value=["fake"]),
            mock.patch.object(processor.subprocess, "Popen", return_value=fake_process),
            mock.patch.object(processor, "_terminate_process_tree", side_effect=terminate) as cleanup,
            mock.patch.object(processor, "ENGINE_EXIT_GRACE_SECONDS", 0),
        ):
            stream = processor._extract_with_external_engine_stream("marker", __file__)
            with self.assertRaisesRegex(RuntimeError, "关闭日志输出"):
                list(stream)
        cleanup.assert_called_once_with(fake_process)


if __name__ == "__main__":
    unittest.main()
