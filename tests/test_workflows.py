from datetime import date, datetime, time
from pathlib import Path
import unittest

from publisher.activity import RunControl
from publisher.browser import (
    ManagedChapter,
    PreflightResult,
    PreflightStatus,
    SubmissionResult,
)
from publisher.models import (
    BookConfig,
    Chapter,
    NovelOperation,
    PublishMode,
    RemoteChapter,
    ScheduledDay,
)
from publisher.short_story import ShortStoryConfig
from publisher.short_story_browser import (
    ShortStoryAgreementRequired,
    ShortStorySubmissionError,
    ShortStorySubmissionResult,
)
from publisher.workflows import (
    publish_all_scheduled,
    publish_all_short_stories,
    publish_short_story,
    run_novel_operation,
    sync_novel_status,
)


def _book() -> BookConfig:
    return BookConfig(
        book_id="book-1",
        name="测试作品",
        source_dir=Path("."),
        publish_time=time(0, 0),
        mode=PublishMode.WORDS,
        limit=10000,
        next_chapter=1,
        publish_start_date=date(2026, 8, 10),
    )


def _day(number: int) -> ScheduledDay:
    chapter = Chapter(Path(f"第{number}章.txt"), number, f"标题{number}", 1200, "hash")
    return ScheduledDay(datetime(2026, 8, 10 + number - 1, 0, 0), (chapter,))


class _Service:
    def __init__(self, days: list[ScheduledDay]) -> None:
        self.book = _book()
        self.days = days
        self.source_chapters = [chapter for day in days for chapter in day.chapters]
        self.synced: set[int] | None = None
        self.recorded: list[tuple[int, bool, str | None]] = []

    def get_book(self, _book_id: str) -> BookConfig:
        return self.book

    def reconcile_remote_submissions(self, _book_id: str, numbers: set[int]) -> None:
        self.synced = numbers

    def next_pending_day(self, _book_id: str, _remote=None) -> ScheduledDay:
        if not self.days:
            raise ValueError("没有可提交的待发布章节")
        return self.days.pop(0)

    def confirm_batch(self, _book_id: str, numbers: list[int]) -> str:
        return "token-" + "-".join(map(str, numbers))

    def record_submission(
        self,
        _book_id: str,
        chapter_number: int,
        success: bool,
        _token: str,
        error: str | None,
    ) -> None:
        self.recorded.append((chapter_number, success, error))

    def cancel_batch(self, _book_id: str, _token: str) -> None:
        pass

    def get_schedule(self, _book_id: str):
        return list(self.days)

    def selected_source_chapters(self, _book_id: str):
        return list(self.source_chapters)


class _Gateway:
    def __init__(self, remote=(), fail_at: int | None = None, on_submit=None) -> None:
        self.remote = list(remote)
        self.fail_at = fail_at
        self.submitted: list[int] = []
        self.remote_reads = 0
        self.known_remote_numbers: list[set[int] | None] = []
        self.on_submit = on_submit

    def launch(self) -> None:
        pass

    def preflight(self, _book_name: str) -> PreflightResult:
        return PreflightResult(PreflightStatus.READY, "后台已连接")

    def existing_remote_chapters(self):
        self.remote_reads += 1
        return list(self.remote)

    def submit_batch(
        self,
        drafts,
        _book_name: str,
        *,
        known_remote_numbers=None,
        should_stop=None,
    ):
        self.known_remote_numbers.append(
            None if known_remote_numbers is None else set(known_remote_numbers)
        )
        results = []
        for draft in drafts:
            if should_stop is not None and should_stop():
                results.append(SubmissionResult(draft.chapter_number, False, cancelled=True))
                break
            self.submitted.append(draft.chapter_number)
            if self.on_submit is not None:
                self.on_submit(draft.chapter_number)
            if draft.chapter_number == self.fail_at:
                results.append(
                    SubmissionResult(
                        draft.chapter_number,
                        False,
                        blocked=True,
                        error="真实失败",
                    )
                )
                break
            results.append(SubmissionResult(draft.chapter_number, True, verified=True))
        return results


class _OperationGateway:
    def __init__(self, managed, fail_at: int | None = None, on_submit=None) -> None:
        self.managed = list(managed)
        self.fail_at = fail_at
        self.on_submit = on_submit
        self.managed_reads = 0
        self.calls: list[tuple[str, list[int]]] = []
        self.known_numbers: set[int] | None = None

    def launch(self) -> None:
        pass

    def preflight(self, _book_name: str) -> PreflightResult:
        return PreflightResult(PreflightStatus.READY, "后台已连接")

    def managed_chapters(self, _book_name: str):
        self.managed_reads += 1
        return list(self.managed)

    def _submit(self, operation: str, items, should_stop=None):
        self.calls.append((operation, [item.chapter_number for item in items]))
        results = []
        for item in items:
            if should_stop is not None and should_stop():
                results.append(SubmissionResult(item.chapter_number, False, cancelled=True))
                break
            if self.on_submit is not None:
                self.on_submit(item.chapter_number)
            if item.chapter_number == self.fail_at:
                results.append(
                    SubmissionResult(
                        item.chapter_number,
                        False,
                        blocked=True,
                        error="真实失败",
                    )
                )
                break
            results.append(SubmissionResult(item.chapter_number, True, verified=True))
        return results

    def submit_immediately(
        self,
        drafts,
        _book_name: str,
        *,
        known_remote_numbers=None,
        should_stop=None,
    ):
        self.known_numbers = set(known_remote_numbers or ())
        return self._submit("immediate", drafts, should_stop)

    def save_drafts(self, drafts, _book_name: str, *, should_stop=None):
        return self._submit("draft", drafts, should_stop)

    def update_existing(self, drafts, _managed, *, should_stop=None):
        return self._submit("edit-content", drafts, should_stop)

    def reschedule_existing(self, changes, _managed, *, should_stop=None):
        return self._submit("reschedule", changes, should_stop)


class WorkflowTests(unittest.TestCase):
    def test_new_book_with_an_empty_remote_list_still_publishes(self):
        service = _Service([_day(1)])
        gateway = _Gateway(remote=[])

        report = publish_all_scheduled(
            service,
            gateway,
            service.book.book_id,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertTrue(report.success)
        self.assertEqual(report.submitted_numbers, (1,))
        self.assertEqual(service.synced, set())
        self.assertEqual(gateway.submitted, [1])

    def test_publish_runs_every_pending_day_and_returns_one_summary(self):
        service = _Service([_day(1), _day(2)])
        gateway = _Gateway()
        progress: list[str] = []

        report = publish_all_scheduled(
            service,
            gateway,
            service.book.book_id,
            read_body=lambda _path, _chapter: "正文",
            on_progress=progress.append,
        )

        self.assertTrue(report.success)
        self.assertEqual(report.submitted_numbers, (1, 2))
        self.assertEqual(gateway.submitted, [1, 2])
        self.assertIn("正在提交第2章", progress)

    def test_publish_scans_remote_chapters_once_and_reuses_known_numbers(self):
        service = _Service([_day(1), _day(2)])
        gateway = _Gateway(remote=[RemoteChapter(77, 1200, datetime(2026, 8, 1, 0, 0))])

        report = publish_all_scheduled(
            service,
            gateway,
            service.book.book_id,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertTrue(report.success)
        self.assertEqual(gateway.remote_reads, 1)
        self.assertEqual(gateway.known_remote_numbers, [{77}, {1, 77}])

    def test_real_failure_stops_once_and_is_returned_in_the_final_report(self):
        service = _Service([_day(1), _day(2)])
        gateway = _Gateway(fail_at=2)

        report = publish_all_scheduled(
            service,
            gateway,
            service.book.book_id,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertFalse(report.success)
        self.assertEqual(report.submitted_numbers, (1,))
        self.assertEqual(report.failed_chapter, 2)
        self.assertEqual(report.error, "真实失败")

    def test_publish_stops_before_the_next_chapter_when_requested(self):
        control = RunControl()
        service = _Service([_day(1), _day(2), _day(3)])
        gateway = _Gateway(
            on_submit=lambda number: control.request_stop() if number == 1 else None
        )

        report = publish_all_scheduled(
            service,
            gateway,
            service.book.book_id,
            read_body=lambda _path, _chapter: "正文",
            control=control,
        )

        self.assertTrue(report.cancelled)
        self.assertEqual(report.submitted_numbers, (1,))
        self.assertEqual(report.remaining_numbers, (2, 3))
        self.assertEqual(gateway.submitted, [1])

    def test_sync_accepts_an_empty_remote_manager_as_a_valid_new_book(self):
        service = _Service([])
        gateway = _Gateway(remote=[])

        report = sync_novel_status(service, gateway, service.book.book_id)

        self.assertEqual(report.remote_count, 0)
        self.assertEqual(report.message, "后台已连接")
        self.assertEqual(service.synced, set())

    def test_immediate_operation_reads_the_managed_list_once_and_skips_existing(self):
        service = _Service([_day(1), _day(2), _day(3)])
        gateway = _OperationGateway(
            [ManagedChapter(1, "pending", "/publish/entry-1")]
        )

        report = run_novel_operation(
            service,
            gateway,
            service.book.book_id,
            NovelOperation.IMMEDIATE,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertTrue(report.success)
        self.assertEqual(report.submitted_numbers, (2, 3))
        self.assertEqual(report.skipped_numbers, (1,))
        self.assertEqual(gateway.managed_reads, 1)
        self.assertEqual(gateway.calls, [("immediate", [2, 3])])
        self.assertEqual(gateway.known_numbers, {1})

    def test_draft_operation_stops_after_the_first_failed_chapter(self):
        service = _Service([_day(1), _day(2), _day(3)])
        gateway = _OperationGateway([], fail_at=2)

        report = run_novel_operation(
            service,
            gateway,
            service.book.book_id,
            NovelOperation.DRAFT,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertFalse(report.success)
        self.assertEqual(report.submitted_numbers, (1,))
        self.assertEqual(report.failed_chapter, 2)
        self.assertEqual(report.remaining_numbers, (2, 3))
        self.assertEqual(gateway.managed_reads, 1)
        self.assertEqual(gateway.calls, [("draft", [1, 2, 3])])

    def test_reschedule_only_sends_pending_remote_chapters(self):
        service = _Service([_day(1), _day(2)])
        gateway = _OperationGateway(
            [
                ManagedChapter(1, "pending", "/publish/entry-1"),
                ManagedChapter(2, "published", "/publish/entry-2"),
            ]
        )

        report = run_novel_operation(
            service,
            gateway,
            service.book.book_id,
            NovelOperation.RESCHEDULE,
            read_body=lambda _path, _chapter: "正文",
        )

        self.assertTrue(report.success)
        self.assertEqual(report.submitted_numbers, (1,))
        self.assertEqual(report.skipped_numbers, (2,))
        self.assertEqual(gateway.managed_reads, 1)
        self.assertEqual(gateway.calls, [("reschedule", [1])])

    def test_short_story_agreement_keeps_the_remote_draft_for_resume(self):
        config = ShortStoryConfig(
            story_id="story-1",
            name="夜航",
            source_path=Path("夜航.txt"),
            cover_path=Path("cover.png"),
            primary_category="其他",
            consent_confirmed=True,
        )

        class Service:
            def __init__(self) -> None:
                self.config = config

            def get_short_story(self, _story_id: str):
                return self.config

            def update_short_story(self, updated) -> None:
                self.config = updated

        class Publisher:
            def __init__(self, _gateway) -> None:
                pass

            def submit(self, _config):
                raise ShortStoryAgreementRequired(
                    "https://fanqienovel.com/main/writer/publish-short/123"
                )

        service = Service()
        report = publish_short_story(
            service,
            object(),
            "story-1",
            publisher_factory=Publisher,
        )

        self.assertFalse(report.success)
        self.assertTrue(report.requires_user_action)
        self.assertEqual(
            service.config.remote_draft_url,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

    def test_short_story_failure_keeps_the_remote_draft_for_retry(self):
        config = ShortStoryConfig(
            story_id="story-1",
            name="夜航",
            source_path=Path("夜航.txt"),
            cover_path=Path("cover.png"),
            primary_category="其他",
            consent_confirmed=True,
        )

        class Service:
            def __init__(self) -> None:
                self.config = config

            def get_short_story(self, _story_id: str):
                return self.config

            def update_short_story(self, updated) -> None:
                self.config = updated

        class Publisher:
            def __init__(self, _gateway) -> None:
                pass

            def submit(self, _config):
                raise ShortStorySubmissionError(
                    "https://fanqienovel.com/main/writer/publish-short/123",
                    "短故事 AI 生成声明未生效",
                )

        service = Service()
        report = publish_short_story(
            service,
            object(),
            "story-1",
            publisher_factory=Publisher,
        )

        self.assertFalse(report.success)
        self.assertFalse(report.requires_user_action)
        self.assertEqual(report.message, "短故事 AI 生成声明未生效")
        self.assertEqual(
            service.config.remote_draft_url,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

    def test_successful_short_story_publish_clears_the_resumable_draft(self):
        config = ShortStoryConfig(
            story_id="story-1",
            name="夜航",
            source_path=Path("夜航.txt"),
            cover_path=Path("cover.png"),
            primary_category="其他",
            consent_confirmed=True,
            remote_draft_url="https://fanqienovel.com/main/writer/publish-short/123",
        )

        class Service:
            def __init__(self) -> None:
                self.config = config

            def get_short_story(self, _story_id: str):
                return self.config

            def update_short_story(self, updated) -> None:
                self.config = updated

        class Publisher:
            def __init__(self, _gateway) -> None:
                pass

            def submit(self, _config):
                return ShortStorySubmissionResult(True)

        service = Service()
        report = publish_short_story(
            service,
            object(),
            "story-1",
            publisher_factory=Publisher,
        )

        self.assertTrue(report.success)
        self.assertIsNone(service.config.remote_draft_url)

    def test_short_story_queue_skips_remote_published_titles_and_submits_the_rest_in_order(self):
        stories = [
            ShortStoryConfig(
                story_id="story-1",
                name="已发布故事",
                source_path=Path("1.txt"),
                cover_path=Path("1.png"),
                primary_category="其他",
                consent_confirmed=True,
            ),
            ShortStoryConfig(
                story_id="story-2",
                name="待发布甲",
                source_path=Path("2.txt"),
                cover_path=Path("2.png"),
                primary_category="其他",
                consent_confirmed=True,
            ),
            ShortStoryConfig(
                story_id="story-3",
                name="待发布乙",
                source_path=Path("3.txt"),
                cover_path=Path("3.png"),
                primary_category="其他",
                consent_confirmed=True,
            ),
        ]

        class Service:
            def list_short_stories(self):
                return stories

            def get_short_story(self, story_id: str):
                return next(story for story in stories if story.story_id == story_id)

            def update_short_story(self, _story) -> None:
                pass

        class Publisher:
            submitted: list[str] = []

            def __init__(self, _gateway) -> None:
                pass

            def published_titles(self):
                return {"已发布故事"}

            def submit(self, config):
                self.submitted.append(config.name)
                return ShortStorySubmissionResult(True)

        report = publish_all_short_stories(
            Service(), object(), publisher_factory=Publisher
        )

        self.assertTrue(report.success)
        self.assertEqual(report.skipped_names, ("已发布故事",))
        self.assertEqual(report.submitted_names, ("待发布甲", "待发布乙"))
        self.assertEqual(Publisher.submitted, ["待发布甲", "待发布乙"])

    def test_short_story_queue_stops_on_the_first_failed_story(self):
        stories = [
            ShortStoryConfig(
                story_id="story-1",
                name="待发布甲",
                source_path=Path("1.txt"),
                cover_path=Path("1.png"),
                primary_category="其他",
                consent_confirmed=True,
            ),
            ShortStoryConfig(
                story_id="story-2",
                name="待发布乙",
                source_path=Path("2.txt"),
                cover_path=Path("2.png"),
                primary_category="其他",
                consent_confirmed=True,
            ),
        ]

        class Service:
            def list_short_stories(self):
                return stories

            def get_short_story(self, story_id: str):
                return next(story for story in stories if story.story_id == story_id)

            def update_short_story(self, _story) -> None:
                pass

        class Publisher:
            submitted: list[str] = []

            def __init__(self, _gateway) -> None:
                pass

            def published_titles(self):
                return set()

            def submit(self, config):
                self.submitted.append(config.name)
                if config.name == "待发布甲":
                    return ShortStorySubmissionResult(False, error="分类未保存")
                return ShortStorySubmissionResult(True)

        report = publish_all_short_stories(
            Service(), object(), publisher_factory=Publisher
        )

        self.assertFalse(report.success)
        self.assertEqual(report.submitted_names, ())
        self.assertEqual(report.failed_name, "待发布甲")
        self.assertEqual(report.error, "分类未保存")
        self.assertEqual(Publisher.submitted, ["待发布甲"])


if __name__ == "__main__":
    unittest.main()
