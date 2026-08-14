from datetime import datetime
import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

from publisher.browser import (
    DraftFields,
    EdgePublisherGateway,
    FakePublisherGateway,
    PublishOutcome,
    PublishBlockedError,
    PublishDraft,
    choose_continue_action,
    draft_fields,
    edge_launch_arguments,
    interpret_publish_response,
    managed_chapters_from_rows,
    remote_chapter_numbers,
    remote_chapters,
    remote_row_has_chapter,
    schedule_values,
)
from publisher.models import RemoteChapter


class _PickerInput:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.blurred = False

    def press(self, key: str) -> None:
        self.keys.append(key)

    def blur(self) -> None:
        self.blurred = True


class _PickerPage:
    class _Keyboard:
        def __init__(self, page: "_PickerPage") -> None:
            self._page = page
            self.keys: list[str] = []

        def press(self, key: str) -> None:
            self.keys.append(key)
            if key == "Escape" and self._page.visible_layers:
                self._page.visible_layers -= 1

    class _Locator:
        def __init__(self, page: "_PickerPage") -> None:
            self._page = page

        @property
        def last(self) -> "_PickerPage._Locator":
            return self

        def is_visible(self) -> bool:
            return self._page.visible_layers > 0

    def __init__(self, visible_layers: int) -> None:
        self.visible_layers = visible_layers
        self.keyboard = self._Keyboard(self)

    def locator(self, _selector: str) -> "_PickerPage._Locator":
        return self._Locator(self)

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _PaginatedRows:
    def __init__(self, page: "_PaginatedPage") -> None:
        self._page = page

    @property
    def first(self) -> "_PaginatedRows":
        return self

    def count(self) -> int:
        return 1

    def wait_for(self, *, state: str, timeout: int) -> None:
        self._page.wait_arguments = (state, timeout)

    def all_inner_texts(self) -> list[str]:
        return self._page.pages[self._page.current_page]


class _PaginatedNext:
    def __init__(self, page: "_PaginatedPage") -> None:
        self._page = page

    @property
    def last(self) -> "_PaginatedNext":
        return self

    def count(self) -> int:
        return 1

    def get_attribute(self, name: str) -> str:
        if name != "class":
            return ""
        return (
            "arco-pagination-item arco-pagination-item-next "
            + ("arco-pagination-item-disabled" if self._page.current_page >= 3 else "")
        )

    def click(self) -> None:
        self._page.current_page += 1


class _PaginatedFirstPage:
    def __init__(self, page: "_PaginatedPage") -> None:
        self._page = page

    @property
    def last(self) -> "_PaginatedFirstPage":
        return self

    def count(self) -> int:
        return 1

    def get_attribute(self, name: str) -> str:
        if name != "class":
            return ""
        return (
            "arco-pagination-item arco-pagination-item-active"
            if self._page.current_page == 1
            else "arco-pagination-item"
        )

    def click(self) -> None:
        self._page.current_page = 1


class _PaginatedControls:
    def __init__(self, page: "_PaginatedPage") -> None:
        self._page = page

    @property
    def last(self) -> "_PaginatedControls":
        return self

    def count(self) -> int:
        return 1

    def locator(self, selector: str):
        if selector == ".arco-pagination-item-next":
            return _PaginatedNext(self._page)
        raise AssertionError(f"unexpected pagination selector: {selector}")

    def get_by_text(self, text: str, exact: bool):
        if text != "1" or not exact:
            raise AssertionError("expected the first-page control")
        return _PaginatedFirstPage(self._page)


class _AbsentEmptyState:
    @property
    def last(self) -> "_AbsentEmptyState":
        return self

    def count(self) -> int:
        return 0

    def is_visible(self) -> bool:
        return False


class _PaginatedPage:
    def __init__(self) -> None:
        self.current_page = 8
        self.pages = {1: ["page-1"], 2: ["page-2"], 3: ["page-3"], 8: ["page-8"]}
        self.wait_arguments: tuple[str, int] | None = None

    def locator(self, selector: str):
        if selector == "tr":
            return _PaginatedRows(self)
        if selector == ".arco-pagination":
            return _PaginatedControls(self)
        raise AssertionError(f"unexpected selector: {selector}")

    def get_by_text(self, _text: str, exact: bool):
        if exact:
            raise AssertionError("empty state lookup must not be exact")
        return _AbsentEmptyState()

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _EmptyChapterRows:
    def count(self) -> int:
        return 0

    @property
    def first(self) -> "_EmptyChapterRows":
        return self

    def wait_for(self, *, state: str, timeout: int) -> None:
        raise AssertionError("empty chapter list must not wait for a table row")


class _VisibleEmptyState:
    @property
    def last(self) -> "_VisibleEmptyState":
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True


class _EmptyChapterPage:
    def locator(self, selector: str):
        if selector != "tr":
            raise AssertionError(f"unexpected selector: {selector}")
        return _EmptyChapterRows()

    def get_by_text(self, text: str, exact: bool):
        if text != "暂无章节" or exact:
            raise AssertionError("expected the empty chapter state")
        return _VisibleEmptyState()


class _DelayedEmptyChapterRows:
    def __init__(self, page: "_DelayedEmptyChapterPage") -> None:
        self._page = page

    def count(self) -> int:
        return 0

    @property
    def first(self) -> "_DelayedEmptyChapterRows":
        return self

    def wait_for(self, *, state: str, timeout: int) -> None:
        self._page.empty_visible = True
        raise AssertionError("the table never appears for an empty book")


class _DelayedEmptyState:
    def __init__(self, page: "_DelayedEmptyChapterPage") -> None:
        self._page = page

    @property
    def last(self) -> "_DelayedEmptyState":
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self._page.empty_visible


class _DelayedEmptyChapterPage:
    def __init__(self) -> None:
        self.empty_visible = False

    def locator(self, selector: str):
        if selector != "tr":
            raise AssertionError(f"unexpected selector: {selector}")
        return _DelayedEmptyChapterRows(self)

    def get_by_text(self, text: str, exact: bool):
        if text != "暂无章节" or exact:
            raise AssertionError("expected the empty chapter state")
        return _DelayedEmptyState(self)


class _VisibleControl:
    @property
    def last(self) -> "_VisibleControl":
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True


class _MissingText:
    @property
    def last(self) -> "_MissingText":
        return self

    def count(self) -> int:
        return 0


class _EmptyManagerWithoutEmptyLabel:
    url = "https://fanqienovel.com/main/writer/chapter-manage/book"

    def locator(self, selector: str):
        if selector != "tr":
            raise AssertionError(f"unexpected selector: {selector}")
        return _EmptyChapterRows()

    def get_by_text(self, _text: str, exact: bool):
        if exact:
            raise AssertionError("empty-state lookup must be fuzzy")
        return _MissingText()

    def get_by_role(self, role: str, **kwargs):
        if role != "link" or kwargs.get("name") != "新建章节":
            raise AssertionError("unexpected role lookup")
        return _VisibleControl()


class _DelayedDialog:
    def __init__(self) -> None:
        self.wait_arguments: tuple[str, int] | None = None

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_arguments = (state, timeout)


class _ClosingDialog:
    def __init__(self) -> None:
        self.wait_arguments: tuple[str, int] | None = None

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_arguments = (state, timeout)


class _WarningSubmitButton:
    def __init__(self) -> None:
        self.clicked = False

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    @property
    def last(self) -> "_WarningSubmitButton":
        return self

    def click(self) -> None:
        self.clicked = True


class _NonChapterWarningDialog:
    def __init__(self, button: _WarningSubmitButton) -> None:
        self._button = button

    def filter(self, **_kwargs) -> "_NonChapterWarningDialog":
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    @property
    def last(self) -> "_NonChapterWarningDialog":
        return self

    def get_by_role(self, role: str, **_kwargs) -> _WarningSubmitButton:
        if role != "button":
            raise AssertionError(f"unexpected role: {role}")
        return self._button


class _NonChapterWarningPage:
    def __init__(self) -> None:
        self.button = _WarningSubmitButton()
        self.dialog = _NonChapterWarningDialog(self.button)

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass

    def get_by_role(self, role: str, **_kwargs) -> _NonChapterWarningDialog:
        if role != "dialog":
            raise AssertionError(f"unexpected role: {role}")
        return self.dialog


class _DelayedNonChapterWarningDialog(_NonChapterWarningDialog):
    def __init__(self, page: "_DelayedNonChapterWarningPage") -> None:
        super().__init__(page.button)
        self._page = page

    def is_visible(self) -> bool:
        return self._page.wait_count >= 3


class _DelayedNonChapterWarningPage:
    def __init__(self) -> None:
        self.button = _WarningSubmitButton()
        self.wait_count = 0
        self.dialog = _DelayedNonChapterWarningDialog(self)

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.wait_count += 1

    def get_by_role(self, role: str, **_kwargs) -> _DelayedNonChapterWarningDialog:
        if role != "dialog":
            raise AssertionError(f"unexpected role: {role}")
        return self.dialog


class _MissingLocator:
    @property
    def last(self) -> "_MissingLocator":
        return self

    def count(self) -> int:
        return 0


class _RiskCheckBody:
    def inner_text(self) -> str:
        return "小说正文提到额度不足，但这不是番茄风险检测结果。"


class _RiskCheckButton:
    def __init__(self, page: "_RiskCheckPage") -> None:
        self._page = page
        self.clicked = False

    @property
    def last(self) -> "_RiskCheckButton":
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        self.clicked = True
        self._page.check_dialog_visible = False


class _RiskCheckDialog:
    def __init__(self, page: "_RiskCheckPage") -> None:
        self._page = page

    @property
    def last(self) -> "_RiskCheckDialog":
        return self

    def count(self) -> int:
        return int(self._page.check_dialog_visible)

    def is_visible(self) -> bool:
        return self._page.check_dialog_visible

    def inner_text(self) -> str:
        return "请选择内容检测方式\n全面检测（本章节剩余次数：1/2次）"

    def get_by_role(self, role: str, *, name: str, exact: bool):
        assert (role, name, exact) == ("button", "全面检测", True)
        return self._page.check_button

    def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "hidden"
        assert timeout == 30000
        if self._page.check_dialog_visible:
            raise AssertionError("comprehensive check dialog did not close")


class _RiskCheckDialogs:
    def __init__(self, page: "_RiskCheckPage") -> None:
        self._page = page

    @property
    def last(self):
        return self

    def filter(self, *, has_text: str):
        if has_text == "发布设置":
            return _MissingLocator()
        if has_text == "请选择内容检测方式":
            return self._page.check_dialog
        raise AssertionError(f"unexpected dialog text: {has_text}")


class _RiskCheckPage:
    def __init__(self) -> None:
        self.check_dialog_visible = True
        self.check_button = _RiskCheckButton(self)
        self.check_dialog = _RiskCheckDialog(self)
        self.dialogs = _RiskCheckDialogs(self)

    def get_by_role(self, role: str, **_kwargs):
        if role != "dialog":
            raise AssertionError(f"unexpected role: {role}")
        return self.dialogs

    def get_by_text(self, text: str, *, exact: bool):
        assert (text, exact) == ("全面检测", True)
        return self.check_button

    def locator(self, selector: str):
        assert selector == "body"
        return _RiskCheckBody()

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _PublishSettingSwitch:
    def __init__(self) -> None:
        self.enabled = False

    @property
    def last(self) -> "_PublishSettingSwitch":
        return self

    def count(self) -> int:
        return 1

    def get_attribute(self, name: str) -> str | None:
        return "true" if name == "aria-checked" and self.enabled else "false"

    def click(self) -> None:
        self.enabled = True


class _PublishSettingInput:
    def __init__(self) -> None:
        self.value = ""
        self.wait_arguments: tuple[str, int] | None = None

    @property
    def first(self) -> "_PublishSettingInput":
        return self

    def count(self) -> int:
        return 1

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_arguments = (state, timeout)

    def fill(self, value: str) -> None:
        self.value = value

    def input_value(self) -> str:
        return self.value


class _PublishSettingRadioLabel:
    def __init__(self, radio: "_PublishSettingRadio") -> None:
        self._radio = radio

    def click(self, *, force: bool = False) -> None:
        self._radio.checked = True


class _PublishSettingRadio:
    def __init__(self) -> None:
        self.checked = False
        self.label = _PublishSettingRadioLabel(self)

    @property
    def last(self) -> "_PublishSettingRadio":
        return self

    def count(self) -> int:
        return 1

    def is_checked(self) -> bool:
        return self.checked

    def locator(self, selector: str) -> _PublishSettingRadioLabel:
        assert selector == "xpath=.."
        return self.label


class _PublishSettingsDialog:
    def __init__(self) -> None:
        self.switch = _PublishSettingSwitch()
        self.date_input = _PublishSettingInput()
        self.time_input = _PublishSettingInput()
        self.ai_yes = _PublishSettingRadio()
        self.ai_no = _PublishSettingRadio()

    def get_by_role(self, role: str):
        assert role == "switch"
        return self.switch

    def locator(self, selector: str):
        fields = {
            "input[placeholder='请选择日期']": self.date_input,
            "input[placeholder='请选择时间']": self.time_input,
            "input[type='radio'][value='1']": self.ai_yes,
            "input[type='radio'][value='2']": self.ai_no,
        }
        return fields[selector]


class _ConditionalPublishButton:
    def __init__(self, page: "_NonChapterBackstopPage") -> None:
        self._page = page
        self.clicked = False

    @property
    def last(self) -> "_ConditionalPublishButton":
        return self

    def count(self) -> int:
        return int(self._page.button.clicked)

    def is_visible(self) -> bool:
        return bool(self.count())

    def click(self) -> None:
        self.clicked = True


class _NonChapterBackstopPage(_NonChapterWarningPage):
    def __init__(self) -> None:
        super().__init__()
        self.publish_button = _ConditionalPublishButton(self)

    def get_by_role(self, role: str, **_kwargs):
        if role == "dialog":
            return self.dialog
        if role == "button":
            return self.publish_button
        raise AssertionError(f"unexpected role: {role}")


class _DraftFieldLocator:
    def __init__(self, page: "_ResettingDraftPage", field: str) -> None:
        self._page = page
        self._field = field

    @property
    def first(self) -> "_DraftFieldLocator":
        return self

    def fill(self, value: str) -> None:
        if self._field == "body":
            raise AssertionError("正文必须通过键盘输入，避免番茄重置章节号和标题")
        self._page.write_order.append(self._field)
        setattr(self._page, self._field, value)

    def input_value(self) -> str:
        return str(getattr(self._page, self._field))

    def inner_text(self) -> str:
        return str(getattr(self._page, self._field))

    def focus(self) -> None:
        if self._field == "body":
            self._page.write_order.append("body")

    def wait_for(self, *, state: str, timeout: int) -> None:
        self._page.field_waits.append((self._field, state, timeout))


class _ResettingDraftPage:
    class _Keyboard:
        def __init__(self, page: "_ResettingDraftPage") -> None:
            self._page = page
            self.keys: list[str] = []

        def press(self, key: str) -> None:
            self.keys.append(key)

        def insert_text(self, value: str) -> None:
            self._page.body = value
            self._page.body_was_written = True

    def __init__(self, resets: int) -> None:
        self.serial = ""
        self.title = "未命名草稿"
        self.body = ""
        self._resets = resets
        self.body_was_written = False
        self.write_order: list[str] = []
        self.field_waits: list[tuple[str, str, int]] = []
        self.keyboard = self._Keyboard(self)

    def locator(self, selector: str) -> _DraftFieldLocator:
        fields = {
            "input.serial-input": "serial",
            "input[placeholder='请输入标题']": "title",
            ".syl-editor-container .ProseMirror": "body",
        }
        return _DraftFieldLocator(self, fields[selector])

    def wait_for_timeout(self, _milliseconds: int) -> None:
        if self.body_was_written and self._resets:
            self.serial = ""
            self.title = "未命名草稿"
            self._resets -= 1


class _DelayedNewChapterLink:
    def __init__(self) -> None:
        self.waited = False

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.waited = (state, timeout) == ("visible", 10000)

    def get_attribute(self, name: str) -> str | None:
        if name != "href" or not self.waited:
            return None
        return "/main/writer/book/publish/?enter_from=newchapter"


class _DelayedNewChapterPage:
    def __init__(self) -> None:
        self.url = "https://fanqienovel.com/main/writer/chapter-manage/book"
        self.link = _DelayedNewChapterLink()
        self.goto_url: str | None = None

    def get_by_role(self, role: str, **kwargs):
        if role != "link" or kwargs.get("name") != "新建章节":
            raise AssertionError("unexpected role lookup")
        return self.link

    def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_url = url


def draft(number: int) -> PublishDraft:
    return PublishDraft(
        chapter_number=number,
        title=f"第{number}章",
        body="正文",
        publish_at=datetime(2026, 7, 27, 0, 0),
    )


class BrowserTests(unittest.TestCase):
    def test_remote_chapter_numbers_reads_all_manager_rows(self):
        rows = [
            "第7章 标题\n待发布\n2026-08-01 00:00",
            "第8章 标题\n审核中\n2026-08-02 00:00",
        ]

        self.assertEqual(remote_chapter_numbers(rows), {7, 8})

    def test_remote_chapters_read_word_count_and_publish_time(self):
        rows = ["第7章 标题\n1234\n0\n待发布\n2026-08-01 00:00"]

        self.assertEqual(
            remote_chapters(rows),
            [RemoteChapter(7, 1234, datetime(2026, 8, 1, 0, 0))],
        )

    def test_all_remote_rows_rewinds_to_first_page_before_scanning_forward(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _PaginatedPage()

        self.assertEqual(gateway._all_remote_rows(), ["page-1", "page-2", "page-3"])

    def test_page_change_ignores_a_transient_table_before_accepting_stable_rows(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _PaginatedPage()

        with (
            patch.object(
                gateway,
                "_remote_rows",
                side_effect=[["loading"], ["page-2"], ["page-2"]],
            ),
            patch.object(gateway, "_active_page_number", return_value=2),
        ):
            rows = gateway._wait_for_remote_page_change(1, ("page-1",))

        self.assertEqual(rows, ["page-2"])

    def test_remote_rows_treats_a_visible_empty_chapter_state_as_no_submissions(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _EmptyChapterPage()

        self.assertEqual(gateway._remote_rows(), [])

    def test_remote_rows_rechecks_the_empty_state_after_table_wait_times_out(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _DelayedEmptyChapterPage()

        self.assertEqual(gateway._remote_rows(), [])

    def test_remote_rows_accepts_a_loaded_new_book_without_table_rows(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _EmptyManagerWithoutEmptyLabel()

        self.assertEqual(gateway._remote_rows(), [])

    def test_non_chapter_notice_submits_the_user_requested_confirmation(self):
        page = _NonChapterWarningPage()

        EdgePublisherGateway._submit_non_chapter_notice_if_present(page)

        self.assertTrue(page.button.clicked)

    def test_non_chapter_notice_is_submitted_when_it_appears_after_next_step(self):
        page = _DelayedNonChapterWarningPage()

        EdgePublisherGateway._submit_non_chapter_notice_if_present(page)

        self.assertTrue(page.button.clicked)

    def test_comprehensive_check_ignores_matching_words_in_the_chapter_body(self):
        page = _RiskCheckPage()

        EdgePublisherGateway._run_comprehensive_check(page)

        self.assertTrue(page.check_button.clicked)

    def test_publish_settings_configure_schedule_and_ai_before_confirmation(self):
        dialog = _PublishSettingsDialog()

        with patch.object(EdgePublisherGateway, "_dismiss_picker_popup"):
            EdgePublisherGateway._configure_publish_settings(
                object(), dialog, datetime(2026, 12, 1, 0, 0), True
            )

        self.assertTrue(dialog.switch.enabled)
        self.assertEqual(dialog.date_input.value, "2026-12-01")
        self.assertEqual(dialog.time_input.value, "00:00")
        self.assertTrue(dialog.ai_yes.checked)
        self.assertFalse(dialog.ai_no.checked)

    def test_missing_publish_entry_rechecks_non_chapter_notice_before_failing(self):
        page = _NonChapterBackstopPage()

        with patch.object(
            EdgePublisherGateway,
            "_publish_settings_dialog",
            return_value=_MissingLocator(),
        ):
            EdgePublisherGateway._open_publish_entry(page)

        self.assertTrue(page.button.clicked)
        self.assertTrue(page.publish_button.clicked)

    def test_submission_handles_the_non_chapter_notice_before_detection(self):
        source = inspect.getsource(EdgePublisherGateway._submit_one)

        self.assertIn("_submit_non_chapter_notice_if_present", source)
        self.assertLess(
            source.index("_submit_non_chapter_notice_if_present"),
            source.index("_submit_typo_warning_if_present"),
        )

    def test_submission_does_not_wait_for_the_remote_pending_status(self):
        source = inspect.getsource(EdgePublisherGateway.submit_batch)

        self.assertIn("_return_to_manager_after_submission", source)

    def test_submit_batch_reuses_known_numbers_and_verifies_each_chapter_on_current_page(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = object()
        submitted: list[int] = []

        with (
            patch.object(gateway, "_open_chapter_manager") as open_manager,
            patch.object(
                gateway,
                "existing_remote_chapter_numbers",
                side_effect=AssertionError("不应重复读取全部分页"),
            ) as all_remote_numbers,
            patch.object(
                gateway,
                "_submit_one",
                side_effect=lambda item: submitted.append(item.chapter_number),
            ),
            patch.object(
                gateway,
                "_return_to_manager_after_submission",
                return_value=True,
            ) as verify_current_page,
        ):
            results = gateway.submit_batch(
                [draft(1), draft(2)],
                "测试作品",
                known_remote_numbers=set(),
            )

        self.assertEqual(submitted, [1, 2])
        self.assertEqual([result.chapter_number for result in results], [1, 2])
        self.assertTrue(all(result.verified for result in results))
        self.assertEqual(open_manager.call_count, 1)
        self.assertEqual(verify_current_page.call_count, 2)
        all_remote_numbers.assert_not_called()

    def test_submit_batch_stops_before_a_later_draft_when_requested(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = object()
        submitted: list[int] = []

        with (
            patch.object(gateway, "_open_chapter_manager"),
            patch.object(
                gateway,
                "_submit_one",
                side_effect=lambda item: submitted.append(item.chapter_number),
            ),
            patch.object(
                gateway,
                "_return_to_manager_after_submission",
                return_value=True,
            ),
        ):
            results = gateway.submit_batch(
                [draft(1), draft(2)],
                "测试作品",
                known_remote_numbers=set(),
                should_stop=lambda: len(submitted) == 1,
            )

        self.assertEqual(submitted, [1])
        self.assertTrue(results[-1].cancelled)
        self.assertEqual(results[-1].chapter_number, 2)

    def test_draft_form_uses_keyboard_body_input_and_retries_after_a_reset(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        page = _ResettingDraftPage(resets=1)
        fields = DraftFields("381", "责任不能停在云服务条款里", "第一段。\n第二段。")

        gateway._fill_draft_fields(page, fields)

        self.assertEqual(page.serial, "381")
        self.assertEqual(page.title, "责任不能停在云服务条款里")
        self.assertEqual(page.body, "第一段。\n第二段。")
        self.assertEqual(page.keyboard.keys, ["Control+A"])
        self.assertEqual(page.write_order[:3], ["body", "serial", "title"])

    def test_draft_form_stops_before_next_step_when_fanqie_keeps_clearing_it(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        page = _ResettingDraftPage(resets=3)
        fields = DraftFields("381", "责任不能停在云服务条款里", "第一段。")

        with self.assertRaisesRegex(PublishBlockedError, "章节号或标题被后台清空"):
            gateway._fill_draft_fields(page, fields)

    def test_new_chapter_entry_waits_for_the_delayed_link(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)
        gateway._page = _DelayedNewChapterPage()

        page = gateway._new_chapter_page()

        self.assertIs(page, gateway._page)
        self.assertTrue(gateway._page.link.waited)
        self.assertEqual(
            gateway._page.goto_url,
            "https://fanqienovel.com/main/writer/book/publish/?enter_from=newchapter",
        )

    def test_publish_response_code_zero_is_authoritative_success(self):
        outcome, message = interpret_publish_response({"code": 0, "message": "success"})

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "success")

    def test_publish_response_nonzero_is_failure(self):
        outcome, message = interpret_publish_response(
            {"code": 1001, "message": "提交字数超出每日上限"}
        )

        self.assertIs(outcome, PublishOutcome.DAILY_LIMIT)
        self.assertEqual(message, "提交字数超出每日上限")

    def test_publish_response_without_code_is_unknown(self):
        outcome, message = interpret_publish_response({"message": "ok"})

        self.assertIs(outcome, PublishOutcome.UNKNOWN)
        self.assertEqual(message, "ok")

    def test_authoritative_interface_success_is_not_retried_when_manager_lags(self):
        gateway = EdgePublisherGateway.__new__(EdgePublisherGateway)

        with (
            patch.object(gateway, "_open_chapter_manager"),
            patch.object(gateway, "_visible_remote_chapter_numbers", return_value=set()),
        ):
            refreshed = gateway._return_to_manager_after_submission("作品", draft(381))

        self.assertFalse(refreshed)

    def test_publish_settings_waits_for_the_visible_dialog_after_clicking_publish(self):
        dialog = _DelayedDialog()

        with patch.object(
            EdgePublisherGateway,
            "_publish_settings_dialog",
            return_value=dialog,
        ):
            result = EdgePublisherGateway._wait_for_publish_settings_dialog(object())

        self.assertIs(result, dialog)
        self.assertEqual(dialog.wait_arguments, ("visible", 5000))

    def test_publish_settings_waits_for_the_dialog_to_close_after_submission(self):
        dialog = _ClosingDialog()

        EdgePublisherGateway._wait_for_publish_settings_to_close(dialog)

        self.assertEqual(dialog.wait_arguments, ("hidden", 5000))

    def test_picker_dismissal_retries_until_stacked_layers_are_closed(self):
        page = _PickerPage(visible_layers=2)
        input_locator = _PickerInput()

        EdgePublisherGateway._dismiss_picker_popup(page, input_locator)

        self.assertEqual(input_locator.keys, ["Enter"])
        self.assertTrue(input_locator.blurred)
        self.assertEqual(page.keyboard.keys, ["Escape", "Escape"])

    def test_edge_launch_arguments_keep_the_minimized_window_on_screen_for_taskbar_restore(self):
        profile_dir = Path("fanqie-edge-profile")

        arguments = edge_launch_arguments(
            Path(r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"),
            profile_dir,
            "https://fanqienovel.com/writer/zone/",
        )

        self.assertIn("--new-window", arguments)
        self.assertIn("--window-position=100,80", arguments)
        self.assertNotIn("--window-position=-32000,-32000", arguments)
        self.assertIn("--remote-debugging-address=127.0.0.1", arguments)
        self.assertIn(f"--user-data-dir={profile_dir.resolve()}", arguments)

    def test_edge_launch_arguments_use_the_account_debug_port(self):
        arguments = edge_launch_arguments(
            Path(r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"),
            Path("fanqie-edge-profile"),
            "https://fanqienovel.com/writer/zone/",
            cdp_port=9444,
        )

        self.assertIn("--remote-debugging-port=9444", arguments)

    def test_typo_prompt_prefers_continue_publishing_over_editing(self):
        self.assertEqual(
            choose_continue_action({"修改", "继续发布", "取消"}),
            "继续发布",
        )
        self.assertEqual(choose_continue_action({"提交", "修改"}), "提交")
        self.assertEqual(choose_continue_action({"修改", "仍要发布"}), "仍要发布")
        self.assertIsNone(choose_continue_action({"修改", "取消"}))

    def test_draft_fields_send_an_unpadded_decimal_chapter_number(self):
        fields = draft_fields(draft(1))

        self.assertEqual(fields.chapter_number, "1")
        self.assertEqual(fields.title, "第1章")

    def test_draft_fields_remove_a_matching_chinese_chapter_heading_and_blank_lines(self):
        chapter_body = (
            "第八十二章 她拒绝当合规负责人\n\n"
            "第一段。\n\n"
            "第二段。\n\n\n"
            "第三段。"
        )
        chapter = PublishDraft(
            chapter_number=82,
            title="她拒绝当合规负责人",
            body=chapter_body,
            publish_at=datetime(2026, 8, 3, 0, 0),
        )

        fields = draft_fields(chapter)

        self.assertEqual(fields.body, "第一段。\n第二段。\n第三段。")

    def test_draft_fields_reject_a_missing_title(self):
        missing_title = PublishDraft(
            chapter_number=1,
            title="   ",
            body="正文",
            publish_at=datetime(2026, 7, 27, 0, 0),
        )

        with self.assertRaisesRegex(ValueError, "标题"):
            draft_fields(missing_title)

    def test_draft_fields_reject_an_empty_body(self):
        empty_body = PublishDraft(
            chapter_number=1,
            title="标题",
            body="\n\t ",
            publish_at=datetime(2026, 7, 27, 0, 0),
        )

        with self.assertRaisesRegex(ValueError, "正文"):
            draft_fields(empty_body)

    def test_remote_row_chapter_check_detects_a_differently_scheduled_duplicate(self):
        row = "第1章 第1章\n\t\n2000\n\t\n待发布\n\t\n2026-08-02 00:00"

        self.assertTrue(remote_row_has_chapter(row, draft(1)))

    def test_managed_chapters_keep_only_number_status_and_editor_path(self):
        managed = managed_chapters_from_rows(
            [
                (
                    "第8章 标题\n2000\n待发布\n2026-08-20 08:00",
                    "/main/writer/book/publish/item-8",
                ),
                (
                    "第9章 标题\n2000\n审核中",
                    "/main/writer/book/publish/item-9",
                ),
            ]
        )

        self.assertEqual(managed[0].chapter_number, 8)
        self.assertEqual(managed[0].status, "pending")
        self.assertEqual(managed[0].editor_path, "/main/writer/book/publish/item-8")
        self.assertEqual(managed[1].status, "reviewing")

    def test_schedule_values_keep_the_planned_date_and_time(self):
        self.assertEqual(
            schedule_values(datetime(2026, 8, 3, 0, 0)),
            ("2026-08-03", "00:00"),
        )

    def test_draft_keeps_its_ai_declaration(self):
        draft_without_ai = PublishDraft(
            chapter_number=1,
            title="标题",
            body="正文",
            publish_at=datetime(2026, 8, 3, 0, 0),
            ai_generated=False,
        )

        self.assertFalse(draft_without_ai.ai_generated)

    def test_gateway_stops_after_the_first_blocked_submission(self):
        gateway = FakePublisherGateway(block_at=2, reason="captcha")

        results = gateway.submit_batch([draft(1), draft(2), draft(3)])

        self.assertEqual([result.chapter_number for result in results], [1, 2])
        self.assertTrue(results[1].blocked)
        self.assertEqual(results[1].error, "captcha")
