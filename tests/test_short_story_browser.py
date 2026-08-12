from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from publisher.browser import PublishBlockedError, PublishOutcome
from publisher.short_story import ShortStoryConfig, ShortStoryDraft
from publisher.short_story_browser import (
    ShortStoryAgreementRequired,
    ShortStoryPublisher,
    ShortStorySubmissionError,
    interpret_short_publish_response,
    requires_cover_agreement,
    requires_publication_agreement,
    short_story_draft_url,
    story_body_html,
)


class _Field:
    def __init__(self, page: "_ResettingStoryPage", name: str) -> None:
        self.page = page
        self.name = name

    @property
    def first(self):
        return self

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.page.waits.append((self.name, state, timeout))

    def focus(self) -> None:
        if self.name == "body":
            self.page.order.append("body")

    def fill(self, value: str) -> None:
        self.page.order.append(self.name)
        setattr(self.page, self.name, value)

    def input_value(self) -> str:
        return getattr(self.page, self.name)

    def inner_text(self) -> str:
        return getattr(self.page, self.name)


class _Keyboard:
    def __init__(self, page: "_ResettingStoryPage") -> None:
        self.page = page

    def press(self, _key: str) -> None:
        pass

    def insert_text(self, value: str) -> None:
        self.page.body = value
        self.page.body_written = True


class _ResettingStoryPage:
    def __init__(self, resets: int) -> None:
        self.title = ""
        self.body = ""
        self.resets = resets
        self.body_written = False
        self.order: list[str] = []
        self.waits: list[tuple[str, str, int]] = []
        self.keyboard = _Keyboard(self)

    def locator(self, selector: str):
        fields = {
            "textarea[placeholder='请输入短故事名称']": "title",
            ".ProseMirror.payNode-helper-content": "body",
        }
        return _Field(self, fields[selector])

    def wait_for_timeout(self, _milliseconds: int) -> None:
        if self.body_written and self.resets:
            self.body = ""
            self.title = ""
            self.resets -= 1


class _ConsentField:
    def __init__(self, checked: bool = False) -> None:
        self.checked = checked
        self.check_calls = 0
        self.parent = _ConsentParent()

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_checked(self) -> bool:
        return self.checked

    def check(self, *, force: bool) -> None:
        assert force
        self.check_calls += 1
        self.checked = True

    def locator(self, selector: str):
        assert selector == "xpath=.."
        return self.parent


class _ConsentParent:
    def click(self, *, force: bool) -> None:
        assert force


class _AgreementModal:
    def __init__(self) -> None:
        self.visible = True
        self.button = _AgreementButton(self)
        self.waits: list[tuple[str, int]] = []

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.visible

    def inner_text(self) -> str:
        return "我已阅读并同意短故事发布协议及创作收益规则"

    def get_by_role(self, role: str, *, name: str, exact: bool):
        assert (role, name, exact) == ("button", "我已阅读并同意", True)
        return self.button

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.waits.append((state, timeout))
        assert state == "hidden"
        assert not self.visible


class _AgreementButton:
    def __init__(self, modal: _AgreementModal) -> None:
        self.modal = modal
        self.click_calls = 0

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def click(self, *, force: bool) -> None:
        assert force
        self.click_calls += 1
        self.modal.visible = False


class _MissingAgreementButton:
    @property
    def last(self):
        return self

    def count(self) -> int:
        return 0


class _TextAgreementModal(_AgreementModal):
    def get_by_role(self, _role: str, *, name: str, exact: bool):
        assert (name, exact) == ("我已阅读并同意", True)
        return _MissingAgreementButton()

    def get_by_text(self, text: str, *, exact: bool):
        assert (text, exact) == ("我已阅读并同意", True)
        return self.button


class _ConsentAgreementPage:
    def __init__(self, modal: _AgreementModal | None = None) -> None:
        self.consent = _ConsentField()
        self.modal = modal or _AgreementModal()

    def locator(self, selector: str):
        fields = {
            ".publish-short-config-signLicense input[type='checkbox']": self.consent,
            ".publish-short-license-modal": self.modal,
        }
        return fields[selector]

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _NoAgreementModal:
    @property
    def last(self):
        return self

    def count(self) -> int:
        return 0


class _ConsentPage:
    def __init__(self) -> None:
        self.consent = _ConsentField()
        self.modal = _NoAgreementModal()

    def locator(self, selector: str):
        fields = {
            ".publish-short-config-signLicense input[type='checkbox']": self.consent,
            ".publish-short-license-modal": self.modal,
        }
        return fields[selector]

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _ResumeEditButton:
    def __init__(self) -> None:
        self.clicked = False

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        self.clicked = True


class _ResumeDraftPage:
    def __init__(self) -> None:
        self.button = _ResumeEditButton()
        self.waits: list[int] = []

    def get_by_text(self, text: str, *, exact: bool):
        assert (text, exact) == ("继续编辑", True)
        return self.button

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class _AiRadio:
    def __init__(self) -> None:
        self.checked = False
        self.check_calls = 0

    def count(self) -> int:
        return 1

    def check(self, *, force: bool) -> None:
        assert force
        self.check_calls += 1
        self.checked = True

    def is_checked(self) -> bool:
        return self.checked

    def locator(self, _selector: str):
        raise AssertionError("应直接选中原生 AI 单选框")


class _AiPage:
    def __init__(self) -> None:
        self.radio = _AiRadio()

    def locator(self, selector: str):
        assert selector == "input[type='radio'][value='1']"
        return self.radio


class _OffscreenAiRadio(_AiRadio):
    def __init__(self) -> None:
        super().__init__()
        self.click_calls = 0

    def check(self, *, force: bool) -> None:
        raise RuntimeError("Element is outside of the viewport")

    def click(self, *, force: bool) -> None:
        assert force
        self.click_calls += 1
        self.checked = True


class _OffscreenAiPage(_AiPage):
    def __init__(self) -> None:
        self.radio = _OffscreenAiRadio()


class _HiddenAiRadio(_OffscreenAiRadio):
    def __init__(self) -> None:
        super().__init__()
        self.evaluate_calls = 0

    def click(self, *, force: bool) -> None:
        raise RuntimeError("Element is outside of the viewport")

    def evaluate(self, expression: str) -> None:
        assert expression == "input => input.click()"
        self.evaluate_calls += 1
        self.checked = True


class _HiddenAiPage(_AiPage):
    def __init__(self) -> None:
        self.radio = _HiddenAiRadio()


class _CategorySelected:
    def __init__(self) -> None:
        self.categories: list[str] = []
        self.clicked = False

    @property
    def first(self):
        return self

    def click(self, *, force: bool) -> None:
        assert force
        self.clicked = True

    def inner_text(self) -> str:
        return "、".join(self.categories)


class _TextCategorySelected:
    def __init__(self, text: str) -> None:
        self.text = text

    def inner_text(self) -> str:
        return self.text


class _CategoryMenu:
    def __init__(self, page: "_CategoryPage") -> None:
        self.page = page
        self.clicked = False

    @property
    def last(self):
        return self

    @property
    def first(self):
        return self

    def click(self, *, force: bool) -> None:
        assert force
        self.clicked = True

    def get_by_text(self, text: str, *, exact: bool):
        return _MissingCategoryOption()


class _MissingCategoryOption:
    @property
    def last(self):
        return self

    def count(self) -> int:
        return 0

    def is_visible(self) -> bool:
        return False


class _CategoryOption:
    def __init__(self, selected: _CategorySelected, updates_selection: bool) -> None:
        self.selected = selected
        self.updates_selection = updates_selection
        self.clicked = False

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def click(self, *, force: bool) -> None:
        assert force
        self.clicked = True
        if self.updates_selection:
            self.selected.categories.append("虐心婚恋")


class _CategoryKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)


class _CategoryPage:
    def __init__(self, updates_selection: bool = True) -> None:
        self.ready = False
        self.selected = _CategorySelected()
        self.menu = _CategoryMenu(self)
        self.option = _CategoryOption(self.selected, updates_selection)
        self.keyboard = _CategoryKeyboard()

    def locator(self, selector: str):
        fields = {
            ".publish-short-category-select-selected-list": self.selected,
            ".publish-short-category-select": self.menu,
            ".publish-short-category-select.arco-dropdown-open": (
                _MissingCategoryOption()
            ),
        }
        return fields[selector]

    def get_by_text(self, text: str, *, exact: bool):
        if not self.ready:
            return _MissingCategoryOption()
        assert (text, exact) == ("虐心婚恋", True)
        return self.option

    def wait_for_timeout(self, _milliseconds: int) -> None:
        if self.selected.clicked:
            self.ready = True


class _CategoryCloseButton:
    def __init__(self, menu: "_OpenCategoryMenu") -> None:
        self.menu = menu
        self.click_calls = 0

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.menu.open

    def click(self, *, force: bool) -> None:
        assert force
        self.click_calls += 1
        self.menu.open = False


class _OpenCategoryMenu(_CategoryMenu):
    def __init__(self, page: "_OpenCategoryPage") -> None:
        super().__init__(page)
        self.open = True
        self.close_icon = _CategoryCloseButton(self)

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.open

    def locator(self, selector: str):
        assert selector == ".publish-short-category-select-icon"
        return self.close_icon


class _OpenCategoryPage(_CategoryPage):
    def __init__(self) -> None:
        super().__init__()
        self.menu = _OpenCategoryMenu(self)

    def locator(self, selector: str):
        if selector == ".publish-short-category-select.arco-dropdown-open":
            return self.menu
        return super().locator(selector)


class _GroupedCategoryOption(_MissingCategoryOption):
    def __init__(self, page: "_GroupedCategoryPage") -> None:
        self.page = page

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.page.option_ready

    def click(self, *, force: bool) -> None:
        assert force
        self.page.selected.categories.append("家庭")


class _GroupedCategoryTab:
    def __init__(self, page: "_GroupedCategoryPage", name: str) -> None:
        self.page = page
        self.name = name

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def hover(self) -> None:
        if self.name == "背景":
            self.page.background_hovered = True


class _GroupedCategoryPage:
    def __init__(self) -> None:
        self.selected = _CategorySelected()
        self.option_ready = False
        self.background_hovered = False
        self.option = _GroupedCategoryOption(self)
        self.keyboard = _CategoryKeyboard()

    def locator(self, selector: str):
        fields = {
            ".publish-short-category-select-selected-list": self.selected,
            ".publish-short-category-select.arco-dropdown-open": (
                _MissingCategoryOption()
            ),
        }
        return fields[selector]

    def get_by_text(self, text: str, *, exact: bool):
        assert exact
        if text == "家庭":
            return self.option
        return _GroupedCategoryTab(self, text)

    def wait_for_timeout(self, milliseconds: int) -> None:
        if self.background_hovered and milliseconds >= 300:
            self.option_ready = True


class _RetryCategorySelected(_CategorySelected):
    def __init__(self, page: "_RetryGroupedCategoryPage") -> None:
        super().__init__()
        self.page = page

    def click(self, *, force: bool) -> None:
        super().click(force=force)
        self.page.open_count += 1


class _RetryGroupedCategoryPage(_GroupedCategoryPage):
    def __init__(self) -> None:
        self.open_count = 0
        super().__init__()
        self.selected = _RetryCategorySelected(self)
        self.option = _GroupedCategoryOption(self)

    def wait_for_timeout(self, milliseconds: int) -> None:
        if (
            self.background_hovered
            and self.open_count > 1
            and milliseconds >= 300
        ):
            self.option_ready = True


class _CoverCheckbox:
    def __init__(self) -> None:
        self.checked = False
        self.check_calls = 0

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_checked(self) -> bool:
        return self.checked

    def check(self, *, force: bool) -> None:
        assert force
        self.check_calls += 1
        self.checked = True


class _CoverButton:
    def __init__(self, action) -> None:
        self.action = action
        self.click_calls = 0

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def click(self, *, force: bool) -> None:
        assert force
        self.click_calls += 1
        self.action()

    def wait_for(self, *, state: str, timeout: int) -> None:
        assert (state, timeout) == ("visible", 5000)


class _CoverUpload:
    def __init__(self) -> None:
        self.path: str | None = None

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def set_input_files(self, path: str) -> None:
        self.path = path


class _CoverDrawer:
    def __init__(self) -> None:
        self.visible = True
        self.stage = "agreement"
        self.checkbox = _CoverCheckbox()
        self.upload = _CoverUpload()
        self.enable = _CoverButton(lambda: setattr(self, "stage", "make"))
        self.local_upload = _CoverButton(lambda: setattr(self, "stage", "local"))
        self.confirm = _CoverButton(lambda: setattr(self, "visible", False))
        self.upload_confirm = _CoverButton(lambda: setattr(self, "visible", False))
        self.requires_upload_confirmation = False
        self.waits: list[tuple[str, int]] = []

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return self.visible

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.waits.append((state, timeout))
        assert (state == "visible" and self.visible) or (
            state == "hidden" and not self.visible
        )

    def inner_text(self) -> str:
        if self.stage == "agreement":
            return "字体许可使用协议 图片上传协议"
        return "制作封面 本地上传"

    def locator(self, selector: str):
        fields = {
            "input[type='checkbox']": self.checkbox,
            "input[type='file']": self.upload,
        }
        return fields[selector]

    def get_by_role(self, role: str, *, name: str, exact: bool):
        assert (role, exact) == ("button", True)
        buttons = {
            "开启AI插图功能": self.enable,
            "确定": self.confirm,
        }
        if name == "确认上传":
            return (
                self.upload_confirm
                if self.requires_upload_confirmation
                else _MissingCategoryOption()
            )
        return buttons[name]

    def get_by_text(self, text: str, *, exact: bool):
        assert (text, exact) == ("本地上传", True)
        return self.local_upload


class _CoverContainer:
    def __init__(self) -> None:
        self.click_calls = 0

    def click(self, *, force: bool) -> None:
        assert force
        self.click_calls += 1


class _CoverPage:
    def __init__(self, drawer: _CoverDrawer | None = None) -> None:
        self.container = _CoverContainer()
        self.drawer = drawer or _CoverDrawer()

    def locator(self, selector: str):
        fields = {
            ".publish-short-config-cover-container": self.container,
            ".byte-drawer": self.drawer,
        }
        return fields[selector]

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass


class _FaceRiskCoverDrawer(_CoverDrawer):
    def __init__(self) -> None:
        super().__init__()
        self.requires_upload_confirmation = True
        self.risk_confirmed = False
        self.awaiting_upload_confirmation = False
        self.confirm = _CoverButton(self._confirm_local_upload)
        self.upload_confirm = _CoverButton(self._confirm_risk)

    def _confirm_local_upload(self) -> None:
        if self.risk_confirmed:
            self.visible = False
        else:
            self.awaiting_upload_confirmation = True

    def _confirm_risk(self) -> None:
        self.awaiting_upload_confirmation = False
        self.risk_confirmed = True

    def get_by_role(self, role: str, *, name: str, exact: bool):
        if name == "确认上传":
            return (
                self.upload_confirm
                if self.awaiting_upload_confirmation
                else _MissingCategoryOption()
            )
        return super().get_by_role(role, name=name, exact=exact)


class _FlowButton:
    def __init__(self, action) -> None:
        self.action = action
        self.click_calls = 0

    @property
    def last(self):
        return self

    def count(self) -> int:
        return 1

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def click(self, **_kwargs) -> None:
        self.click_calls += 1
        self.action()


class _MissingPublishDialog:
    @property
    def last(self):
        return self

    def count(self) -> int:
        return 0

    def is_visible(self) -> bool:
        return False

    def wait_for(self, **_kwargs) -> None:
        raise TimeoutError("dialog is not visible")


class _PublishFlowDialog:
    def __init__(self, page: "_PublishFlowPage") -> None:
        self.page = page
        self.agree = _FlowButton(lambda: setattr(page, "stage", "draft"))
        self.continue_publish = _FlowButton(
            lambda: setattr(page, "stage", "confirmation")
        )
        self.confirm = _FlowButton(lambda: setattr(page, "stage", "done"))

    @property
    def last(self):
        return self

    def count(self) -> int:
        return int(
            self.page.stage in {"agreement", "warning", "confirmation"}
        )

    def is_visible(self) -> bool:
        return bool(self.count())

    def inner_text(self) -> str:
        if self.page.stage == "agreement":
            return "短故事发布协议 我已阅读并同意"
        if self.page.stage == "warning":
            return "发布提示 检测到以下问题，是否继续发布？"
        if self.page.stage == "confirmation":
            return "提交确认"
        return ""

    def filter(self, *, has_text: str):
        if has_text in self.inner_text():
            return self
        return _MissingPublishDialog()

    def get_by_role(self, role: str, *, name: str, exact: bool):
        assert (role, exact) == ("button", True)
        if name == "我已阅读并同意" and self.page.stage == "agreement":
            return self.agree
        if name == "继续发布" and self.page.stage == "warning":
            return self.continue_publish
        if name == "确认" and self.page.stage == "confirmation":
            return self.confirm
        return _MissingPublishDialog()


class _PublishFlowPage:
    def __init__(self, first_dialog: str = "agreement") -> None:
        self.stage = "draft"
        self.first_dialog = first_dialog
        self.next = _FlowButton(self._advance)
        self.dialog = _PublishFlowDialog(self)

    def _advance(self) -> None:
        if self.stage == "draft" and self.next.click_calls == 1:
            self.stage = self.first_dialog
        elif self.stage == "draft":
            self.stage = "confirmation"

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = True):
        if role == "button" and name == "下一步":
            return self.next
        if role == "dialog":
            return self.dialog
        raise AssertionError(f"unexpected role: {role} {name}")

    def locator(self, selector: str):
        fields = {
            "body": self.dialog,
            ".arco-modal": self.dialog,
            ".byte-modal-wrapper:not([aria-hidden='true'])": self.dialog,
            ".byte-modal-wrapper": _MissingPublishDialog(),
        }
        return fields[selector]

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass

    @contextmanager
    def expect_response(self, predicate, *, timeout: int):
        assert timeout == 15000
        response = type(
            "Response",
            (), {
                "url": "https://fanqienovel.com/api/author/short_article/publish/v0/",
                "json": lambda _self: {"code": 0, "message": "发布成功"},
            },
        )()
        assert predicate(response)
        yield type("ResponseInfo", (), {"value": response})()


class _NonSemanticPublishFlowPage(_PublishFlowPage):
    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = True
    ):
        if role == "dialog":
            return _MissingPublishDialog()
        return super().get_by_role(role, name=name, exact=exact)

    def locator(self, selector: str):
        if selector == ".arco-modal":
            return self.dialog
        return super().locator(selector)


class _ByteModalPublishFlowPage(_PublishFlowPage):
    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = True
    ):
        if role == "dialog":
            return _MissingPublishDialog()
        return super().get_by_role(role, name=name, exact=exact)

    def locator(self, selector: str):
        if selector == ".arco-modal":
            return _MissingPublishDialog()
        if selector in (
            ".byte-modal-wrapper:not([aria-hidden='true'])",
            ".byte-modal-wrapper",
        ):
            return self.dialog
        return super().locator(selector)


class _AriaHiddenByteModalPublishFlowPage(_PublishFlowPage):
    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = True
    ):
        if role == "dialog":
            return _MissingPublishDialog()
        return super().get_by_role(role, name=name, exact=exact)

    def locator(self, selector: str):
        if selector == ".arco-modal":
            return _MissingPublishDialog()
        if selector == ".byte-modal-wrapper:not([aria-hidden='true'])":
            return _MissingPublishDialog()
        if selector == ".byte-modal-wrapper":
            return self.dialog
        return super().locator(selector)


class _RoleHiddenContinuePublishDialog(_PublishFlowDialog):
    def get_by_role(self, role: str, *, name: str, exact: bool):
        if name == "继续发布" and self.page.stage == "warning":
            return _MissingPublishDialog()
        return super().get_by_role(role, name=name, exact=exact)

    def locator(self, selector: str):
        if (
            selector == "button:has-text('继续发布')"
            and self.page.stage == "warning"
        ):
            return self.continue_publish
        return _MissingPublishDialog()


class _AriaHiddenByteModalWithRoleHiddenPublishFlowPage(
    _AriaHiddenByteModalPublishFlowPage
):
    def __init__(self, first_dialog: str = "agreement") -> None:
        super().__init__(first_dialog)
        self.dialog = _RoleHiddenContinuePublishDialog(self)


class _DelayedConfirmationPublishPage(_PublishFlowPage):
    def __init__(self) -> None:
        super().__init__(first_dialog="warning")
        self.confirmation_waits = 0
        self.dialog.continue_publish = _FlowButton(self._begin_confirmation)

    def _begin_confirmation(self) -> None:
        self.stage = "awaiting_confirmation"

    def wait_for_timeout(self, _milliseconds: int) -> None:
        if self.stage == "awaiting_confirmation":
            self.confirmation_waits += 1
            if self.confirmation_waits == 2:
                self.stage = "confirmation"


class _Gateway:
    def launch(self) -> None:
        pass

    @property
    def current_page(self):
        return object()


class ShortStoryBrowserTests(unittest.TestCase):
    def test_story_body_html_uses_real_paragraphs_and_escapes_text(self):
        self.assertEqual(
            story_body_html("第一段<&\n\n第二段"),
            "<p>第一段&lt;&amp;</p><p>第二段</p>",
        )

    def test_story_validation_stops_before_browser_when_body_exceeds_platform_limit(self):
        draft = ShortStoryDraft(
            title="夜航",
            body="正文",
            source_path=Path("夜航.txt"),
            source_files=(Path("夜航.txt"),),
            character_count=100001,
        )

        with self.assertRaisesRegex(ValueError, "不能超过 100000 字"):
            ShortStoryPublisher._validate_draft(
                draft,
                type(
                    "Config",
                    (),
                    {"trial_enabled": True, "consent_confirmed": True},
                )(),
            )

    def test_story_fields_write_body_first_and_recover_from_initial_page_reset(self):
        page = _ResettingStoryPage(resets=1)
        draft = ShortStoryDraft(
            title="夜航",
            body="第一段。\n\n第二段。",
            source_path=Path("夜航.txt"),
            source_files=(Path("夜航.txt"),),
            character_count=8,
        )

        ShortStoryPublisher._fill_story_fields(page, draft)

        self.assertEqual(page.title, "夜航")
        self.assertEqual(page.body, "第一段。\n\n第二段。")
        self.assertEqual(page.order[:2], ["body", "title"])

    def test_ai_declaration_uses_the_native_radio_and_reads_it_back(self):
        page = _AiPage()

        ShortStoryPublisher._set_ai_declaration(page, True)

        self.assertEqual(page.radio.check_calls, 1)
        self.assertTrue(page.radio.is_checked())

    def test_ai_declaration_force_clicks_when_the_native_input_is_offscreen(self):
        page = _OffscreenAiPage()

        ShortStoryPublisher._set_ai_declaration(page, True)

        self.assertEqual(page.radio.click_calls, 1)
        self.assertTrue(page.radio.is_checked())

    def test_ai_declaration_uses_dom_click_when_the_native_input_is_hidden(self):
        page = _HiddenAiPage()

        ShortStoryPublisher._set_ai_declaration(page, True)

        self.assertEqual(page.radio.evaluate_calls, 1)
        self.assertTrue(page.radio.is_checked())

    def test_publication_consent_uses_the_native_checkbox_and_reads_it_back(self):
        page = _ConsentPage()

        ShortStoryPublisher._set_publication_consent(
            page,
            True,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

        self.assertEqual(page.consent.check_calls, 1)
        self.assertTrue(page.consent.is_checked())

    def test_category_selection_force_clicks_the_live_option(self):
        page = _CategoryPage()
        config = type(
            "Config", (), {"primary_category": "虐心婚恋", "extra_categories": ()}
        )()

        ShortStoryPublisher._select_categories(page, config)

        self.assertTrue(page.selected.clicked)
        self.assertTrue(page.option.clicked)
        self.assertEqual(page.selected.categories, ["虐心婚恋"])

    def test_category_selection_closes_the_menu_after_the_last_choice(self):
        page = _CategoryPage()
        config = type(
            "Config", (), {"primary_category": "虐心婚恋", "extra_categories": ()}
        )()

        ShortStoryPublisher._select_categories(page, config)

        self.assertEqual(page.keyboard.presses, [])

    def test_category_selection_closes_the_live_picker_with_its_arrow(self):
        page = _OpenCategoryPage()
        config = type(
            "Config", (), {"primary_category": "虐心婚恋", "extra_categories": ()}
        )()

        ShortStoryPublisher._select_categories(page, config)

        self.assertFalse(page.menu.open)
        self.assertEqual(page.menu.close_icon.click_calls, 1)
        self.assertEqual(page.keyboard.presses, [])

    def test_category_selection_stops_when_the_choice_is_not_saved(self):
        page = _CategoryPage(updates_selection=False)
        config = type(
            "Config", (), {"primary_category": "虐心婚恋", "extra_categories": ()}
        )()

        with self.assertRaisesRegex(PublishBlockedError, "分类未生效"):
            ShortStoryPublisher._select_categories(page, config)

    def test_category_check_does_not_confuse_a_short_tag_with_a_primary_name(self):
        selected = _TextCategorySelected("婚姻家庭")

        self.assertFalse(
            ShortStoryPublisher._category_is_selected(selected, "家庭")
        )

    def test_category_selection_waits_for_a_grouped_extra_category(self):
        page = _GroupedCategoryPage()
        config = type(
            "Config", (), {"primary_category": "家庭", "extra_categories": ()}
        )()

        ShortStoryPublisher._select_categories(page, config)

        self.assertEqual(page.selected.categories, ["家庭"])

    def test_category_selection_retries_when_the_grouped_option_is_late(self):
        page = _RetryGroupedCategoryPage()
        config = type(
            "Config", (), {"primary_category": "家庭", "extra_categories": ()}
        )()

        ShortStoryPublisher._select_categories(page, config)

        self.assertEqual(page.selected.categories, ["家庭"])

    def test_cover_upload_accepts_licenses_then_uses_local_upload(self):
        page = _CoverPage()

        ShortStoryPublisher._upload_cover(
            page,
            Path("cover.png"),
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

        self.assertEqual(page.drawer.checkbox.check_calls, 1)
        self.assertEqual(page.drawer.enable.click_calls, 1)
        self.assertEqual(page.drawer.local_upload.click_calls, 1)
        self.assertEqual(page.drawer.upload.path, "cover.png")
        self.assertEqual(page.drawer.confirm.click_calls, 1)
        self.assertEqual(page.drawer.waits[-1], ("hidden", 8000))

    def test_cover_upload_confirms_the_face_risk_prompt(self):
        page = _CoverPage(_FaceRiskCoverDrawer())

        ShortStoryPublisher._upload_cover(
            page,
            Path("cover.png"),
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

        self.assertEqual(page.drawer.confirm.click_calls, 2)
        self.assertEqual(page.drawer.upload_confirm.click_calls, 1)
        self.assertFalse(page.drawer.visible)

    def test_submit_keeps_the_draft_url_when_a_page_operation_times_out(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "夜航.txt"
            cover = root / "cover.png"
            source.write_text("正" * 5000, encoding="utf-8")
            cover.write_bytes(b"png")
            config = ShortStoryConfig(
                story_id="story-1",
                name="夜航",
                source_path=source,
                cover_path=cover,
                primary_category="婚姻家庭",
                consent_confirmed=True,
            )

            with (
                patch.object(
                    ShortStoryPublisher,
                    "_open_draft",
                    return_value="https://fanqienovel.com/main/writer/publish-short/123",
                ),
                patch.object(
                    ShortStoryPublisher,
                    "_fill_story_fields",
                    side_effect=TimeoutError("分类菜单重绘"),
                ),
                self.assertRaises(ShortStorySubmissionError) as error,
            ):
                ShortStoryPublisher(_Gateway()).submit(config)

        self.assertEqual(
            error.exception.draft_url,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )
        self.assertEqual(str(error.exception), "分类菜单重绘")

    def test_cover_license_must_be_handled_by_the_user(self):
        self.assertTrue(requires_cover_agreement("字体许可使用协议 图片上传协议", False))
        self.assertFalse(requires_cover_agreement("制作封面 本地上传", False))
        self.assertFalse(requires_cover_agreement("字体许可使用协议", True))

    def test_publication_license_is_recognized_before_auto_publish(self):
        self.assertTrue(requires_publication_agreement("我已阅读并同意 创作收益"))
        self.assertFalse(requires_publication_agreement("短故事发布设置"))

    def test_publication_license_modal_is_accepted_after_local_consent(self):
        page = _ConsentAgreementPage()

        ShortStoryPublisher._set_publication_consent(
            page,
            True,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

        self.assertEqual(page.modal.button.click_calls, 1)
        self.assertEqual(page.modal.waits, [("hidden", 10000)])

    def test_publication_license_falls_back_to_its_agree_text(self):
        page = _ConsentAgreementPage(_TextAgreementModal())

        ShortStoryPublisher._set_publication_consent(
            page,
            True,
            "https://fanqienovel.com/main/writer/publish-short/123",
        )

        self.assertEqual(page.modal.button.click_calls, 1)

    def test_publish_advances_through_a_visible_agreement_before_submission(self):
        page = _PublishFlowPage()

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.next.click_calls, 2)
        self.assertEqual(page.dialog.agree.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_continues_through_a_formatting_warning(self):
        page = _PublishFlowPage(first_dialog="warning")

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_continues_through_an_arco_warning_without_dialog_role(self):
        page = _NonSemanticPublishFlowPage(first_dialog="warning")

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_continues_through_a_byte_modal_warning_without_dialog_role(self):
        page = _ByteModalPublishFlowPage(first_dialog="warning")

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_continues_through_a_visible_byte_modal_marked_aria_hidden(self):
        page = _AriaHiddenByteModalPublishFlowPage(first_dialog="warning")

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.next.click_calls, 1)
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_uses_css_fallback_when_aria_hidden_modal_hides_continue_button_role(self):
        page = _AriaHiddenByteModalWithRoleHiddenPublishFlowPage(
            first_dialog="warning"
        )

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.next.click_calls, 1)
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_publish_waits_for_confirmation_after_continuing_a_warning(self):
        page = _DelayedConfirmationPublishPage()

        outcome, message = ShortStoryPublisher._publish(page)

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")
        self.assertEqual(page.next.click_calls, 1)
        self.assertEqual(page.dialog.continue_publish.click_calls, 1)
        self.assertEqual(page.dialog.confirm.click_calls, 1)

    def test_reopens_a_recently_updated_draft_for_editing(self):
        page = _ResumeDraftPage()

        ShortStoryPublisher._resume_recent_draft(page)

        self.assertTrue(page.button.clicked)

    def test_short_publish_response_code_zero_is_success(self):
        outcome, message = interpret_short_publish_response(
            {"code": 0, "message": "发布成功"}
        )

        self.assertIs(outcome, PublishOutcome.SUCCESS)
        self.assertEqual(message, "发布成功")

    def test_short_publish_response_nonzero_is_failure(self):
        outcome, message = interpret_short_publish_response(
            {"code": 1001, "message": "分类未设置"}
        )

        self.assertIs(outcome, PublishOutcome.FAILED)
        self.assertEqual(message, "分类未设置")

    def test_draft_url_keeps_only_real_fanqie_short_drafts(self):
        self.assertEqual(
            short_story_draft_url(
                "https://fanqienovel.com/main/writer/publish-short/123?enter_from=x"
            ),
            "https://fanqienovel.com/main/writer/publish-short/123?enter_from=x",
        )
        self.assertIsNone(short_story_draft_url("https://example.com/publish-short/123"))


if __name__ == "__main__":
    unittest.main()
