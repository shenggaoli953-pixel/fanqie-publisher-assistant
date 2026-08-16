from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from publisher.chapters import scan_chapters
from publisher.models import (
    BookConfig,
    BookState,
    PublishMode,
    RemoteChapter,
    ScheduledDay,
)
from publisher.repository import JsonRepository
from publisher.service import PublishingService
from publisher.short_story import ShortStoryConfig


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source_dir = self.root / "正文"
        self.source_dir.mkdir()
        (self.source_dir / "第001章-开始.txt").write_text("第一章", encoding="utf-8")
        (self.source_dir / "第002章-继续.txt").write_text("第二章", encoding="utf-8")
        (self.source_dir / "第003章-结尾.txt").write_text("第三章", encoding="utf-8")
        self.repository = JsonRepository(self.root / "data")
        self.service = PublishingService(self.repository)
        self.service.add_book(
            BookConfig(
                book_id="robot",
                name="机器人",
                source_dir=self.source_dir,
                publish_time=time(0, 0),
                mode=PublishMode.CHAPTERS,
                limit=1,
                next_chapter=1,
                publish_start_date=date(2026, 7, 27),
            ),
        )

    def test_unconfirmed_batch_cannot_be_submitted(self):
        with self.assertRaises(PermissionError):
            self.service.record_submission("robot", 1, True, "missing")

    def test_list_books_returns_each_saved_book(self):
        self.assertEqual([book.book_id for book in self.service.list_books()], ["robot"])

    def test_delete_book_removes_its_workbench_entry_and_schedule_state(self):
        self.service.delete_book("robot")

        self.assertEqual(self.service.list_books(), [])
        self.assertIsNone(self.repository.load_state("robot"))
        with self.assertRaisesRegex(KeyError, "未知书籍"):
            self.service.get_book("robot")

    def test_get_book_state_returns_the_selected_book_state(self):
        state = self.service.get_book_state("robot")

        self.assertEqual(state.book_id, "robot")
        self.assertEqual(state.last_failed_chapter, None)

    def test_short_story_configs_can_be_added_and_updated(self):
        source_path = self.root / "夜航.txt"
        source_path.write_text("短故事正文", encoding="utf-8")
        config = ShortStoryConfig(
            story_id="story-1",
            name="夜航",
            source_path=source_path,
            cover_path=self.root / "cover.png",
            primary_category="其他",
            consent_confirmed=True,
        )

        self.service.add_short_story(config)
        self.service.update_short_story(
            ShortStoryConfig(
                **{
                    **config.to_dict(),
                    "source_path": config.source_path,
                    "cover_path": config.cover_path,
                    "remote_draft_url": (
                        "https://fanqienovel.com/main/writer/publish-short/123"
                    ),
                }
            )
        )

        saved = self.service.get_short_story("story-1")
        self.assertEqual(len(self.service.list_short_stories()), 1)
        self.assertEqual(
            saved.remote_draft_url,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

    def test_delete_short_story_keeps_its_local_source_file(self):
        source_path = self.root / "夜航.txt"
        source_path.write_text("短故事正文", encoding="utf-8")
        config = ShortStoryConfig(
            story_id="story-1",
            name="夜航",
            source_path=source_path,
            cover_path=self.root / "cover.png",
            primary_category="其他",
            consent_confirmed=True,
        )
        self.service.add_short_story(config)

        self.service.delete_short_story("story-1")

        self.assertEqual(self.service.list_short_stories(), [])
        self.assertTrue(source_path.exists())
        with self.assertRaisesRegex(KeyError, "未知短故事"):
            self.service.get_short_story("story-1")

    def test_paused_book_has_no_schedule_and_cannot_be_confirmed(self):
        self.service.add_book(
            BookConfig(
                book_id="paused",
                name="暂缓作品",
                source_dir=self.source_dir,
                publish_time=time(0, 0),
                mode=PublishMode.CHAPTERS,
                limit=1,
                next_chapter=1,
                publish_start_date=None,
            ),
        )

        self.assertEqual(self.service.get_schedule("paused"), [])
        with self.assertRaisesRegex(PermissionError, "首个自动发布日期"):
            self.service.confirm_batch("paused", [1])

    def test_next_pending_day_returns_only_the_first_publish_day(self):
        day = self.service.next_pending_day("robot")

        self.assertEqual([chapter.number for chapter in day.chapters], [1])
        self.assertEqual(day.publish_at, datetime(2026, 7, 27, 0, 0))

    def test_next_pending_day_refreshes_a_renamed_chapter_file(self):
        old_path = self.source_dir / "第001章-开始.txt"
        renamed_path = self.source_dir / "第001章-新的标题.txt"
        old_path.rename(renamed_path)

        day = self.service.next_pending_day("robot")

        self.assertEqual(day.chapters[0].relative_path, renamed_path.relative_to(self.source_dir))
        self.assertEqual(day.chapters[0].title, "新的标题")

    def test_end_chapter_limits_the_pending_schedule(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=1,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=2,
        )

        scheduled_numbers = [
            chapter.number
            for day in self.service.get_schedule("robot")
            for chapter in day.chapters
        ]
        self.assertEqual(scheduled_numbers, [1, 2])

    def test_selected_source_chapters_honor_the_saved_range(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=1,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=2,
            publish_end_chapter=3,
        )

        chapters = self.service.selected_source_chapters("robot")

        self.assertEqual([chapter.number for chapter in chapters], [2, 3])

    def test_policy_can_update_the_ai_declaration(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=1,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=None,
            ai_generated=False,
        )

        self.assertFalse(self.service.get_book("robot").ai_generated)

    def test_policy_preserves_or_replaces_multiple_publish_times_explicitly(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=1,
            publish_time=time(8, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=None,
            publish_times=(time(8, 0), time(12, 0)),
        )

        self.assertEqual(
            self.service.get_book("robot").effective_publish_times,
            (time(8, 0), time(12, 0)),
        )

        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=2,
            publish_time=time(8, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=None,
        )

        self.assertEqual(
            self.service.get_book("robot").effective_publish_times,
            (time(8, 0), time(12, 0)),
        )

    def test_submission_advances_only_within_the_selected_range(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=1,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=2,
            publish_end_chapter=2,
        )
        token = self.service.confirm_batch("robot", [2])
        self.service.record_submission("robot", 2, True, token)

        self.assertEqual(self.service.get_book("robot").next_chapter, 3)

    def test_failed_chapter_remains_the_next_chapter_after_reopen(self):
        token = self.service.confirm_batch("robot", [1, 2])
        self.service.record_submission("robot", 1, True, token)
        self.service.record_submission("robot", 2, False, token, "network error")

        restored = PublishingService(self.repository)

        self.assertEqual(restored.get_book("robot").next_chapter, 2)

    def test_failure_status_clears_only_after_the_failed_chapter_succeeds(self):
        token = self.service.confirm_batch("robot", [1])
        self.service.record_submission("robot", 1, False, token, "network error")

        self.assertEqual(self.service.failure_status("robot"), (1, "network error"))

        retry_token = self.service.confirm_batch("robot", [1])
        self.service.record_submission("robot", 1, True, retry_token)

        self.assertEqual(self.service.failure_status("robot"), (None, None))

    def test_cancel_batch_clears_the_unconsumed_confirmation(self):
        token = self.service.confirm_batch("robot", [1, 2])

        self.service.cancel_batch("robot", token)

        self.assertIsNone(self.service.get_book_state("robot").confirmation)

    def test_remote_fit_keeps_the_pending_schedule_slot_time(self):
        chapters = scan_chapters(self.source_dir)
        book = BookConfig(
            book_id="robot",
            name="机器人",
            source_dir=self.source_dir,
            publish_time=time(8, 0),
            publish_times=(time(8, 0), time(12, 0)),
            mode=PublishMode.CHAPTERS,
            limit=2,
            next_chapter=1,
            publish_start_date=date(2026, 7, 27),
        )
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 12, 0),
            chapters=(chapters[0],),
        )

        fitted = PublishingService._fit_remote_daily_limit(book, day, [])

        self.assertEqual(fitted.publish_at, datetime(2026, 7, 27, 12, 0))

    def test_next_pending_day_retries_only_unsubmitted_chapters_of_partial_day(self):
        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=2,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=None,
        )
        token = self.service.confirm_batch("robot", [1, 2])
        self.service.record_submission("robot", 1, True, token)
        self.service.record_submission("robot", 2, False, token, "network error")

        day = self.service.next_pending_day("robot")

        self.assertEqual([chapter.number for chapter in day.chapters], [2])

    def test_next_pending_day_adds_a_filled_gap_before_later_chapters(self):
        late_source = self.root / "后续正文"
        late_source.mkdir()
        (late_source / "第001章-开始.txt").write_text("第一章", encoding="utf-8")
        (late_source / "第003章-后续.txt").write_text("第三章", encoding="utf-8")
        self.service.add_book(
            BookConfig(
                book_id="late",
                name="后续作品",
                source_dir=late_source,
                publish_time=time(0, 0),
                mode=PublishMode.CHAPTERS,
                limit=1,
                next_chapter=1,
                publish_start_date=date(2026, 7, 27),
            )
        )
        token = self.service.confirm_batch("late", [1])
        self.service.record_submission("late", 1, True, token)
        (late_source / "第002章-补充.txt").write_text("第二章", encoding="utf-8")

        day = self.service.next_pending_day("late")

        self.assertEqual([chapter.number for chapter in day.chapters], [2])

    def test_remote_reconciliation_uses_the_chapters_in_fanqie(self):
        self.service.reconcile_remote_submissions("robot", {1, 3})

        state = self.repository.load_state("robot")

        self.assertEqual(state.submitted_chapters, (1, 3))
        self.assertEqual(self.service.get_book("robot").next_chapter, 2)

    def test_remote_reconciliation_keeps_a_remote_chapter_missing_from_schedule(self):
        chapters = scan_chapters(self.source_dir)
        self.repository.save_state(
            BookState(
                book_id="robot",
                schedule=(
                    ScheduledDay(
                        publish_at=datetime(2026, 7, 27, 0, 0),
                        chapters=tuple(
                            chapter for chapter in chapters if chapter.number != 2
                        ),
                    ),
                ),
            )
        )

        self.service.reconcile_remote_submissions("robot", {1, 2, 3})

        state = self.repository.load_state("robot")

        self.assertEqual(state.submitted_chapters, (1, 2, 3))

    def test_next_pending_day_uses_only_the_remaining_remote_word_capacity(self):
        (self.source_dir / "第001章-开始.txt").write_text("aa", encoding="utf-8")
        (self.source_dir / "第002章-继续.txt").write_text("aa", encoding="utf-8")
        (self.source_dir / "第003章-结尾.txt").write_text("aa", encoding="utf-8")
        self.service.update_policy(
            "robot",
            mode=PublishMode.WORDS,
            limit=5,
            publish_time=time(0, 0),
            publish_start_date=date(2026, 7, 27),
            next_chapter=1,
            publish_end_chapter=None,
        )

        day = self.service.next_pending_day(
            "robot",
            [RemoteChapter(99, 3, datetime(2026, 7, 27, 0, 0))],
        )

        self.assertEqual([chapter.number for chapter in day.chapters], [1])

    def test_remote_entry_with_pending_word_count_uses_the_local_word_count(self):
        (self.source_dir / "第001章-开始.txt").write_text("aa", encoding="utf-8")
        (self.source_dir / "第002章-继续.txt").write_text("aa", encoding="utf-8")
        (self.source_dir / "第003章-结尾.txt").write_text("aa", encoding="utf-8")
        book = BookConfig(
            book_id="robot",
            name="机器人",
            source_dir=self.source_dir,
            publish_time=time(0, 0),
            mode=PublishMode.WORDS,
            limit=5,
            next_chapter=1,
            publish_start_date=date(2026, 7, 27),
        )
        chapters = scan_chapters(self.source_dir)
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 0, 0),
            chapters=tuple(chapter for chapter in chapters if chapter.number in {1, 2}),
        )

        fitted = PublishingService._fit_remote_daily_limit(
            book,
            day,
            [RemoteChapter(3, 0, datetime(2026, 7, 27, 0, 0))],
        )

        self.assertEqual([chapter.number for chapter in fitted.chapters], [1])


    def test_changing_policy_rebuilds_only_unsubmitted_days(self):
        token = self.service.confirm_batch("robot", [1])
        self.service.record_submission("robot", 1, True, token)

        self.service.update_policy(
            "robot",
            mode=PublishMode.CHAPTERS,
            limit=2,
            publish_time=time(8, 0),
            publish_start_date=date(2026, 8, 1),
            next_chapter=1,
            publish_end_chapter=None,
        )

        schedule = self.service.get_schedule("robot")
        self.assertEqual(schedule[0].status, "submitted")
        self.assertEqual([chapter.number for chapter in schedule[1].chapters], [2, 3])
        self.assertEqual(schedule[1].publish_at, datetime(2026, 8, 1, 8, 0))
