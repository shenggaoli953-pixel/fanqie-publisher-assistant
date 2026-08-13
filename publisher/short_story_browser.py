from dataclasses import dataclass
from html import escape
from pathlib import Path
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from publisher.browser import (
    EdgePublisherGateway,
    PublishBlockedError,
    PublishOutcome,
)
from publisher.short_story import (
    ShortStoryConfig,
    ShortStoryDraft,
    scan_short_story_source,
    validate_short_story_config,
)


_NEW_STORY_URL = (
    "https://fanqienovel.com/main/writer/publish-short/?enter_from=NEWCHAPTER_1"
)
_SHORT_STORY_MANAGER_URL = "https://fanqienovel.com/main/writer/short-manage/"
_DRAFT_URL = re.compile(
    r"^https://fanqienovel\.com/main/writer/publish-short/\d+(?:\?.*)?$"
)


class ShortStoryAgreementRequired(PublishBlockedError):
    def __init__(
        self, draft_url: str, agreement_name: str = "字体与图片上传协议"
    ) -> None:
        super().__init__(
            "短故事草稿已准备完成。请在 Edge 中阅读并同意番茄的"
            f"《{agreement_name}》，然后再次点击发布短故事。"
        )
        self.draft_url = draft_url


class ShortStorySubmissionError(PublishBlockedError):
    def __init__(self, draft_url: str, message: str) -> None:
        super().__init__(message)
        self.draft_url = draft_url


@dataclass(frozen=True)
class ShortStorySubmissionResult:
    success: bool
    draft_url: str | None = None
    error: str | None = None


def requires_cover_agreement(drawer_text: str, agreed: bool) -> bool:
    return (
        not agreed
        and "字体许可使用协议" in drawer_text
        and "图片上传协议" in drawer_text
    )


def requires_publication_agreement(modal_text: str) -> bool:
    return "我已阅读并同意" in modal_text and "创作收益" in modal_text


def short_story_draft_url(value: str) -> str | None:
    return value if _DRAFT_URL.fullmatch(value) else None


def interpret_short_publish_response(payload: object) -> tuple[PublishOutcome, str]:
    if not isinstance(payload, dict):
        return PublishOutcome.UNKNOWN, "短故事发布接口没有返回可识别结果"
    message = str(payload.get("message") or payload.get("msg") or "").strip()
    code = payload.get("code")
    if code == 0:
        return PublishOutcome.SUCCESS, message or "发布成功"
    if code is None:
        return PublishOutcome.UNKNOWN, message or "短故事发布接口没有返回结果代码"
    return PublishOutcome.FAILED, message or f"短故事发布接口返回代码 {code}"


def story_body_html(body: str) -> str:
    return "".join(
        f"<p>{escape(line.strip())}</p>"
        for line in body.splitlines()
        if line.strip()
    )


class ShortStoryPublisher:
    def __init__(self, gateway: EdgePublisherGateway) -> None:
        self._gateway = gateway

    def published_titles(self) -> set[str]:
        self._gateway.launch()
        page = self._gateway.current_page
        try:
            with page.expect_response(
                lambda response: "/api/author/short_article/list/v0/"
                in response.url,
                timeout=10000,
            ) as response_info:
                page.goto(_SHORT_STORY_MANAGER_URL, wait_until="domcontentloaded")
            return self._published_titles_from_api(
                page.context.request,
                response_info.value.url,
                response_info.value.json(),
            )
        except Exception:
            page.wait_for_timeout(1800)
        return self._published_titles(page)

    def submit(self, config: ShortStoryConfig) -> ShortStorySubmissionResult:
        validate_short_story_config(config)
        draft = scan_short_story_source(config.source_path)
        self._validate_draft(draft, config)
        self._gateway.launch()
        page = self._gateway.current_page
        draft_url = self._open_draft(page, config.remote_draft_url)
        try:
            self._fill_story_fields(page, draft)
            self._select_categories(page, config)
            self._set_ai_declaration(page, config.ai_generated)
            self._set_trial_position(page, config.trial_enabled)
            self._set_publication_consent(
                page, config.consent_confirmed, draft_url
            )
            self._upload_cover(page, config.cover_path, draft_url)
            outcome, message = self._publish(page)
        except ShortStoryAgreementRequired:
            raise
        except Exception as error:
            raise ShortStorySubmissionError(draft_url, str(error)) from error
        if outcome is PublishOutcome.SUCCESS:
            return ShortStorySubmissionResult(True)
        return ShortStorySubmissionResult(False, draft_url, message)

    @staticmethod
    def _validate_draft(draft: ShortStoryDraft, config: ShortStoryConfig) -> None:
        if re.search(r"\s", draft.title):
            raise ValueError("短故事标题不能包含空格")
        if draft.character_count < 5000:
            raise ValueError("番茄短故事设置试读位置前，正文至少需要 5000 字")
        if draft.character_count > 100000:
            raise ValueError("番茄短故事正文不能超过 100000 字")
        if not config.trial_enabled:
            raise ValueError("番茄短故事发布前必须设置试读位置")
        if not config.consent_confirmed:
            raise ValueError("请先勾选已阅读番茄短故事发布事项")

    @staticmethod
    def _published_titles(page) -> set[str]:
        rows = page.locator(".short-article-item")
        published: set[str] = set()
        for index in range(rows.count()):
            row = rows.nth(index)
            if "已发布" not in row.inner_text():
                continue
            title = row.locator(".article-item-title").last
            if title.count():
                value = title.inner_text().strip()
                if value:
                    published.add(value)
        return published

    @staticmethod
    def _published_titles_from_api(
        request, first_url: str, first_payload: object
    ) -> set[str]:
        parsed = urlsplit(first_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        page_count = max(1, int(query.get("page_count", ["10"])[0]))
        titles: set[str] = set()
        total_count: int | None = None
        page_index = 0
        while total_count is None or page_index * page_count < total_count:
            if page_index == 0:
                payload = first_payload
            else:
                query["page_index"] = [str(page_index)]
                url = urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        urlencode(query, doseq=True),
                        "",
                    )
                )
                payload = request.get(url, timeout=10000).json()
            if not isinstance(payload, dict) or payload.get("code") != 0:
                raise PublishBlockedError("短故事后台列表接口返回异常")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise PublishBlockedError("短故事后台列表缺少数据")
            total_count = int(data.get("total_count", 0))
            items = data.get("item_list")
            if not isinstance(items, list):
                raise PublishBlockedError("短故事后台列表格式异常")
            for item in items:
                if not isinstance(item, dict) or item.get("display_status") != 1:
                    continue
                titles.update(
                    str(title).strip()
                    for title in item.get("multi_title", ())
                    if str(title).strip()
                )
            if not items:
                break
            page_index += 1
        return titles

    @staticmethod
    def _open_draft(page, saved_url: str | None) -> str:
        target = short_story_draft_url(saved_url or "") or _NEW_STORY_URL
        page.goto(target, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        current = short_story_draft_url(page.url)
        if current is None:
            raise PublishBlockedError("番茄没有创建短故事草稿")
        if target == _NEW_STORY_URL:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
        ShortStoryPublisher._resume_recent_draft(page)
        return current

    @staticmethod
    def _resume_recent_draft(page) -> None:
        for _ in range(6):
            resume = page.get_by_text("继续编辑", exact=True).last
            if resume.count() and resume.is_visible():
                resume.click()
                page.wait_for_timeout(500)
                return
            page.wait_for_timeout(700)

    @staticmethod
    def _fill_story_fields(page, draft: ShortStoryDraft) -> None:
        title = page.locator("textarea[placeholder='请输入短故事名称']")
        editor = page.locator(".ProseMirror.payNode-helper-content").first
        for locator in (title, editor):
            locator.wait_for(state="visible", timeout=10000)

        expected_body = _compact_text(draft.body)
        for attempt in range(3):
            if attempt:
                title.fill(draft.title)
                page.wait_for_timeout(400)
            used_adapter = False
            try:
                page.evaluate(
                    "html => window.adapter.setHTML(html)",
                    story_body_html(draft.body),
                )
                used_adapter = True
            except (AttributeError, AssertionError):
                editor.focus()
                page.keyboard.press("Control+A")
                page.keyboard.insert_text(draft.body)
            page.wait_for_timeout(900)
            title.fill(draft.title)
            if used_adapter:
                editor.focus()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text(" ")
                page.keyboard.press("Backspace")
            page.wait_for_timeout(700)
            if (
                title.input_value().strip() == draft.title
                and _compact_text(
                    ShortStoryPublisher._editor_text(page, editor)
                )
                == expected_body
            ):
                page.wait_for_timeout(500)
                if (
                    title.input_value().strip() == draft.title
                    and _compact_text(
                        ShortStoryPublisher._editor_text(page, editor)
                    )
                    == expected_body
                ):
                    return
        raise PublishBlockedError("短故事标题或正文被后台清空，已停止提交")

    @staticmethod
    def _editor_text(page, editor) -> str:
        try:
            return str(page.evaluate("() => window.adapter.getText()"))
        except (AttributeError, AssertionError):
            return editor.inner_text()

    @staticmethod
    def _select_categories(page, config: ShortStoryConfig) -> None:
        selected = page.locator(".publish-short-category-select-selected-list")
        wanted = (config.primary_category, *config.extra_categories)
        for category in wanted:
            if ShortStoryPublisher._category_is_selected(selected, category):
                continue
            option_was_visible = False
            for _ in range(3):
                page.locator(
                    ".publish-short-category-select-selected-list"
                ).first.click(force=True)
                page.wait_for_timeout(500)
                option = page.get_by_text(category, exact=True).last
                if option.count() == 0 or not option.is_visible():
                    for group in ("主分类", "情节", "角色", "情绪", "背景"):
                        tab = page.get_by_text(group, exact=True).last
                        if tab.count() and tab.is_visible():
                            tab.hover()
                            page.wait_for_timeout(300)
                        if option.count() and option.is_visible():
                            break
                if option.count() == 0 or not option.is_visible():
                    continue
                option_was_visible = True
                try:
                    option.click(force=True)
                except Exception:
                    continue
                page.wait_for_timeout(300)
                if ShortStoryPublisher._category_is_selected(selected, category):
                    break
            else:
                if not option_was_visible:
                    raise PublishBlockedError(
                        f"番茄后台没有短故事分类：{category}"
                    )
                raise PublishBlockedError(f"短故事分类未生效：{category}")
        ShortStoryPublisher._close_category_picker(page)

    @staticmethod
    def _close_category_picker(page) -> None:
        picker = page.locator(
            ".publish-short-category-select.arco-dropdown-open"
        ).last
        if picker.count() == 0 or not picker.is_visible():
            return
        try:
            picker.locator(
                ".publish-short-category-select-icon"
            ).click(force=True)
        except Exception:
            page.locator(
                ".publish-short-category-select-selected-list"
            ).first.click(force=True)
        for _ in range(4):
            page.wait_for_timeout(250)
            if not picker.is_visible():
                return
        raise PublishBlockedError("短故事分类已选择，但分类浮层未收起")

    @staticmethod
    def _category_is_selected(selected, category: str) -> bool:
        try:
            label = selected.get_by_text(category, exact=True).last
            if label.count() and label.is_visible():
                return True
        except (AttributeError, AssertionError):
            pass
        try:
            return category in {
                value.strip()
                for value in selected.locator(
                    ".publish-short-category-select-selected"
                ).all_inner_texts()
            }
        except (AttributeError, AssertionError):
            return category in re.split(r"[、,，\s]+", selected.inner_text())

    @staticmethod
    def _set_ai_declaration(page, ai_generated: bool) -> None:
        value = "1" if ai_generated else "2"
        radio = page.locator(f"input[type='radio'][value='{value}']")
        if radio.count() == 0:
            raise PublishBlockedError("短故事页面没有 AI 生成声明")
        try:
            radio.check(force=True)
        except Exception:
            try:
                radio.click(force=True)
            except Exception:
                radio.evaluate("input => input.click()")
        if not radio.is_checked():
            raise PublishBlockedError("短故事 AI 生成声明未生效")

    @staticmethod
    def _set_trial_position(page, enabled: bool) -> None:
        if not enabled:
            return
        button = page.get_by_role("button", name="去设置", exact=True)
        if button.count() == 0 or not button.is_enabled():
            raise PublishBlockedError("短故事正文未达到试读位置设置要求")
        button.click()
        page.wait_for_timeout(400)
        try:
            has_pay_node = page.evaluate(
                "() => window.adapter.getExistNodes('payNode').length > 0"
            )
        except (AttributeError, AssertionError):
            has_pay_node = True
        if not has_pay_node:
            raise PublishBlockedError("短故事试读位置设置未生效")

    @staticmethod
    def _set_publication_consent(
        page, confirmed: bool, draft_url: str
    ) -> None:
        if not confirmed:
            return
        consent = page.locator(
            ".publish-short-config-signLicense input[type='checkbox']"
        )
        if consent.count() == 0:
            raise PublishBlockedError("短故事页面没有发布事项确认框")
        if not consent.is_checked():
            try:
                consent.check(force=True)
            except Exception:
                try:
                    consent.click(force=True)
                except Exception:
                    consent.evaluate("input => input.click()")
            page.wait_for_timeout(400)
        agreement = page.locator(".publish-short-license-modal").last
        if agreement.count() and agreement.is_visible():
            if requires_publication_agreement(agreement.inner_text()):
                accept = agreement.get_by_role(
                    "button", name="我已阅读并同意", exact=True
                ).last
                if accept.count() == 0:
                    accept = agreement.get_by_text(
                        "我已阅读并同意", exact=True
                    ).last
                if accept.count() == 0:
                    raise PublishBlockedError("短故事发布协议没有同意按钮")
                accept.click(force=True)
                agreement.wait_for(state="hidden", timeout=10000)
        if not consent.is_checked():
            raise PublishBlockedError("短故事发布事项确认未生效")

    @staticmethod
    def _upload_cover(page, cover_path: Path, draft_url: str) -> None:
        page.locator(".publish-short-config-cover-container").click(force=True)
        drawer = page.locator(".byte-drawer").last
        drawer.wait_for(state="visible", timeout=5000)
        if ShortStoryPublisher._drawer_requires_agreement(drawer):
            agreement = drawer.locator("input[type='checkbox']").last
            try:
                agreement.check(force=True)
            except Exception:
                try:
                    agreement.click(force=True)
                except Exception:
                    agreement.evaluate("input => input.click()")
            if not agreement.is_checked():
                raise PublishBlockedError("封面字体与图片上传协议未生效")
            enable = drawer.get_by_role(
                "button", name="开启AI插图功能", exact=True
            ).last
            if enable.count() == 0:
                raise PublishBlockedError("封面协议页面没有开启按钮")
            enable.click(force=True)
            page.wait_for_timeout(500)
            drawer = page.locator(".byte-drawer").last
            if ShortStoryPublisher._drawer_requires_agreement(drawer):
                raise PublishBlockedError("封面字体与图片上传协议未完成")

        local_upload = drawer.get_by_text("本地上传", exact=True).last
        if local_upload.count() == 0:
            raise PublishBlockedError("短故事封面窗口没有本地上传页签")
        local_upload.click(force=True)
        page.wait_for_timeout(300)
        upload = drawer.locator("input[type='file']")
        if upload.count() == 0:
            raise PublishBlockedError("短故事封面窗口没有本地上传入口")
        upload.set_input_files(str(cover_path))
        page.wait_for_timeout(300)
        for _ in range(2):
            confirm = drawer.get_by_role("button", name="确定", exact=True).last
            if confirm.count() == 0:
                confirm = drawer.get_by_role(
                    "button", name="确认上传", exact=True
                ).last
            if confirm.count() == 0:
                break
            confirm.wait_for(state="visible", timeout=5000)
            confirm.click(force=True)
            page.wait_for_timeout(500)
            upload_confirm = drawer.get_by_role(
                "button", name="确认上传", exact=True
            ).last
            if upload_confirm.count() and upload_confirm.is_visible():
                upload_confirm.click(force=True)
                page.wait_for_timeout(500)
            if not drawer.is_visible():
                break
        if ShortStoryPublisher._drawer_requires_agreement(drawer):
            raise ShortStoryAgreementRequired(
                draft_url, "字体与图片上传协议"
            )
        try:
            drawer.wait_for(state="hidden", timeout=8000)
        except Exception as error:
            raise PublishBlockedError("短故事封面上传后未完成") from error

    @staticmethod
    def _drawer_requires_agreement(drawer) -> bool:
        if not drawer.count() or not drawer.is_visible():
            return False
        text = drawer.inner_text()
        checks = drawer.locator("input[type='checkbox']")
        agreed = bool(checks.count() and checks.last.is_checked())
        return requires_cover_agreement(text, agreed)

    @staticmethod
    def _publish(page) -> tuple[PublishOutcome, str]:
        for _ in range(8):
            dialog = ShortStoryPublisher._visible_publish_dialog(page)
            if dialog is not None:
                dialog_text = dialog.inner_text()
                if "我已阅读并同意" in dialog_text:
                    agree = dialog.get_by_role(
                        "button", name="我已阅读并同意", exact=True
                    ).last
                    if agree.count() and agree.is_visible():
                        agree.click(force=True)
                        page.wait_for_timeout(500)
                        continue
                if "是否继续发布" in dialog_text:
                    continue_publish = dialog.get_by_role(
                        "button", name="继续发布", exact=True
                    ).last
                    if continue_publish.count() == 0:
                        continue_publish = dialog.locator(
                            "button:has-text('继续发布')"
                        ).last
                    if continue_publish.count() and continue_publish.is_visible():
                        continue_publish.click(force=True)
                        return ShortStoryPublisher._wait_for_submission_confirmation(
                            page
                        )
                if "提交确认" in dialog_text:
                    return ShortStoryPublisher._confirm_submission(page, dialog)

            next_step = page.get_by_role(
                "button", name="下一步", exact=True
            ).last
            if (
                next_step.count()
                and next_step.is_visible()
                and next_step.is_enabled()
            ):
                next_step.click()
                page.wait_for_timeout(700)
                continue
            break

        body_text = page.locator("body").inner_text()
        for indicator in (
            "请上传封面",
            "请选择作品分类",
            "请设置试读位置",
            "请勾选发布协议",
            "正文至少输入",
            "审核问题",
        ):
            if indicator in body_text:
                raise PublishBlockedError(indicator)
        raise PublishBlockedError("短故事未进入提交确认页面")

    @staticmethod
    def _visible_publish_dialog(page):
        dialog = page.get_by_role("dialog").last
        if dialog.count() and dialog.is_visible():
            return dialog
        for selector in (
            ".arco-modal",
            ".byte-modal-wrapper",
        ):
            dialog = page.locator(selector).last
            if dialog.count() and dialog.is_visible():
                return dialog
        return None

    @staticmethod
    def _wait_for_submission_confirmation(page) -> tuple[PublishOutcome, str]:
        for _ in range(12):
            dialog = ShortStoryPublisher._visible_publish_dialog(page)
            if dialog is not None and "提交确认" in dialog.inner_text():
                return ShortStoryPublisher._confirm_submission(page, dialog)
            page.wait_for_timeout(500)
        raise PublishBlockedError("短故事继续发布后未进入提交确认页面")

    @staticmethod
    def _confirm_submission(page, dialog) -> tuple[PublishOutcome, str]:
        confirm = None
        for name in ("确认", "确定", "提交"):
            candidate = dialog.get_by_role("button", name=name, exact=True)
            if candidate.count() and candidate.is_visible():
                confirm = candidate
                break
        if confirm is None:
            raise PublishBlockedError("短故事提交确认窗口没有确认按钮")
        try:
            with page.expect_response(
                lambda response: (
                    "/api/author/short_article/publish/v0/" in response.url
                ),
                timeout=15000,
            ) as response_info:
                confirm.click()
            return interpret_short_publish_response(response_info.value.json())
        except Exception:
            return PublishOutcome.UNKNOWN, "短故事确认后未收到番茄发布结果"


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)
