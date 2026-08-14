from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.chapters import (
    ChapterParseError,
    contiguous_chapters,
    discover_project,
    read_chapter_body,
    scan_chapters,
)


class ChapterScanTests(unittest.TestCase):
    def test_scan_recursively_sorts_numbered_txt_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "卷一").mkdir()
            (root / "卷一" / "第002章-后.txt").write_text("后文", encoding="utf-8")
            (root / "第001章-前.txt").write_text("前 文\n", encoding="utf-8")

            chapters = scan_chapters(root)

        self.assertEqual([chapter.number for chapter in chapters], [1, 2])
        self.assertEqual(chapters[0].title, "前")
        self.assertEqual(chapters[0].character_count, 2)

    def test_scan_rejects_duplicate_chapter_numbers(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "第001章-A.txt").write_text("A", encoding="utf-8")
            (root / "第001章-B.txt").write_text("B", encoding="utf-8")

            with self.assertRaises(ChapterParseError):
                scan_chapters(root)

    def test_scan_ignores_non_chapter_text_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "第001章-正文.txt").write_text("正文", encoding="utf-8")
            (root / "备选稿_大纲.txt").write_text("资料", encoding="utf-8")

            chapters = scan_chapters(root)

        self.assertEqual([chapter.number for chapter in chapters], [1])

    def test_discover_project_prefers_named_body_directory(self):
        with TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "电赛小说"
            body_dir = project / "10-正文"
            body_dir.mkdir(parents=True)
            (body_dir / "第001章-开始.txt").write_text("正文", encoding="utf-8")

            detected = discover_project(project)

        self.assertEqual(detected.name, "电赛小说")
        self.assertEqual(detected.source_dir, body_dir)
        self.assertEqual(detected.first_chapter, 1)

    def test_contiguous_chapters_stops_before_a_missing_number(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "第001章-前.txt").write_text("前文", encoding="utf-8")
            (root / "第003章-后.txt").write_text("后文", encoding="utf-8")

            chapters = contiguous_chapters(scan_chapters(root), 1, None)

        self.assertEqual([chapter.number for chapter in chapters], [1])

    def test_scan_supports_markdown_and_common_chapter_name_forms(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "第001回-开场.md").write_text(
                "# 第1回 开场\n\n正文一", encoding="utf-8"
            )
            (root / "chapter-2-继续.md").write_text("正文二", encoding="utf-8")
            (root / "3-收束.txt").write_text("正文三", encoding="utf-8")

            chapters = scan_chapters(root)
            first_body = read_chapter_body(root, chapters[0])

        self.assertEqual([chapter.number for chapter in chapters], [1, 2, 3])
        self.assertEqual([chapter.title for chapter in chapters], ["开场", "继续", "收束"])
        self.assertEqual(first_body, "第1回 开场\n\n正文一")
        self.assertEqual(chapters[0].character_count, len("第1回开场正文一"))

    def test_scan_rejects_duplicate_numbers_across_text_and_markdown(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "第001章-正文.txt").write_text("正文", encoding="utf-8")
            (root / "chapter-1-副本.md").write_text("正文", encoding="utf-8")

            with self.assertRaises(ChapterParseError):
                scan_chapters(root)
