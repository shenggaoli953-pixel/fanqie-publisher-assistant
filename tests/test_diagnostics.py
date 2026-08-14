from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.diagnostics import write_diagnostic_report
from publisher.models import BookState, Chapter, ScheduledDay


class DiagnosticTests(unittest.TestCase):
    def test_diagnostic_report_omits_titles_paths_urls_and_error_details(self):
        chapter = Chapter(
            relative_path=Path(r"C:\secret\正文\私密标题.txt"),
            number=8,
            title="私密标题",
            character_count=3210,
            sha256="hash",
        )
        state = BookState(
            book_id="账号A-私密作品",
            schedule=(),
            last_error=(
                r"正文内容 C:\secret\正文\私密标题.txt "
                "https://example.com/account"
            ),
            last_failed_chapter=8,
        )
        schedule = [
            ScheduledDay(
                publish_at=datetime(2026, 8, 15, 12, 0),
                chapters=(chapter,),
                status="pending",
            )
        ]

        with TemporaryDirectory() as temp_dir:
            report = write_diagnostic_report(
                Path(temp_dir) / "diagnostic.json",
                version="0.2.0",
                state=state,
                schedule=schedule,
            )
            content = report.read_text(encoding="utf-8")

        for private_value in (
            "私密标题",
            "正文内容",
            "C:\\secret",
            "https://",
            "账号A",
        ):
            self.assertNotIn(private_value, content)
        self.assertIn('"chapter_number": 8', content)
        self.assertIn('"last_error_category": "unknown"', content)

    def test_diagnostic_report_categorizes_common_errors_without_copying_them(self):
        state = BookState(
            book_id="robot",
            schedule=(),
            last_error="登录状态已过期，请重新登录",
        )

        with TemporaryDirectory() as temp_dir:
            report = write_diagnostic_report(
                Path(temp_dir) / "diagnostic.json",
                version="0.2.0",
                state=state,
                schedule=[],
            )
            content = report.read_text(encoding="utf-8")

        self.assertIn('"last_error_category": "login"', content)
        self.assertNotIn("登录状态已过期", content)
