from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
import secrets

from publisher.chapters import contiguous_chapters, scan_chapters
from publisher.models import (
    BatchConfirmation,
    BookConfig,
    BookState,
    Chapter,
    PublishMode,
    RemoteChapter,
    ScheduledDay,
)
from publisher.planner import build_schedule
from publisher.repository import JsonRepository
from publisher.short_story import ShortStoryConfig


class PublishingService:
    def __init__(self, repository: JsonRepository) -> None:
        self._repository = repository

    def add_book(self, config: BookConfig) -> None:
        books = self._repository.load_books()
        if any(book.book_id == config.book_id for book in books):
            raise ValueError(f"书籍已存在: {config.book_id}")
        self._repository.save_books([*books, config])
        schedule: tuple[ScheduledDay, ...] = ()
        if config.publish_start_date is not None:
            chapters = self._contiguous_source_chapters(config)
            schedule = tuple(
                build_schedule(chapters, config, config.publish_start_date)
            )
        self._repository.save_state(
            BookState(
                book_id=config.book_id,
                schedule=schedule,
            )
        )

    def list_books(self) -> list[BookConfig]:
        return self._repository.load_books()

    def list_short_stories(self) -> list[ShortStoryConfig]:
        return self._repository.load_short_stories()

    def add_short_story(self, config: ShortStoryConfig) -> None:
        stories = self._repository.load_short_stories()
        if any(story.story_id == config.story_id for story in stories):
            raise ValueError(f"短故事已存在: {config.story_id}")
        self._repository.save_short_stories([*stories, config])

    def get_short_story(self, story_id: str) -> ShortStoryConfig:
        for story in self._repository.load_short_stories():
            if story.story_id == story_id:
                return story
        raise KeyError(f"未知短故事: {story_id}")

    def update_short_story(self, config: ShortStoryConfig) -> None:
        stories = self._repository.load_short_stories()
        if not any(story.story_id == config.story_id for story in stories):
            raise KeyError(f"未知短故事: {config.story_id}")
        self._repository.save_short_stories(
            [config if story.story_id == config.story_id else story for story in stories]
        )

    def get_book(self, book_id: str) -> BookConfig:
        for book in self._repository.load_books():
            if book.book_id == book_id:
                return book
        raise KeyError(f"未知书籍: {book_id}")

    def get_book_state(self, book_id: str) -> BookState:
        return self._get_state(book_id)

    def get_schedule(self, book_id: str) -> list[ScheduledDay]:
        book = self.get_book(book_id)
        state = self._get_state(book_id)
        submitted = set(state.submitted_chapters)
        if book.publish_start_date is None:
            return [
                self._with_status(day, submitted)
                for day in state.schedule
                if any(chapter.number in submitted for chapter in day.chapters)
            ]
        return [self._with_status(day, submitted) for day in state.schedule]

    def failure_status(self, book_id: str) -> tuple[int | None, str | None]:
        state = self._get_state(book_id)
        return state.last_failed_chapter, state.last_error

    def next_pending_day(
        self, book_id: str, remote_chapters: list[RemoteChapter] | None = None
    ) -> ScheduledDay:
        state = self._refresh_schedule_from_source(book_id)
        submitted = set(state.submitted_chapters)
        for day in self.get_schedule(book_id):
            remaining = tuple(
                chapter for chapter in day.chapters if chapter.number not in submitted
            )
            if remaining and not day.over_limit:
                pending_day = replace(day, chapters=remaining, status="pending")
                if remote_chapters is None:
                    return pending_day
                return self._fit_remote_daily_limit(
                    self.get_book(book_id), pending_day, remote_chapters
                )
        raise ValueError("没有可提交的待发布章节")

    def update_policy(
        self,
        book_id: str,
        mode: PublishMode,
        limit: int,
        publish_time: time,
        publish_start_date: date | None,
        next_chapter: int,
        publish_end_chapter: int | None,
        ai_generated: bool = True,
        publish_times: tuple[time, ...] | None = None,
    ) -> None:
        book = self.get_book(book_id)
        updated_publish_times = (
            book.publish_times if publish_times is None else publish_times
        )
        updated_book = replace(
            book,
            mode=mode,
            limit=limit,
            publish_start_date=publish_start_date,
            next_chapter=next_chapter,
            publish_end_chapter=publish_end_chapter,
            ai_generated=ai_generated,
            publish_time=(
                updated_publish_times[0]
                if updated_publish_times
                else publish_time
            ),
            publish_times=updated_publish_times,
        )
        state = self._get_state(book_id)
        submitted = set(state.submitted_chapters)
        protected_days = [
            day
            for day in state.schedule
            if any(chapter.number in submitted for chapter in day.chapters)
        ]
        protected_numbers = {
            chapter.number for day in protected_days for chapter in day.chapters
        }
        unprotected_days = [day for day in state.schedule if day not in protected_days]
        rebuilt_days: list[ScheduledDay] = []
        if updated_book.publish_start_date is not None:
            rebuild_start = updated_book.publish_start_date
            if protected_days:
                rebuild_start = max(
                    rebuild_start,
                    protected_days[-1].publish_at.date() + timedelta(days=1),
                )
            pending_chapters = [
                chapter
                for chapter in self._contiguous_source_chapters(updated_book)
                if (
                    chapter.number not in submitted
                    and chapter.number not in protected_numbers
                )
            ]
            rebuilt_days = build_schedule(pending_chapters, updated_book, rebuild_start)
        self._repository.save_books(
            [
                updated_book if item.book_id == book_id else item
                for item in self._repository.load_books()
            ]
        )
        self._repository.save_state(
            replace(
                state,
                schedule=tuple([*protected_days, *rebuilt_days]),
                confirmation=None,
            )
        )

    def confirm_batch(self, book_id: str, chapter_numbers: list[int]) -> str:
        if self.get_book(book_id).publish_start_date is None:
            raise PermissionError("作品尚未设置首个自动发布日期")
        state = self._get_state(book_id)
        known_numbers = {
            chapter.number for day in state.schedule for chapter in day.chapters
        }
        requested_numbers = tuple(chapter_numbers)
        if not requested_numbers or len(set(requested_numbers)) != len(requested_numbers):
            raise ValueError("确认批次必须包含不重复的章节")
        if any(number not in known_numbers for number in requested_numbers):
            raise ValueError("确认批次包含未排程章节")
        if any(number in state.submitted_chapters for number in requested_numbers):
            raise ValueError("确认批次包含已提交章节")

        confirmation = BatchConfirmation(
            token=secrets.token_urlsafe(24),
            chapter_numbers=requested_numbers,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self._repository.save_state(replace(state, confirmation=confirmation, last_error=None))
        return confirmation.token

    def cancel_batch(self, book_id: str, token: str) -> None:
        state = self._get_state(book_id)
        confirmation = state.confirmation
        if confirmation is None or confirmation.token != token:
            raise PermissionError("批次尚未确认")
        self._repository.save_state(replace(state, confirmation=None))

    def record_submission(
        self,
        book_id: str,
        chapter_number: int,
        success: bool,
        token: str,
        error: str | None = None,
    ) -> None:
        state = self._get_state(book_id)
        confirmation = state.confirmation
        if confirmation is None or confirmation.token != token:
            raise PermissionError("批次尚未确认")
        if confirmation.expires_at <= datetime.now(UTC):
            self._repository.save_state(replace(state, confirmation=None))
            raise PermissionError("批次确认已过期")
        if chapter_number not in confirmation.chapter_numbers:
            raise PermissionError("章节不在确认批次中")
        if chapter_number in state.submitted_chapters:
            raise PermissionError("章节已提交")

        if not success:
            self._repository.save_state(
                replace(
                    state,
                    confirmation=None,
                    last_error=error or "提交失败",
                    last_failed_chapter=chapter_number,
                )
            )
            return

        submitted = tuple(sorted({*state.submitted_chapters, chapter_number}))
        cleared_failure = state.last_failed_chapter == chapter_number
        self._repository.save_state(
            replace(
                state,
                submitted_chapters=submitted,
                last_error=None if cleared_failure else state.last_error,
                last_failed_chapter=(
                    None if cleared_failure else state.last_failed_chapter
                ),
            )
        )
        self._save_next_chapter(book_id, submitted)

    def reconcile_remote_submissions(
        self, book_id: str, remote_numbers: set[int]
    ) -> None:
        book = self.get_book(book_id)
        state = self._get_state(book_id)
        scheduled_numbers = {
            chapter.number for day in state.schedule for chapter in day.chapters
        }
        start_number = min(scheduled_numbers, default=book.next_chapter)
        source_numbers = {
            chapter.number
            for chapter in contiguous_chapters(
                scan_chapters(book.source_dir),
                start_number,
                book.publish_end_chapter,
            )
        }
        submitted = tuple(sorted(source_numbers & remote_numbers))
        cleared_failure = state.last_failed_chapter in remote_numbers
        self._repository.save_state(
            replace(
                state,
                submitted_chapters=submitted,
                confirmation=None,
                last_error=None if cleared_failure else state.last_error,
                last_failed_chapter=(
                    None if cleared_failure else state.last_failed_chapter
                ),
            )
        )
        self._save_next_chapter(book_id, submitted)

    def _get_state(self, book_id: str) -> BookState:
        state = self._repository.load_state(book_id)
        if state is None:
            raise KeyError(f"书籍没有状态: {book_id}")
        return state

    @staticmethod
    def _with_status(day: ScheduledDay, submitted: set[int]) -> ScheduledDay:
        numbers = {chapter.number for chapter in day.chapters}
        if numbers.issubset(submitted):
            status = "submitted"
        elif numbers & submitted:
            status = "partial"
        else:
            status = "pending"
        return replace(day, status=status)

    def _save_next_chapter(self, book_id: str, submitted: tuple[int, ...]) -> None:
        book = self.get_book(book_id)
        submitted_numbers = set(submitted)
        numbers = [
            chapter.number
            for chapter in scan_chapters(book.source_dir)
            if (
                chapter.number >= book.next_chapter
                and (
                    book.publish_end_chapter is None
                    or chapter.number <= book.publish_end_chapter
                )
            )
        ]
        next_chapter = next(
            (number for number in numbers if number not in submitted_numbers),
            (
                book.publish_end_chapter + 1
                if book.publish_end_chapter is not None
                else max(numbers, default=0) + 1
            ),
        )
        updated = replace(book, next_chapter=next_chapter)
        self._repository.save_books(
            [updated if item.book_id == book_id else item for item in self._repository.load_books()]
        )

    @staticmethod
    def _contiguous_source_chapters(config: BookConfig) -> list[Chapter]:
        return contiguous_chapters(
            scan_chapters(config.source_dir),
            config.next_chapter,
            config.publish_end_chapter,
        )

    def _refresh_schedule_from_source(self, book_id: str) -> BookState:
        book = self.get_book(book_id)
        state = self._get_state(book_id)
        if book.publish_start_date is None or not state.schedule:
            return state

        source_chapters = scan_chapters(book.source_dir)
        source_by_number = {chapter.number: chapter for chapter in source_chapters}
        scheduled_numbers = {
            chapter.number for day in state.schedule for chapter in day.chapters
        }
        submitted_numbers = set(state.submitted_chapters)
        pending_numbers = scheduled_numbers - submitted_numbers
        missing_numbers = sorted(pending_numbers - source_by_number.keys())
        if missing_numbers:
            first_missing = missing_numbers[0]
            submitted_after_gap = sorted(
                number
                for number in submitted_numbers
                if number > first_missing and number in scheduled_numbers
            )
            if submitted_after_gap:
                raise ValueError(
                    f"第{first_missing}章正文文件不存在，后续第{submitted_after_gap[0]}章已提交，"
                    "已停止，避免章节顺序错误"
                )
            refreshed_days = tuple(
                replace(
                    day,
                    chapters=tuple(
                        source_by_number.get(chapter.number, chapter)
                        for chapter in day.chapters
                        if chapter.number in submitted_numbers
                        or chapter.number < first_missing
                    ),
                )
                for day in state.schedule
            )
            refreshed = replace(
                state,
                schedule=tuple(day for day in refreshed_days if day.chapters),
                confirmation=None,
            )
            self._repository.save_state(refreshed)
            return refreshed

        refreshed_days = tuple(
            replace(
                day,
                chapters=tuple(
                    source_by_number.get(chapter.number, chapter) for chapter in day.chapters
                ),
            )
            for day in state.schedule
        )
        if refreshed_days != state.schedule:
            state = replace(state, schedule=refreshed_days, confirmation=None)
            self._repository.save_state(state)

        start_number = min(scheduled_numbers)
        chapters = contiguous_chapters(
            source_chapters, start_number, book.publish_end_chapter
        )
        missing = [
            chapter
            for chapter in chapters
            if (
                chapter.number not in scheduled_numbers
                and chapter.number not in submitted_numbers
            )
        ]
        if not missing:
            return state

        remaining_numbers = scheduled_numbers - set(state.submitted_chapters)
        first_missing = missing[0].number
        if remaining_numbers and first_missing > min(remaining_numbers):
            return state

        submitted_after_gap = sorted(
            number
            for number in state.submitted_chapters
            if number > first_missing and number in scheduled_numbers
        )
        if submitted_after_gap:
            raise ValueError(
                f"第{first_missing}章未进入排程，后续第{submitted_after_gap[0]}章已提交，"
                "已停止，避免章节顺序错误"
            )

        rebuilt = tuple(build_schedule(chapters, book, book.publish_start_date))
        refreshed = replace(state, schedule=rebuilt, confirmation=None)
        self._repository.save_state(refreshed)
        return refreshed

    @staticmethod
    def _fit_remote_daily_limit(
        book: BookConfig,
        day: ScheduledDay,
        remote_chapters: list[RemoteChapter],
    ) -> ScheduledDay:
        local_character_counts = {
            chapter.number: chapter.character_count
            for chapter in scan_chapters(book.source_dir)
        }
        first_chapter = day.chapters[0].number
        previous_dates = [
            chapter.publish_at.date()
            for chapter in remote_chapters
            if (
                chapter.chapter_number < first_chapter
                and chapter.publish_at is not None
            )
        ]
        publish_date = max(
            day.publish_at.date(), max(previous_dates, default=day.publish_at.date())
        )
        later_chapters = [
            chapter
            for chapter in remote_chapters
            if (
                chapter.chapter_number > first_chapter
                and chapter.publish_at is not None
            )
        ]
        latest_allowed = min(
            (chapter.publish_at.date() for chapter in later_chapters), default=None
        )

        while latest_allowed is None or publish_date <= latest_allowed:
            occupied = [
                chapter
                for chapter in remote_chapters
                if chapter.publish_at is not None
                and chapter.publish_at.date() == publish_date
            ]
            used = (
                sum(
                    chapter.character_count
                    or local_character_counts.get(chapter.chapter_number, 0)
                    for chapter in occupied
                )
                if book.mode is PublishMode.WORDS
                else len(occupied)
            )
            available = book.limit - used
            selected: list[Chapter] = []
            for chapter in day.chapters:
                amount = (
                    chapter.character_count
                    if book.mode is PublishMode.WORDS
                    else 1
                )
                if amount > available:
                    break
                selected.append(chapter)
                available -= amount
            if selected:
                return replace(
                    day,
                    chapters=tuple(selected),
                    publish_at=datetime.combine(publish_date, day.publish_at.time()),
                )
            publish_date += timedelta(days=1)

        blocking = min(later_chapters, key=lambda chapter: chapter.publish_at)
        raise ValueError(
            f"第{first_chapter}章无法在第{blocking.chapter_number}章之前安排，"
            "请先调整后续已定时章节"
        )
