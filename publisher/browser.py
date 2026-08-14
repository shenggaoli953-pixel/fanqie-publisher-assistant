from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import re
import subprocess
import time
from collections.abc import Callable
from typing import Protocol

from publisher.models import RemoteChapter


_CHAPTER_HEADING = re.compile(r"^第\s*([0-9]+|[零一二三四五六七八九十百千两]+)\s*章\s*(.*)$")
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
    for action in ("继续发布", "提交", "继续", "确认"):
        if action in button_names:
            return action
    non_editing_actions = {
        action
        for action in button_names
        if action not in {"修改", "去修改", "取消", "返回", "关闭"}
    }
    if len(non_editing_actions) == 1:
        return next(iter(non_editing_actions))
    return None


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
        dialog = EdgePublisherGateway._publish_settings_dialog(page)
        if dialog.count() == 0:
            EdgePublisherGateway._open_publish_entry(page)
        dialog = EdgePublisherGateway._wait_for_publish_settings_dialog(page)
        EdgePublisherGateway._configure_publish_settings(
            page, dialog, publish_at, ai_generated
        )
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
    def _confirm_publish(page, confirm) -> tuple[PublishOutcome, str]:
        try:
            with page.expect_response(
                lambda response: "/api/author/publish_article/v0/" in response.url,
                timeout=15000,
            ) as response_info:
                confirm.click()
                EdgePublisherGateway._submit_non_chapter_notice_if_present(page)
            response = response_info.value
            return interpret_publish_response(response.json())
        except Exception:
            EdgePublisherGateway._submit_non_chapter_notice_if_present(page, timeout_ms=500)
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
