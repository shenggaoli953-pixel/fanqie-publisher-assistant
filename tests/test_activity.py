from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.activity import ActivityLog, RunControl


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_run_control_remembers_a_stop_request(self):
        control = RunControl()

        control.request_stop()

        self.assertTrue(control.stop_requested())

    def test_activity_log_omits_private_error_text(self):
        log = ActivityLog(self.root)

        entry = log.append(
            "scheduled",
            "failed",
            chapter_number=8,
            error="C:/private https://example.com 正文 标题",
        )
        payload = (self.root / "activity.json").read_text(encoding="utf-8")

        self.assertEqual(entry.error_category, "unknown")
        for value in ("C:/private", "https://", "正文", "标题"):
            self.assertNotIn(value, payload)

    def test_activity_log_keeps_only_the_latest_five_hundred_entries(self):
        log = ActivityLog(self.root)
        for chapter_number in range(1, 503):
            log.append("scheduled", "submitted", chapter_number=chapter_number)

        records = log.recent()

        self.assertEqual(len(records), 500)
        self.assertEqual(records[0].chapter_number, 3)
        self.assertEqual(records[-1].chapter_number, 502)


if __name__ == "__main__":
    unittest.main()
