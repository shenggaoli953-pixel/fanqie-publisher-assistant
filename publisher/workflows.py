from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from publisher.activity import ActivityLog, RunControl
from publisher.browser import (
    PreflightStatus,
    PublishBlockedError,
    PublishDraft,
)
from publisher.models import Chapter, RemoteChapter
from publisher.short_story_browser import (
    ShortStoryAgreementRequired,
    ShortStoryPublisher,
    ShortStorySubmissionError,
)


@dataclass(frozen=True)
class SyncReport:
    remote_count: int
    message: str


@dataclass(frozen=True)
class PublishRunReport:
    submitted_numbers: tuple[int, ...]
    failed_chapter: int | None = None
    error: str | None = None
    cancelled: bool = False
    remaining_numbers: tuple[int, ...] = ()

    @property
    def success(self) -> bool:
        return not self.cancelled and self.failed_chapter is None and self.error is None


@dataclass(frozen=True)
class ShortStoryRunReport:
    success: bool
    message: str
    requires_user_action: bool = False


@dataclass(frozen=True)
class ShortStoryQueueReport:
    submitted_names: tuple[str, ...]
    skipped_names: tuple[str, ...]
    failed_name: str | None = None
    error: str | None = None
    requires_user_action: bool = False

    @property
    def success(self) -> bool:
        return self.failed_name is None and self.error is None


def sync_novel_status(service, gateway, book_id: str) -> SyncReport:
    book = service.get_book(book_id)
    gateway.launch()
    preflight = gateway.preflight(book.name)
    if preflight.status is not PreflightStatus.READY:
        raise PublishBlockedError(preflight.message)
    remote = list(gateway.existing_remote_chapters())
    service.reconcile_remote_submissions(
        book.book_id,
        {chapter.chapter_number for chapter in remote},
    )
    return SyncReport(len(remote), preflight.message)


def publish_all_scheduled(
    service,
    gateway,
    book_id: str,
    *,
    read_body: Callable[[Path, Chapter], str],
    on_progress: Callable[[str], None] | None = None,
    control: RunControl | None = None,
    activity_log: ActivityLog | None = None,
) -> PublishRunReport:
    progress = on_progress or (lambda _message: None)
    record_activity = activity_log.append if activity_log is not None else None
    book = service.get_book(book_id)
    if record_activity is not None:
        record_activity("scheduled", "started")
    progress("正在连接番茄后台")
    gateway.launch()
    preflight = gateway.preflight(book.name)
    if preflight.status is not PreflightStatus.READY:
        raise PublishBlockedError(preflight.message)

    progress("正在同步后台章节状态")
    remote_chapters = list(gateway.existing_remote_chapters())
    service.reconcile_remote_submissions(
        book.book_id,
        {chapter.chapter_number for chapter in remote_chapters},
    )
    book = service.get_book(book.book_id)
    known_remote_numbers = {
        chapter.chapter_number for chapter in remote_chapters
    }
    submitted: list[int] = []

    while True:
        if control is not None and control.stop_requested():
            remaining = _remaining_numbers(service, book.book_id, submitted)
            progress("任务已停止，未开始下一章")
            if record_activity is not None:
                record_activity("scheduled", "stopped")
            return PublishRunReport(
                tuple(submitted),
                cancelled=True,
                remaining_numbers=remaining,
            )
        try:
            day = service.next_pending_day(book.book_id, remote_chapters)
        except ValueError as error:
            if str(error) == "没有可提交的待发布章节":
                break
            raise

        drafts = [
            PublishDraft(
                chapter_number=chapter.number,
                title=chapter.title,
                body=read_body(book.source_dir, chapter),
                publish_at=day.publish_at,
                ai_generated=book.ai_generated,
            )
            for chapter in day.chapters
        ]
        if not drafts:
            break
        progress(
            f"正在提交第{drafts[0].chapter_number}章"
            + (
                f"至第{drafts[-1].chapter_number}章"
                if len(drafts) > 1
                else ""
            )
        )
        token = service.confirm_batch(
            book.book_id,
            [draft.chapter_number for draft in drafts],
        )
        results = gateway.submit_batch(
            drafts,
            book.name,
            known_remote_numbers=known_remote_numbers,
            should_stop=(control.stop_requested if control is not None else None),
        )
        for result in results:
            if result.cancelled:
                continue
            service.record_submission(
                book.book_id,
                result.chapter_number,
                result.success,
                token,
                result.error,
            )
            if result.success:
                submitted.append(result.chapter_number)
                if record_activity is not None:
                    record_activity(
                        "scheduled",
                        "submitted",
                        chapter_number=result.chapter_number,
                    )

        cancelled = next((result for result in results if result.cancelled), None)
        if cancelled is not None:
            service.cancel_batch(book.book_id, token)
            remaining = _remaining_numbers(
                service,
                book.book_id,
                submitted,
                first_number=cancelled.chapter_number,
            )
            progress("任务已停止，未开始下一章")
            if record_activity is not None:
                record_activity(
                    "scheduled",
                    "stopped",
                    chapter_number=cancelled.chapter_number,
                )
            return PublishRunReport(
                tuple(submitted),
                cancelled=True,
                remaining_numbers=remaining,
            )

        failed = next((result for result in results if not result.success), None)
        if failed is not None:
            if record_activity is not None:
                record_activity(
                    "scheduled",
                    "failed",
                    chapter_number=failed.chapter_number,
                    error=failed.error,
                )
            return PublishRunReport(
                tuple(submitted),
                failed_chapter=failed.chapter_number,
                error=failed.error or "提交失败",
            )
        if len(results) != len(drafts):
            missing_number = drafts[len(results)].chapter_number
            return PublishRunReport(
                tuple(submitted),
                failed_chapter=missing_number,
                error="番茄后台未返回完整的提交结果",
            )

        submitted_numbers = {
            result.chapter_number for result in results if result.success
        }
        remote_chapters.extend(
            RemoteChapter(
                chapter_number=chapter.number,
                character_count=chapter.character_count,
                publish_at=day.publish_at,
            )
            for chapter in day.chapters
            if chapter.number in submitted_numbers
        )
        known_remote_numbers.update(submitted_numbers)

    progress("全部排程处理完成")
    if record_activity is not None:
        record_activity("scheduled", "completed")
    return PublishRunReport(tuple(submitted))


def _remaining_numbers(
    service,
    book_id: str,
    submitted: list[int],
    *,
    first_number: int | None = None,
) -> tuple[int, ...]:
    numbers: list[int] = []
    if first_number is not None:
        numbers.append(first_number)
    submitted_numbers = set(submitted)
    for day in service.get_schedule(book_id):
        if day.status == "submitted":
            continue
        for chapter in day.chapters:
            if chapter.number not in submitted_numbers:
                numbers.append(chapter.number)
    return tuple(dict.fromkeys(numbers))


def publish_short_story(
    service,
    gateway,
    story_id: str,
    *,
    publisher_factory=ShortStoryPublisher,
) -> ShortStoryRunReport:
    config = service.get_short_story(story_id)
    publisher = publisher_factory(gateway)
    try:
        result = publisher.submit(config)
    except ShortStoryAgreementRequired as error:
        service.update_short_story(
            replace(config, remote_draft_url=error.draft_url)
        )
        return ShortStoryRunReport(False, str(error), requires_user_action=True)
    except ShortStorySubmissionError as error:
        service.update_short_story(
            replace(config, remote_draft_url=error.draft_url)
        )
        return ShortStoryRunReport(False, str(error))
    if result.success:
        if config.remote_draft_url is not None:
            service.update_short_story(replace(config, remote_draft_url=None))
        return ShortStoryRunReport(True, "短故事已提交到番茄后台")
    if result.draft_url and result.draft_url != config.remote_draft_url:
        service.update_short_story(
            replace(config, remote_draft_url=result.draft_url)
        )
    return ShortStoryRunReport(False, result.error or "短故事发布失败")


def publish_all_short_stories(
    service,
    gateway,
    *,
    publisher_factory=ShortStoryPublisher,
    on_progress: Callable[[str], None] | None = None,
) -> ShortStoryQueueReport:
    progress = on_progress or (lambda _message: None)
    publisher = publisher_factory(gateway)
    progress("正在同步番茄已发布短故事")
    published_titles = publisher.published_titles()
    submitted: list[str] = []
    skipped: list[str] = []

    for config in service.list_short_stories():
        if config.name in published_titles:
            skipped.append(config.name)
            continue
        progress(f"正在发布短故事：{config.name}")
        report = publish_short_story(
            service,
            gateway,
            config.story_id,
            publisher_factory=lambda _gateway: publisher,
        )
        if report.success:
            submitted.append(config.name)
            published_titles.add(config.name)
            continue
        return ShortStoryQueueReport(
            tuple(submitted),
            tuple(skipped),
            failed_name=config.name,
            error=report.message,
            requires_user_action=report.requires_user_action,
        )

    return ShortStoryQueueReport(tuple(submitted), tuple(skipped))
