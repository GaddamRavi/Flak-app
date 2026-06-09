import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class MetricTests(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(app.format_bytes(0), "0.0 B")
        self.assertEqual(app.format_bytes(1024), "1.0 KB")
        self.assertEqual(app.format_bytes(1024 * 1024), "1.0 MB")

    def test_directory_size_counts_files_and_ignores_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            (root / "first.txt").write_bytes(b"1234")
            (nested / "second.txt").write_bytes(b"123456")

            self.assertEqual(app.directory_size(root), 10)

    def test_memory_metrics_uses_process_rss_and_container_limit(self):
        with (
            patch.object(app, "process_memory_bytes", return_value=64 * 1024 * 1024),
            patch.object(
                app,
                "cgroup_memory_values",
                return_value=(80 * 1024 * 1024, 256 * 1024 * 1024),
            ),
        ):
            metrics = app.memory_metrics()

        self.assertEqual(metrics["used"], "64.0 MB")
        self.assertEqual(metrics["total"], "256.0 MB")
        self.assertEqual(metrics["used_percent"], 25.0)
        self.assertEqual(metrics["scope"], "process_rss")

    def test_status_endpoint_contains_scoped_metrics(self):
        response = app.app.test_client().get("/api/status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("scope", payload["metrics"]["memory"])
        self.assertIn("app_used", payload["metrics"]["disk"])
        self.assertIn("filesystem_free", payload["metrics"]["disk"])


if __name__ == "__main__":
    unittest.main()
