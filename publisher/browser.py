from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import re
import subprocess
import time
from collections.abc import Callable
from typing import Protocol

from publisher.dialogs import choose_publish_progress_action
from publisher.models import RemoteChapter


_CHAPTER_HEADING = re.compile(
    r"^第\s*([0-9]+|[零一二三四五六七八九十百千两]+)\s*(?:章|回|节|话)\s*(.*)$"
)
_REMOTE_CHAPTER_NUMBER = re.compile(r"第\s*(\d+)\s*章")
_REMOTE_PUBLISH_AT = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}")
_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}


class PreflightStatus(StrEnum):
    NOT_LAUNCHED = "not_launched"
    NOT_LOGGED_IN = "not_logged_in"
    BOOK_NOT_SELECTED = "book_not_selected"
    READY = "ready"
    BLOCKED = "blocked"


class PublishOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    DAILY_LIMIT = "daily_limit"
    UNKNOWN = "unknown"


class PublishBlockedError(RuntimeError):
    pass


class PublishUnknownError(PublishBlockedError):
    pass


@dataclass(frozen=True)
class PublishDraft:
    chapter_number: int
    title: str
    body: str
    publish_at: datetime
    ai_generated: bool = True


@dataclass(frozen=True)
class DraftFields:
    chapter_number: str
    title: str
    body: str


def draft_fields(draft: PublishDraft) -> DraftFields:
    if draft.chapter_number <= 0:
        raise ValueError("章节号必须大于 0")
    title = draft.title.strip()
    if not title:
        raise ValueError("章节标题不能为空")
    body = _prepare_body(draft.body, draft.chapter_number, title)
    if not body:
        raise ValueError("章节正文不能为空")
    return DraftFields(
        chapter_number=str(draft.chapter_number),
        title=title,
        body=body,
    )


def _prepare_body(body: str, chapter_number: int, title: str) -> str:
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _matches_chapter_heading(lines[0], chapter_number, title):
        lines.pop(0)
    return "\n".join(line.strip() for line in lines if line.strip())


def _matches_chapter_heading(line: str, chapter_number: int, title: str) -> bool:
    match = _CHAPTER_HEADING.match(line.strip())
    if match is None:
        return False
    try:
        parsed_number = _parse_chapter_number(match.group(1))
    except ValueError:
        return False
    return (
        parsed_number == chapter_number
        and _normalize_title(match.group(2)) == _normalize_title(title)
    )


def _parse_chapter_number(value: str) -> int:
    if value.isascii() and value.isdecimal():
        return int(value)
    total = 0
    current = 0
    for character in value:
        if character in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[character]
            continue
        unit = _CHINESE_UNITS.get(character)
        if unit is None:
            raise ValueError("无法识别中文章节号")
        total += max(current, 1) * unit
        current = 0
    return total + current


def _normalize_title(value: str) -> str:
    return re.sub(r"[\s:：、_—-]+", "", value)


def remote_row_has_chapter(row_text: str, draft: PublishDraft) -> bool:
    return _remote_chapter_name(draft) in row_text


def remote_chapter_numbers(rows: list[str]) -> set[int]:
    return {
        int(match.group(1))
        for row in rows
        for match in _REMOTE_CHAPTER_NUMBER.finditer(row)
    }


def remote_chapters(rows: list[str]) -> list[RemoteChapter]:
    chapters: list[RemoteChapter] = []
    for row in rows:
        number_match = _REMOTE_CHAPTER_NUMBER.search(row)
        if number_match is None:
            continue
        fields = [field.strip() for field in row.splitlines() if field.strip()]
        character_count = next(
            (int(field) for field in fields[1:] if field.isdecimal()), 0
        )
        publish_match = _REMOTE_PUBLISH_AT.search(row)
        publish_at = (
            datetime.strptime(publish_match.group(), "%Y-%m-%d %H:%M")
            if publish_match is not None
            else None
        )
        chapters.append(
            RemoteChapter(
                chapter_number=int(number_match.group(1)),
                character_count=character_count,
                publish_at=publish_at,
            )
        )
    return chapters


def _remote_chapter_name(draft: PublishDraft) -> str:
    fields = draft_fields(draft)
    return f"第{fields.chapter_number}章 {fields.title}"


def schedule_values(publish_at: datetime) -> tuple[str, str]:
    return (
        publish_at.strftime("%Y-%m-%d"),
        publish_at.strftime("%H:%M"),
    )


def choose_continue_action(button_names: set[str]) -> str | None:
    return choose_publish_progress_action("", button_names)


def interpret_publish_response(payload: object) -> tuple[PublishOutcome, str]:
    if not isinstance(payload, dict):
        return PublishOutcome.UNKNOWN, "发布接口没有返回可识别结果"
    message = str(payload.get("message") or payload.get("msg") or "").strip()
    code = payload.get("code")
    if code == 0:
        return PublishOutcome.SUCCESS, message or "发布成功"
    if code is None:
        return PublishOutcome.UNKNOWN, message or "发布接口没有返回结果代码"
    if any(indicator in message for indicator in ("每日上限", "字数上限", "超出每日")):
        return PublishOutcome.DAILY_LIMIT, message
    return PublishOutcome.FAILED, message or f"发布接口返回代码 {code}"


def edge_launch_arguments(
    edge_path: Path,
    profile_dir: Path,
    author_url: str,
    *,
    cdp_port: int = 9222,
) -> list[str]:
    return [
        str(edge_path),
        "--new-window",
        "--window-position=100,80",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile_dir.resolve()}",
        author_url,
    ]


@dataclass(frozen=True)
class SubmissionResult:
    chapter_number: int
    success: bool
    blocked: bool = False
    error: str | None = None
    verified: bool = False
    cancelled: bool = False


@dataclass(frozen=True)
class PreflightResult:
    status: PreflightStatus
    message: str


@dataclass(frozen=True)
class ManagedChapter:
    chapter_number: int
    status: str
    editor_path: str


@dataclass(frozen=True)
class ScheduleChange:
    chapter_number: int
    publish_at: datetime


def managed_chapters_from_rows(
    rows: list[tuple[str, str | None]],
) -> list[ManagedChapter]:
    managed: list[ManagedChapter] = []
    numbers: set[int] = set()
    for row_text, editor_path in rows:
        match = _REMOTE_CHAPTER_NUMBER.search(row_text)
        if match is None:
            continue
        chapter_number = int(match.group(1))
        if chapter_number in numbers:
            raise PublishBlockedError(f"后台章节序号重复：第{chapter_number}章")
        if editor_path is None or "/publish/" not in editor_path:
            raise PublishBlockedError(f"第{chapter_number}章没有可用编辑入口")
        numbers.add(chapter_number)
        managed.append(
            ManagedChapter(
                chapter_number=chapter_number,
                status=_managed_chapter_status(row_text),
                editor_path=editor_path,
            )
        )
    return managed


def _managed_chapter_status(row_text: str) -> str:
    if "待发布" in row_text:
        return "pending"
    if "审核中" in row_text:
        return "reviewing"
    if "已发布" in row_text:
        return "published"
    if "草稿" in row_text:
        return "draft"
    return "unknown"


@dataclass(frozen=True)
class EdgeSelectors:
    title_input: str | None = None
    body_editor: str | None = None
    schedule_toggle: str | None = None
    publish_time_input: str | None = None
    submit_button: str | None = None

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.title_input,
                self.body_editor,
                self.schedule_toggle,
                self.publish_time_input,
                self.submit_button,
            )
        )


class PublisherGateway(Protocol):
    def submit_batch(
        self,
        drafts: list[PublishDraft],
        book_name: str | None = None,
        *,
        known_remote_numbers: set[int] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]: ...


class FakePublisherGateway:
    def __init__(self, block_at: int | None = None, reason: str = "blocked") -> None:
        self._block_at = block_at
        self._reason = reason

    def submit_batch(
        self,
        drafts: list[PublishDraft],
        book_name: str | None = None,
        *,
        known_remote_numbers: set[int] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        results: list[SubmissionResult] = []
        for position, draft in enumerate(drafts, start=1):
            if should_stop is not None and should_stop():
                results.append(
                    SubmissionResult(
                        chapter_number=draft.chapter_number,
                        success=False,
                        cancelled=True,
                    )
                )
                break
            if self._block_at == position:
                results.append(
                    SubmissionResult(
                        chapter_number=draft.chapter_number,
                        success=False,
                        blocked=True,
                        error=self._reason,
                    )
                )
                break
            results.append(SubmissionResult(chapter_number=draft.chapter_number, success=True))
        return results

class EdgePublisherGateway:
    _DEFAULT_AUTHOR_URL = "https://fanqienovel.com/writer/zone/"
    _BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"

    def __init__(
        self,
        profile_dir: Path,
        author_url: str = _DEFAULT_AUTHOR_URL,
        selectors: EdgeSelectors | None = None,
        cdp_endpoint: str | None = None,
        cdp_port: int = 9222,
    ) -> None:
        self._profile_dir = profile_dir
        self._author_url = author_url
        self._selectors = selectors or EdgeSelectors()
        self._cdp_port = cdp_port
        self._cdp_endpoint = cdp_endpoint or f"http://127.0.0.1:{cdp_port}"
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._manager_url: str | None = None
        self._manager_book_name: str | None = None

    @property
    def current_page(self):
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        return self._page

    def launch(self) -> None:
        from playwright.sync_api import sync_playwright

        if self._page is not None and not self._page.is_closed():
            return
        if self._page is not None:
            self.close()
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(
                self._cdp_endpoint
            )
        except Exception:
            edge_path = self._find_edge()
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = 7
            subprocess.Popen(
                edge_launch_arguments(
                    edge_path,
                    self._profile_dir,
                    self._author_url,
                    cdp_port=self._cdp_port,
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startup_info,
            )
            self._browser = self._connect_after_launch()
        if not self._browser.contexts:
            raise PublishBlockedError("未能连接到 Edge 浏览器配置")
        self._context = self._browser.contexts[0]
        pages = [page for page in self._context.pages if not page.is_closed()]
        if pages:
            self._page = pages[-1]
            for stale_page in pages[:-1]:
                try:
                    stale_page.close()
                except Exception:
                    pass
        else:
            self._page = self._context.new_page()
        self._page.goto(self._author_url, wait_until="domcontentloaded")

    def preflight(self, book_name: str | None = None) -> PreflightResult:
        if self._page is None:
            return PreflightResult(PreflightStatus.NOT_LAUNCHED, "尚未打开 Edge")
        if book_name is None:
            return PreflightResult(PreflightStatus.BOOK_NOT_SELECTED, "请先选择本地作品")
        try:
            self._open_chapter_manager(book_name)
        except PublishBlockedError as error:
            return PreflightResult(PreflightStatus.BLOCKED, str(error))
        except Exception:
            return PreflightResult(
                PreflightStatus.BLOCKED,
                "无法打开番茄章节管理页，请确认 Edge 已完成登录",
            )
        return PreflightResult(PreflightStatus.READY, "已连接番茄后台并找到作品")

    def submit_batch(
        self,
        drafts: list[PublishDraft],
        book_name: str | None = None,
        *,
        known_remote_numbers: set[int] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        if not book_name:
            raise PublishBlockedError("未选择番茄作品")
        self._open_chapter_manager(book_name)
        known_numbers = (
            set(known_remote_numbers)
            if known_remote_numbers is not None
            else self.existing_remote_chapter_numbers()
        )
        results: list[SubmissionResult] = []
        for draft in drafts:
            if should_stop is not None and should_stop():
                results.append(
                    SubmissionResult(
                        chapter_number=draft.chapter_number,
                        success=False,
                        cancelled=True,
                    )
                )
                break
            success = False
            for attempt in range(2):
                try:
                    if draft.chapter_number in known_numbers:
                        success = True
                        break
                    self._submit_one(draft)
                    if not self._return_to_manager_after_submission(book_name, draft):
                        raise PublishUnknownError(
                            f"提交后未在章节管理列表找到第{draft.chapter_number}章"
                        )
                    known_numbers.add(draft.chapter_number)
                    success = True
                    break
                except PublishUnknownError as error:
                    try:
                        if self._return_to_manager_after_submission(book_name, draft):
                            known_numbers.add(draft.chapter_number)
                            success = True
                            break
                    except Exception:
                        pass
                    if attempt == 0:
                        continue
                    results.append(
                        SubmissionResult(
                            chapter_number=draft.chapter_number,
                            success=False,
                            blocked=True,
                            error=str(error),
                        )
                    )
                    break
                except PublishBlockedError as error:
                    results.append(
                        SubmissionResult(
                            chapter_number=draft.chapter_number,
                            success=False,
                            blocked=True,
                            error=str(error),
                        )
                    )
                    break
                except Exception as error:
                    results.append(
                        SubmissionResult(
                            chapter_number=draft.chapter_number,
                            success=False,
                            blocked=True,
                            error=f"番茄后台操作失败: {error}",
                        )
                    )
                    break
            if not success:
                break
            results.append(
                SubmissionResult(
                    chapter_number=draft.chapter_number,
                    success=True,
                    verified=True,
                )
            )
        return results

    def submit_immediately(
        self,
        drafts: list[PublishDraft],
        book_name: str | None = None,
        *,
        known_remote_numbers: set[int] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        self._require_active_book(book_name)
        known_numbers = (
            set(known_remote_numbers)
            if known_remote_numbers is not None
            else self.existing_remote_chapter_numbers()
        )

        def submit(draft: PublishDraft) -> None:
            if draft.chapter_number in known_numbers:
                return
            self._open_chapter_manager(book_name)
            self._submit_immediate_one(draft)
            known_numbers.add(draft.chapter_number)

        return self._run_items(drafts, submit, should_stop)

    def save_drafts(
        self,
        drafts: list[PublishDraft],
        book_name: str | None = None,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        self._require_active_book(book_name)
        draft_ids: set[str] = set()

        def save(draft: PublishDraft) -> None:
            self._open_chapter_manager(book_name)
            page = self._new_chapter_page()
            self._fill_draft_fields(page, draft_fields(draft))
            draft_id = self._save_draft(page)
            if draft_id in draft_ids:
                raise PublishBlockedError("后台复用了草稿标识，已停止避免覆盖前一章")
            draft_ids.add(draft_id)

        return self._run_items(drafts, save, should_stop)

    def update_existing(
        self,
        drafts: list[PublishDraft],
        managed: list[ManagedChapter],
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        by_number = {chapter.chapter_number: chapter for chapter in managed}

        def update(draft: PublishDraft) -> None:
            chapter = by_number.get(draft.chapter_number)
            if chapter is None:
                raise PublishBlockedError(f"后台未找到第{draft.chapter_number}章")
            if chapter.status in {"reviewing", "unknown"}:
                raise PublishBlockedError(
                    f"第{draft.chapter_number}章当前状态不允许自动修改"
                )
            self._submit_existing_content(draft, chapter)

        return self._run_items(drafts, update, should_stop)

    def reschedule_existing(
        self,
        changes: list[ScheduleChange],
        managed: list[ManagedChapter],
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[SubmissionResult]:
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        by_number = {chapter.chapter_number: chapter for chapter in managed}

        def reschedule(change: ScheduleChange) -> None:
            chapter = by_number.get(change.chapter_number)
            if chapter is None:
                raise PublishBlockedError(f"后台未找到第{change.chapter_number}章")
            if chapter.status != "pending":
                raise PublishBlockedError(
                    f"第{change.chapter_number}章不是待发布状态，已停止改排期"
                )
            self._reschedule_one(change, chapter)

        return self._run_items(changes, reschedule, should_stop)

    def _require_active_book(self, book_name: str | None) -> None:
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        if not book_name:
            raise PublishBlockedError("未选择番茄作品")

    @staticmethod
    def _run_items(items, action, should_stop) -> list[SubmissionResult]:
        results: list[SubmissionResult] = []
        for item in items:
            chapter_number = item.chapter_number
            if should_stop is not None and should_stop():
                results.append(
                    SubmissionResult(
                        chapter_number=chapter_number,
                        success=False,
                        cancelled=True,
                    )
                )
                break
            try:
                action(item)
            except PublishBlockedError as error:
                results.append(
                    SubmissionResult(
                        chapter_number=chapter_number,
                        success=False,
                        blocked=True,
                        error=str(error),
                    )
                )
                break
            except Exception as error:
                results.append(
                    SubmissionResult(
                        chapter_number=chapter_number,
                        success=False,
                        blocked=True,
                        error=f"番茄后台操作失败: {error}",
                    )
                )
                break
            results.append(
                SubmissionResult(
                    chapter_number=chapter_number,
                    success=True,
                    verified=True,
                )
            )
        return results

    def close(self) -> None:
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    @staticmethod
    def _find_edge() -> Path:
        candidates = (
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise PublishBlockedError("未找到 Microsoft Edge")

    def _connect_after_launch(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                return self._playwright.chromium.connect_over_cdp(self._cdp_endpoint)
            except Exception:
                time.sleep(0.5)
        raise PublishBlockedError("Edge 启动后未能连接，请稍后再试")

    def _open_chapter_manager(self, book_name: str) -> None:
        if self._page is None:
            raise PublishBlockedError("请先打开 Edge")
        if self._manager_url is not None and self._manager_book_name == book_name:
            self._page.goto(self._manager_url, wait_until="domcontentloaded")
            self._remote_rows()
            return
        self._page.goto(self._BOOK_MANAGE_URL, wait_until="domcontentloaded")
        card = self._page.locator(".info-content").filter(has_text=book_name).first
        try:
            card.wait_for(state="visible", timeout=6000)
        except Exception as error:
            raise PublishBlockedError(f"后台未找到作品：{book_name}")
        chapter_button = card.get_by_role("button", name="章节管理", exact=True)
        try:
            chapter_button.wait_for(state="visible", timeout=3000)
        except Exception as error:
            raise PublishBlockedError("未找到作品的章节管理入口")
        origin_page = self._page
        pages_before = set(self._context.pages) if self._context is not None else set()
        chapter_button.focus()
        self._page.keyboard.press("Enter")
        deadline = time.monotonic() + 6
        manager_pages = []
        while time.monotonic() < deadline and not manager_pages:
            manager_pages = [
                page
                for page in (self._context.pages if self._context is not None else [])
                if page not in pages_before and "/chapter-manage/" in page.url
            ]
            if not manager_pages and "/chapter-manage/" in self._page.url:
                manager_pages = [self._page]
            if not manager_pages:
                time.sleep(0.2)
        if not manager_pages:
            raise PublishBlockedError("无法打开作品章节管理页")
        self._page = manager_pages[-1]
        self._page.wait_for_load_state("domcontentloaded")
        self._manager_url = self._page.url
        self._manager_book_name = book_name
        if origin_page is not self._page:
            try:
                origin_page.close()
            except Exception:
                pass

    def _submit_one(self, draft: PublishDraft) -> None:
        self._reject_existing_remote_chapter(draft)
        fields = draft_fields(draft)
        page = self._new_chapter_page()
        self._fill_draft_fields(page, fields)
        page.get_by_role("button", name="下一步", exact=True).click()
        self._submit_non_chapter_notice_if_present(page)
        self._submit_typo_warning_if_present(page)
        self._run_comprehensive_check(page)
        self._open_publish_settings(page, draft.publish_at, draft.ai_generated)

    def _submit_immediate_one(self, draft: PublishDraft) -> None:
        fields = draft_fields(draft)
        page = self._new_chapter_page()
        self._fill_draft_fields(page, fields)
        dialog = self._advance_editor(page, run_check=True)
        self._configure_immediate_settings(dialog, draft.ai_generated)
        self._confirm_publish_dialog(page, dialog)

    def _submit_existing_content(
        self, draft: PublishDraft, chapter: ManagedChapter
    ) -> None:
        page = self._open_existing_editor(chapter)
        self._fill_existing_fields(page, draft_fields(draft))
        dialog = self._advance_editor(page, run_check=True)
        self._confirm_publish_dialog(page, dialog)

    def _reschedule_one(
        self, change: ScheduleChange, chapter: ManagedChapter
    ) -> None:
        page = self._open_existing_editor(chapter)
        dialog = self._advance_editor(page, run_check=False)
        self._configure_schedule_settings(page, dialog, change.publish_at)
        self._confirm_publish_dialog(page, dialog)

    def _open_existing_editor(self, chapter: ManagedChapter):
        if self._page is None:
            raise PublishBlockedError("请先打开并登录 Edge")
        editor_url = chapter.editor_path
        if editor_url.startswith("/"):
            editor_url = f"https://fanqienovel.com{editor_url}"
        self._page.goto(editor_url, wait_until="domcontentloaded")
        title_input = self._page.locator("input[placeholder='请输入标题']")
        editor = self._page.locator(".syl-editor-container .ProseMirror").first
        try:
            title_input.wait_for(state="visible", timeout=10000)
            editor.wait_for(state="visible", timeout=10000)
        except Exception as error:
            raise PublishBlockedError(f"第{chapter.chapter_number}章编辑页未成功打开") from error
        return self._page

    @staticmethod
    def _advance_editor(page, *, run_check: bool):
        next_step = page.get_by_role("button", name="下一步", exact=True)
        if next_step.count() == 0 or not next_step.is_visible():
            raise PublishBlockedError("编辑页未找到下一步按钮")
        next_step.click()
        EdgePublisherGateway._submit_non_chapter_notice_if_present(page)
        EdgePublisherGateway._submit_typo_warning_if_present(page)
        if run_check:
            EdgePublisherGateway._run_comprehensive_check(page)
        return EdgePublisherGateway._open_publish_dialog(page)

    @staticmethod
    def _fill_draft_fields(page, fields: DraftFields) -> None:
        serial_input = page.locator("input.serial-input").first
        title_input = page.locator("input[placeholder='请输入标题']")
        editor = page.locator(".syl-editor-container .ProseMirror").first
        for locator in (serial_input, title_input, editor):
            locator.wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(1000)

        editor.focus()
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(fields.body)
        page.wait_for_timeout(700)
        editor_body = EdgePublisherGateway._normalized_editor_body(editor.inner_text())
        if editor_body != fields.body:
            editor.focus()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(fields.body)
            page.wait_for_timeout(700)
            editor_body = EdgePublisherGateway._normalized_editor_body(editor.inner_text())
        if editor_body != fields.body:
            raise PublishBlockedError("章节正文写入后被后台清空，已停止提交")

        for _ in range(2):
            serial_input.fill(fields.chapter_number)
            title_input.fill(fields.title)
            page.wait_for_timeout(500)
            if (
                serial_input.input_value() == fields.chapter_number
                and title_input.input_value().strip() == fields.title
                and EdgePublisherGateway._normalized_editor_body(editor.inner_text())
                == fields.body
            ):
                page.wait_for_timeout(500)
                if (
                    serial_input.input_value() == fields.chapter_number
                    and title_input.input_value().strip() == fields.title
                    and EdgePublisherGateway._normalized_editor_body(editor.inner_text())
                    == fields.body
                ):
                    return
        raise PublishBlockedError("章节号或标题被后台清空，已停止提交")

    @staticmethod
    def _fill_existing_fields(page, fields: DraftFields) -> None:
        title_input = page.locator("input[placeholder='请输入标题']")
        editor = page.locator(".syl-editor-container .ProseMirror").first
        for locator in (title_input, editor):
            locator.wait_for(state="visible", timeout=10000)
        page.wait_for_timeout(1000)

        editor.focus()
        page.keyboard.press("Control+A")
        page.keyboard.insert_text(fields.body)
        page.wait_for_timeout(700)
        editor_body = EdgePublisherGateway._normalized_editor_body(editor.inner_text())
        if editor_body != fields.body:
            editor.focus()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(fields.body)
            page.wait_for_timeout(700)
            editor_body = EdgePublisherGateway._normalized_editor_body(editor.inner_text())
        if editor_body != fields.body:
            raise PublishBlockedError("章节正文写入后被后台清空，已停止修改")

        for _ in range(2):
            title_input.fill(fields.title)
            page.wait_for_timeout(500)
            if (
                title_input.input_value().strip() == fields.title
                and EdgePublisherGateway._normalized_editor_body(editor.inner_text())
                == fields.body
            ):
                page.wait_for_timeout(500)
                if (
                    title_input.input_value().strip() == fields.title
                    and EdgePublisherGateway._normalized_editor_body(editor.inner_text())
                    == fields.body
                ):
                    return
        raise PublishBlockedError("章节标题被后台清空，已停止修改")

    @staticmethod
    def _normalized_editor_body(value: str) -> str:
        return "\n".join(line.strip() for line in value.splitlines() if line.strip())

    def _reject_existing_remote_chapter(self, draft: PublishDraft) -> None:
        rows = self._remote_rows()
        if draft.chapter_number in remote_chapter_numbers(rows):
            raise PublishBlockedError(
                f"后台已有第{draft.chapter_number}章，请把起始章节改为第{draft.chapter_number + 1}章后再提交"
            )

    def existing_remote_chapter_numbers(self) -> set[int]:
        return remote_chapter_numbers(self._all_remote_rows())

    def existing_remote_chapters(self) -> list[RemoteChapter]:
        return remote_chapters(self._all_remote_rows())

    def managed_chapters(self, book_name: str) -> list[ManagedChapter]:
        self._open_chapter_manager(book_name)
        return managed_chapters_from_rows(self._all_managed_rows())

    def _new_chapter_page(self):
        if self._page is None:
            raise PublishBlockedError("未打开章节管理页")
        new_chapter = self._page.get_by_role("link", name="新建章节", exact=True)
        try:
            new_chapter.wait_for(state="visible", timeout=10000)
        except Exception as error:
            raise PublishBlockedError("章节管理页没有新建章节入口") from error
        href = new_chapter.get_attribute("href")
        if not href:
            raise PublishBlockedError("新建章节入口无效")
        self._page.goto(f"https://fanqienovel.com{href}", wait_until="domcontentloaded")
        return self._page

    @staticmethod
    def _submit_typo_warning_if_present(page) -> None:
        page.wait_for_timeout(500)
        typo_dialog = page.get_by_role("dialog").filter(has_text="错别字").last
        if typo_dialog.count():
            button_names = {
                name.strip()
                for name in typo_dialog.get_by_role("button").all_inner_texts()
                if name.strip()
            }
            action = choose_continue_action(button_names)
            if action is None:
                raise PublishBlockedError("错别字提示没有继续发布按钮")
            typo_dialog.get_by_role("button", name=action, exact=True).last.click()

    @staticmethod
    def _run_comprehensive_check(page) -> None:
        page.wait_for_timeout(500)
        if EdgePublisherGateway._publish_settings_dialog(page).count():
            return
        check_dialog = EdgePublisherGateway._comprehensive_check_dialog(page)
        if check_dialog.count() == 0 or not check_dialog.is_visible():
            return
        failure = EdgePublisherGateway._comprehensive_check_failure(
            check_dialog.inner_text()
        )
        if failure is not None:
            raise PublishBlockedError(f"全面检测未完成：{failure}")
        comprehensive = check_dialog.get_by_role(
            "button", name="全面检测", exact=True
        ).last
        if comprehensive.count() == 0 or not comprehensive.is_visible():
            raise PublishBlockedError("全面检测窗口未找到全面检测按钮")
        comprehensive.click()
        try:
            check_dialog.wait_for(state="hidden", timeout=30000)
        except Exception as error:
            if check_dialog.count() and check_dialog.is_visible():
                failure = EdgePublisherGateway._comprehensive_check_failure(
                    check_dialog.inner_text()
                )
                if failure is not None:
                    raise PublishBlockedError(
                        f"全面检测未完成：{failure}"
                    ) from error
            raise PublishBlockedError("全面检测未在 30 秒内完成") from error

    @staticmethod
    def _comprehensive_check_dialog(page):
        return (
            page.get_by_role("dialog")
            .filter(has_text="请选择内容检测方式")
            .last
        )

    @staticmethod
    def _comprehensive_check_failure(text: str) -> str | None:
        for indicator in ("额度不足", "次数已用完", "检测未通过", "检测失败"):
            if indicator in text:
                return indicator
        return None

    @staticmethod
    def _open_publish_settings(
        page, publish_at: datetime, ai_generated: bool
    ) -> None:
        dialog = EdgePublisherGateway._open_publish_dialog(page)
        EdgePublisherGateway._configure_publish_settings(
            page, dialog, publish_at, ai_generated
        )
        EdgePublisherGateway._confirm_publish_dialog(page, dialog)

    @staticmethod
    def _open_publish_dialog(page):
        dialog = EdgePublisherGateway._publish_settings_dialog(page)
        if dialog.count() == 0 or not dialog.is_visible():
            EdgePublisherGateway._open_publish_entry(page)
        return EdgePublisherGateway._wait_for_publish_settings_dialog(page)

    @staticmethod
    def _confirm_publish_dialog(page, dialog) -> None:
        confirm = dialog.get_by_role("button", name="确认发布", exact=True)
        if confirm.count() == 0:
            raise PublishBlockedError("发布设置中未找到确认发布按钮")
        outcome, message = EdgePublisherGateway._confirm_publish(page, confirm)
        if outcome is PublishOutcome.SUCCESS:
            return
        if outcome is PublishOutcome.DAILY_LIMIT:
            raise PublishBlockedError(message or "提交字数超出每日上限")
        if outcome is PublishOutcome.FAILED:
            raise PublishBlockedError(message or "发布失败")
        raise PublishUnknownError(message or "番茄后台未返回明确的发布结果")

    @staticmethod
    def _configure_publish_settings(
        page, dialog, publish_at: datetime, ai_generated: bool
    ) -> None:
        EdgePublisherGateway._configure_schedule_settings(page, dialog, publish_at)
        EdgePublisherGateway._configure_ai_declaration(dialog, ai_generated)

    @staticmethod
    def _configure_schedule_settings(page, dialog, publish_at: datetime) -> None:
        schedule_switch = dialog.get_by_role("switch").last
        if schedule_switch.count() == 0:
            raise PublishBlockedError("发布设置中未找到定时开关")
        if schedule_switch.get_attribute("aria-checked") != "true":
            schedule_switch.click()
        if schedule_switch.get_attribute("aria-checked") != "true":
            raise PublishBlockedError("定时发布开关未成功开启")
        date_input = dialog.locator("input[placeholder='请选择日期']").first
        time_input = dialog.locator("input[placeholder='请选择时间']").first
        try:
            date_input.wait_for(state="visible", timeout=5000)
            time_input.wait_for(state="visible", timeout=5000)
        except Exception as error:
            raise PublishBlockedError("发布设置中未出现日期或时间输入框") from error
        publish_date, publish_time = schedule_values(publish_at)
        date_input.fill(publish_date)
        EdgePublisherGateway._dismiss_picker_popup(page, date_input)
        time_input.fill(publish_time)
        EdgePublisherGateway._dismiss_picker_popup(page, time_input)
        if (
            date_input.input_value() != publish_date
            or time_input.input_value() != publish_time
        ):
            raise PublishBlockedError("定时发布日期或时间未成功写入")

    @staticmethod
    def _configure_immediate_settings(dialog, ai_generated: bool) -> None:
        schedule_switch = dialog.get_by_role("switch").last
        if schedule_switch.count() == 0:
            raise PublishBlockedError("发布设置中未找到定时开关")
        if schedule_switch.get_attribute("aria-checked") == "true":
            schedule_switch.click()
        if schedule_switch.get_attribute("aria-checked") == "true":
            raise PublishBlockedError("定时发布开关未成功关闭")
        EdgePublisherGateway._configure_ai_declaration(dialog, ai_generated)

    @staticmethod
    def _configure_ai_declaration(dialog, ai_generated: bool) -> None:
        ai_value = "1" if ai_generated else "2"
        ai_declaration = dialog.locator(
            f"input[type='radio'][value='{ai_value}']"
        ).last
        if ai_declaration.count() == 0:
            raise PublishBlockedError("发布设置中未找到 AI 声明")
        if not ai_declaration.is_checked():
            ai_declaration.locator("xpath=..").click(force=True)
        if not ai_declaration.is_checked():
            raise PublishBlockedError("AI 声明未成功设置")

    @staticmethod
    def _save_draft(page) -> str:
        save = page.get_by_role("button", name="存草稿", exact=True).last
        if save.count() == 0 or not save.is_visible():
            raise PublishBlockedError("编辑页未找到存草稿按钮")
        save.click()
        saved = page.get_by_text("已保存", exact=True).last
        for _ in range(30):
            if saved.count() and saved.is_visible():
                draft_id = EdgePublisherGateway._draft_identifier(page.url)
                if draft_id is None:
                    raise PublishBlockedError("草稿保存后没有独立标识")
                return draft_id
            page.wait_for_timeout(200)
        raise PublishBlockedError("草稿未出现保存成功提示")

    @staticmethod
    def _draft_identifier(url: str) -> str | None:
        match = re.search(r"/publish/([^/?#]+)", url)
        return match.group(1) if match is not None else None

    @staticmethod
    def _confirm_publish(page, confirm) -> tuple[PublishOutcome, str]:
        try:
            with page.expect_response(
                lambda response: "/api/author/publish_article/v0/" in response.url,
                timeout=15000,
            ) as response_info:
                confirm.click()
                EdgePublisherGateway._submit_non_chapter_notice_if_present(page)
                EdgePublisherGateway._advance_visible_publish_dialog(page)
            response = response_info.value
            return interpret_publish_response(response.json())
        except Exception:
            EdgePublisherGateway._submit_non_chapter_notice_if_present(page, timeout_ms=500)
            EdgePublisherGateway._advance_visible_publish_dialog(page)
            body_text = page.locator("body").inner_text()
            for indicator in ("提交字数超出每日上限", "额度不足", "验证码", "发布失败"):
                if indicator in body_text:
                    if "上限" in indicator:
                        return PublishOutcome.DAILY_LIMIT, indicator
                    return PublishOutcome.FAILED, indicator
            return PublishOutcome.UNKNOWN, "确认发布后未收到番茄接口结果"

    def _return_to_manager_after_submission(
        self, book_name: str, draft: PublishDraft
    ) -> bool:
        self._open_chapter_manager(book_name)
        return draft.chapter_number in self._visible_remote_chapter_numbers()

    def _visible_remote_chapter_numbers(self) -> set[int]:
        return remote_chapter_numbers(self._remote_rows())

    @staticmethod
    def _open_publish_entry(page) -> None:
        publish = page.get_by_role("button", name="发布", exact=True).last
        if publish.count() and publish.is_visible():
            publish.click()
            return

        EdgePublisherGateway._submit_non_chapter_notice_if_present(
            page,
            timeout_ms=5000,
        )
        for _ in range(30):
            dialog = EdgePublisherGateway._publish_settings_dialog(page)
            if dialog.count() and dialog.is_visible():
                return
            publish = page.get_by_role("button", name="发布", exact=True).last
            if publish.count() and publish.is_visible():
                publish.click()
                return
            if EdgePublisherGateway._advance_visible_publish_dialog(page):
                page.wait_for_timeout(300)
                continue
            page.wait_for_timeout(100)
        raise PublishBlockedError("未出现发布设置入口")

    @staticmethod
    def _publish_settings_dialog(page):
        return page.get_by_role("dialog").filter(has_text="发布设置").last

    @staticmethod
    def _wait_for_publish_settings_dialog(page):
        dialog = EdgePublisherGateway._publish_settings_dialog(page)
        try:
            dialog.wait_for(state="visible", timeout=5000)
        except Exception as error:
            raise PublishBlockedError("未出现发布设置入口") from error
        return dialog

    @staticmethod
    def _wait_for_publish_settings_to_close(dialog) -> None:
        try:
            dialog.wait_for(state="hidden", timeout=5000)
        except Exception as error:
            raise PublishBlockedError("确认发布后页面未完成，已停止继续下一章") from error

    @staticmethod
    def _submit_non_chapter_notice_if_present(page, timeout_ms: int = 2000) -> None:
        notice = (
            page.get_by_role("dialog")
            .filter(has_text="非章节内容请使用“作者有话说”功能")
            .last
        )
        for _ in range(max(1, timeout_ms // 100)):
            if notice.count() and notice.is_visible():
                submit = notice.get_by_role("button", name="提交", exact=True).last
                if submit.count() == 0 or not submit.is_visible():
                    raise PublishBlockedError("非章节内容提示未找到提交按钮")
                submit.click()
                return
            page.wait_for_timeout(100)

    @staticmethod
    def _advance_visible_publish_dialog(page) -> bool:
        dialogs = page.get_by_role("dialog")
        try:
            dialog_count = dialogs.count()
        except Exception:
            return False
        for index in range(dialog_count - 1, -1, -1):
            dialog = dialogs.nth(index) if hasattr(dialogs, "nth") else dialogs.last
            try:
                if not dialog.is_visible():
                    continue
                buttons = dialog.get_by_role("button")
                button_names = {
                    name.strip() for name in buttons.all_inner_texts() if name.strip()
                }
                action = choose_publish_progress_action(
                    dialog.inner_text(), button_names
                )
                if action is None:
                    continue
                button = dialog.get_by_role(
                    "button", name=action, exact=True
                ).last
                if button.count() and button.is_visible():
                    button.click()
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _dismiss_picker_popup(page, input_locator) -> None:
        input_locator.press("Enter")
        input_locator.blur()
        page.wait_for_timeout(100)
        for _ in range(3):
            has_visible_picker = any(
                page.locator(selector).last.is_visible()
                for selector in (".arco-picker-date", ".arco-picker-time")
            )
            if not has_visible_picker:
                return
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)
        raise PublishBlockedError("日期或时间选择弹层未关闭，已停止提交")

    def _remote_rows(self) -> list[str]:
        if self._page is None:
            raise PublishBlockedError("无法检查后台已有章节")
        rows = self._page.locator("tr")
        empty_state = self._page.get_by_text("暂无章节", exact=False).last
        if rows.count() == 0 and self._chapter_manager_is_empty(empty_state):
            return []
        try:
            rows.first.wait_for(state="visible", timeout=6000)
        except Exception as error:
            if self._chapter_manager_is_empty(empty_state):
                return []
            raise PublishBlockedError("章节管理表未加载，已停止提交")
        return rows.all_inner_texts()

    def _chapter_manager_is_empty(self, empty_state) -> bool:
        if empty_state.count() and empty_state.is_visible():
            return True
        try:
            new_chapter = self._page.get_by_role(
                "link", name="新建章节", exact=True
            )
            return (
                "/chapter-manage/" in self._page.url
                and new_chapter.count()
                and new_chapter.is_visible()
            )
        except Exception:
            return False

    def _all_remote_rows(self) -> list[str]:
        if self._page is None:
            raise PublishBlockedError("无法检查后台已有章节")
        all_rows = self._remote_rows()
        pagination = self._page.locator(".arco-pagination").last
        if pagination.count() == 0:
            return all_rows
        first_page = pagination.get_by_text("1", exact=True).last
        if first_page.count() and "arco-pagination-item-active" not in (
            first_page.get_attribute("class") or ""
        ):
            previous_rows = tuple(all_rows)
            previous_page = self._active_page_number()
            first_page.click()
            all_rows = self._wait_for_remote_page_change(
                previous_page,
                previous_rows,
            )
        next_page = pagination.locator(".arco-pagination-item-next").last
        if next_page.count() == 0:
            raise PublishBlockedError("章节列表分页无法读取，已停止提交")

        while "arco-pagination-item-disabled" not in (
            next_page.get_attribute("class") or ""
        ):
            previous_rows = tuple(self._remote_rows())
            previous_page = self._active_page_number()
            next_page.click()
            all_rows.extend(
                self._wait_for_remote_page_change(previous_page, previous_rows)
            )

        return all_rows

    def _managed_rows(self) -> list[tuple[str, str | None]]:
        row_texts = self._remote_rows()
        rows = self._page.locator("tr")
        managed_rows: list[tuple[str, str | None]] = []
        for index, row_text in enumerate(row_texts):
            row = rows.nth(index)
            paths = row.locator("a").evaluate_all(
                "items => items.map(item => item.getAttribute('href') || '')"
                ".filter(value => value.includes('/publish/'))"
            )
            managed_rows.append((row_text, paths[0] if paths else None))
        return managed_rows

    def _all_managed_rows(self) -> list[tuple[str, str | None]]:
        if self._page is None:
            raise PublishBlockedError("无法检查后台已有章节")
        all_rows = self._managed_rows()
        pagination = self._page.locator(".arco-pagination").last
        if pagination.count() == 0:
            return all_rows
        first_page = pagination.get_by_text("1", exact=True).last
        if first_page.count() and "arco-pagination-item-active" not in (
            first_page.get_attribute("class") or ""
        ):
            previous_rows = tuple(all_rows)
            previous_page = self._active_page_number()
            first_page.click()
            all_rows = self._wait_for_managed_page_change(
                previous_page,
                previous_rows,
            )
        next_page = pagination.locator(".arco-pagination-item-next").last
        if next_page.count() == 0:
            raise PublishBlockedError("章节列表分页无法读取，已停止提交")
        while "arco-pagination-item-disabled" not in (
            next_page.get_attribute("class") or ""
        ):
            previous_rows = tuple(self._managed_rows())
            previous_page = self._active_page_number()
            next_page.click()
            all_rows.extend(
                self._wait_for_managed_page_change(previous_page, previous_rows)
            )
        return all_rows

    def _active_page_number(self) -> int | None:
        try:
            active = self._page.locator(".arco-pagination-item-active").last
            text = active.inner_text().strip()
            return int(text) if text.isdecimal() else None
        except Exception:
            return None

    def _wait_for_remote_page_change(
        self,
        previous_page: int | None,
        previous_rows: tuple[str, ...],
    ) -> list[str]:
        deadline = time.monotonic() + 6
        candidate: tuple[str, ...] | None = None
        stable_reads = 0
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(120)
            rows = tuple(self._remote_rows())
            active_page = self._active_page_number()
            page_changed = (
                previous_page is None
                or active_page is None
                or active_page != previous_page
            )
            if page_changed and rows != previous_rows:
                if rows == candidate:
                    stable_reads += 1
                else:
                    candidate = rows
                    stable_reads = 1
                if stable_reads >= 2:
                    return list(rows)
            else:
                candidate = None
                stable_reads = 0
        raise PublishBlockedError("章节列表翻页未完成，已停止读取")

    def _wait_for_managed_page_change(
        self,
        previous_page: int | None,
        previous_rows: tuple[tuple[str, str | None], ...],
    ) -> list[tuple[str, str | None]]:
        deadline = time.monotonic() + 6
        candidate: tuple[tuple[str, str | None], ...] | None = None
        stable_reads = 0
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(120)
            rows = tuple(self._managed_rows())
            active_page = self._active_page_number()
            page_changed = (
                previous_page is None
                or active_page is None
                or active_page != previous_page
            )
            if page_changed and rows != previous_rows:
                if rows == candidate:
                    stable_reads += 1
                else:
                    candidate = rows
                    stable_reads = 1
                if stable_reads >= 2:
                    return list(rows)
            else:
                candidate = None
                stable_reads = 0
        raise PublishBlockedError("章节列表翻页未完成，已停止读取")
