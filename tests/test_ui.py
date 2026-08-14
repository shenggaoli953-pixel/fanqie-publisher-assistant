from datetime import date, datetime, time
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from publisher.browser import PreflightResult, PreflightStatus, SubmissionResult
from publisher.models import BookConfig, Chapter, PublishMode, RemoteChapter, ScheduledDay
from publisher.workflows import ShortStoryQueueReport
from publisher.ui import (
    PublisherApp,
    _BODY_BOLD_FONT,
    _BODY_FONT,
    _SHORT_STORY_CATEGORIES,
    _TITLE_FONT,
    _UI_THEMES,
    format_publish_confirmation,
    format_publish_preview_rows,
    format_schedule_detail_title,
    format_schedule_detail_rows,
    format_schedule_rows,
    parse_publish_end_chapter,
    parse_publish_start_date,
    parse_publish_times,
    schedule_row_tag,
)


class UiFormattingTests(unittest.TestCase):
    def test_short_story_preview_auto_fills_category_suggestion(self):
        class Service:
            def list_books(self):
                return []

        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "离婚九年，前夫要收回儿子的房子.txt"
            source.write_text(
                "离婚九年后，前夫带着律师找上门，要收回留给儿子的房子。"
                "婆婆指责我自私，我决定为儿子争回这个家。",
                encoding="utf-8",
            )
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(root.destroy)
            app = PublisherApp(root, Service(), object())
            app._story_source_var.set(str(source))

            app._update_story_preview()

        self.assertEqual(app._story_category_var.get(), "婚姻家庭")
        self.assertEqual(app._story_extra_var.get(), "家庭、婚恋")

    def test_short_story_extra_categories_can_be_added_and_removed(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        app._story_extra_choice_var.set("婚恋")

        app._add_story_extra_category()

        self.assertEqual(app._story_extra_var.get(), "婚恋")
        self.assertEqual(app._story_extra_list.get(0), "婚恋")
        app._story_extra_list.selection_set(0)
        app._remove_story_extra_category()

        self.assertEqual(app._story_extra_var.get(), "")

    def test_short_story_extra_categories_scroll_and_remove_later_item(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        categories = (
            "婚恋",
            "家庭",
            "虐文",
            "婆媳",
            "打脸逆袭",
            "现代",
            "追妻火葬场",
        )

        app._set_story_extra_categories(categories)

        self.assertTrue(hasattr(app, "_story_extra_scrollbar"))
        app._story_extra_list.yview_moveto(1.0)
        app._story_extra_list.selection_set(6)
        app._remove_story_extra_category()

        self.assertEqual(app._story_extra_list.cget("height"), 4)
        self.assertEqual(str(app._story_extra_scrollbar.cget("orient")), "vertical")
        self.assertEqual(app._story_extra_categories(), categories[:-1])

    def test_schedule_row_tag_gives_over_limit_precedence(self):
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 8, 0),
            chapters=(),
            over_limit=True,
            status="submitted",
        )

        self.assertEqual(schedule_row_tag(day), "over-limit")

    def test_schedule_row_tag_matches_each_publish_state(self):
        for status in ("pending", "partial", "submitted"):
            with self.subTest(status=status):
                day = ScheduledDay(
                    publish_at=datetime(2026, 7, 27, 8, 0),
                    chapters=(),
                    status=status,
                )

                self.assertEqual(schedule_row_tag(day), status)

    def test_app_builds_schedule_details_with_supported_tk_options(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)

        app = PublisherApp(root, Service(), object())

        self.assertEqual(app._detail_date_var.get(), "当天章节")
        self.assertEqual(app._story_category_var.get(), "")
        self.assertEqual(len(_SHORT_STORY_CATEGORIES), 24)
        self.assertIn("婚姻家庭", _SHORT_STORY_CATEGORIES)
        self.assertNotIn("追妻火葬场", _SHORT_STORY_CATEGORIES)

    def test_app_applies_workbench_styles_and_schedule_tags(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)

        app = PublisherApp(root, Service(), object())

        self.assertEqual(app._schedule.cget("style"), "App.Treeview")
        self.assertEqual(app._schedule_detail.cget("style"), "App.Treeview")
        self.assertEqual(app._schedule.cget("height"), 4)
        self.assertEqual(app._schedule_detail.cget("height"), 5)
        main_frame = app._schedule.master.master
        self.assertEqual(app._header.cget("height"), 64)
        self.assertEqual(app._header_subtitle_label.cget("text"), "创作工作台")
        self.assertEqual(app._book_context.cget("style"), "Context.TFrame")
        self.assertEqual(app._story_context.cget("style"), "Context.TFrame")
        self.assertEqual(app._settings_band.cget("style"), "Config.TFrame")
        self.assertEqual(app._range_band.cget("style"), "Config.TFrame")
        self.assertEqual(main_frame.grid_rowconfigure(6)["weight"], 1)
        self.assertEqual(main_frame.grid_rowconfigure(8)["weight"], 1)
        self.assertEqual(app._publish_button.cget("style"), "Primary.TButton")
        self.assertEqual(app._time_entry.cget("width"), 22)
        self.assertEqual(app._preview_button.cget("text"), "查看发布清单")
        self.assertEqual(app._recovery_button.cget("text"), "从失败处继续")
        self.assertEqual(app._diagnostic_button.cget("text"), "导出诊断")
        self.assertEqual(app._story_publish_button.cget("style"), "Primary.TButton")
        self.assertEqual(
            app._schedule.tag_configure("submitted")["foreground"],
            "#5D6B52",
        )

    def test_app_uses_a_readable_editorial_workbench_theme(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())

        self.assertEqual(app._header.cget("background"), "#FFFFFF")
        self.assertEqual(app._header_status.cget("width"), 18)
        self.assertEqual(
            ttk.Style(root).lookup("Primary.TButton", "background"),
            "#1F1F1F",
        )
        self.assertEqual(
            ttk.Style(root).lookup("Context.TFrame", "background"),
            "#F8F8F8",
        )
        self.assertEqual(
            ttk.Style(root).lookup("App.Treeview", "rowheight"),
            38,
        )
        self.assertIn("Segoe UI", ttk.Style(root).lookup("App.Treeview", "font"))
        self.assertEqual(
            app._schedule.tag_configure("alternating-row")["background"],
            "#FAFAFA",
        )

    def test_short_story_failure_keeps_browser_trace_out_of_header_status(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        app._selected_story_id = "story-1"
        app._save_short_story = lambda: True
        app._refresh_short_stories = lambda: None
        app._start_task = lambda _label, _operation, done: done(
            ShortStoryQueueReport(
                (),
                (),
                failed_name="夜航",
                error="Locator.click: Timeout 30000ms exceeded.",
            )
        )

        with patch("publisher.ui.messagebox.showerror") as show_error:
            app._start_publish_short_story()

        self.assertEqual(app._task_status_var.get(), "短故事发布未完成")
        show_error.assert_called_once()

    def test_theme_picker_applies_and_remembers_the_selected_theme(self):
        class Service:
            def list_books(self):
                return []

        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "ui-settings.json"
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(root.destroy)
            app = PublisherApp(
                root,
                Service(),
                object(),
                theme_settings_path=settings_path,
            )

            self.assertEqual(app._theme_name_var.get(), "Codex 浅色")
            self.assertEqual(
                app._theme_box.cget("values"),
                (
                    "Codex 浅色",
                    "Codex 柔白",
                    "Codex 深色",
                    "Codex 黑曜",
                    "Codex 石墨",
                    "Codex 暖灰",
                ),
            )
            app._theme_name_var.set("Codex 黑曜")
            app._apply_selected_theme()

            self.assertEqual(app._header.cget("background"), "#0D0D0D")
            self.assertEqual(app._books_list.cget("background"), "#161616")
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {"version": 3, "theme": "Codex 黑曜"},
            )

    def test_workbench_uses_the_codex_style_system_font_stack(self):
        self.assertEqual(_BODY_FONT, ("Segoe UI Variable Text", 10))
        self.assertEqual(_BODY_BOLD_FONT, ("Segoe UI Variable Text Semibold", 10))
        self.assertEqual(_TITLE_FONT, ("Segoe UI Variable Display Semib", 18))

    def test_codex_graphite_primary_button_keeps_white_text_readable(self):
        def relative_luminance(color: str) -> float:
            channels = tuple(int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))

            def linearize(channel: float) -> float:
                return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

            red, green, blue = (linearize(channel) for channel in channels)
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue

        palette = _UI_THEMES["Codex 石墨"]
        white_luminance = relative_luminance("#FFFFFF")
        for key in ("primary", "primary_active"):
            foreground_luminance = relative_luminance(palette[key])
            contrast = (white_luminance + 0.05) / (foreground_luminance + 0.05)
            self.assertGreaterEqual(contrast, 4.5, key)

    def test_legacy_warm_theme_preference_moves_to_codex_warm_gray(self):
        class Service:
            def list_books(self):
                return []

        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "ui-settings.json"
            settings_path.write_text(
                json.dumps({"theme": "暖灰橙"}, ensure_ascii=False),
                encoding="utf-8",
            )
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(root.destroy)

            app = PublisherApp(
                root,
                Service(),
                object(),
                theme_settings_path=settings_path,
            )

            self.assertEqual(app._theme_name_var.get(), "Codex 暖灰")
            self.assertEqual(
                json.loads(settings_path.read_text(encoding="utf-8")),
                {"version": 3, "theme": "Codex 暖灰"},
            )

    def test_invalid_theme_preference_uses_codex_light(self):
        class Service:
            def list_books(self):
                return []

        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "ui-settings.json"
            settings_path.write_text("not-json", encoding="utf-8")
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(root.destroy)

            app = PublisherApp(
                root,
                Service(),
                object(),
                theme_settings_path=settings_path,
            )

        self.assertEqual(app._theme_name_var.get(), "Codex 浅色")

    def test_legacy_theme_write_error_keeps_codex_warm_gray(self):
        class Service:
            def list_books(self):
                return []

        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "ui-settings.json"
            settings_path.write_text(
                json.dumps({"theme": "暖灰橙"}, ensure_ascii=False),
                encoding="utf-8",
            )
            root = tk.Tk()
            root.withdraw()
            self.addCleanup(root.destroy)

            with patch("pathlib.Path.write_text", side_effect=OSError):
                app = PublisherApp(
                    root,
                    Service(),
                    object(),
                    theme_settings_path=settings_path,
                )

        self.assertEqual(app._theme_name_var.get(), "Codex 暖灰")

    def test_minimum_window_keeps_schedule_panels_usable(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        root.geometry("980x680")
        root.update()

        self.assertEqual((root.winfo_width(), root.winfo_height()), (980, 680))
        self.assertGreaterEqual(app._schedule.winfo_height(), 65)
        self.assertGreaterEqual(app._schedule_detail.winfo_height(), 95)

    def test_publish_button_submits_all_pending_days_before_one_completion_notice(self):
        first_chapter = Chapter(Path("第001章-开始.txt"), 1, "开始", 1200, "hash")
        second_chapter = Chapter(Path("第002章-继续.txt"), 2, "继续", 1300, "hash")
        first_day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 0, 0),
            chapters=(first_chapter,),
        )
        second_day = ScheduledDay(
            publish_at=datetime(2026, 7, 28, 0, 0),
            chapters=(second_chapter,),
        )
        book = BookConfig(
            book_id="book-1",
            name="测试作品",
            source_dir=Path("."),
            publish_time=time(0, 0),
            mode=PublishMode.WORDS,
            limit=10000,
            next_chapter=1,
            publish_start_date=date(2026, 7, 27),
        )

        class Service:
            def __init__(self) -> None:
                self.days = [first_day, second_day]
                self.confirmed_batches: list[list[int]] = []
                self.recorded: list[int] = []

            def get_book(self, _book_id: str) -> BookConfig:
                return book

            def next_pending_day(self, _book_id: str, _remote_chapters=None) -> ScheduledDay:
                if not self.days:
                    raise ValueError("没有可提交的待发布章节")
                return self.days.pop(0)

            def reconcile_remote_submissions(
                self, _book_id: str, _remote_numbers: set[int]
            ) -> None:
                pass

            def confirm_batch(self, _book_id: str, chapter_numbers: list[int]) -> str:
                self.confirmed_batches.append(chapter_numbers)
                return f"token-{len(self.confirmed_batches)}"

            def record_submission(
                self,
                _book_id: str,
                chapter_number: int,
                _success: bool,
                _token: str,
                _error: str | None,
            ) -> None:
                self.recorded.append(chapter_number)

        class Gateway:
            def __init__(self) -> None:
                self.submitted_batches: list[list[int]] = []

            def launch(self) -> None:
                pass

            def preflight(self, _book_name: str) -> PreflightResult:
                return PreflightResult(PreflightStatus.READY, "ready")

            def existing_remote_chapters(self):
                return []

            def submit_batch(self, drafts, _book_name: str):
                self.submitted_batches.append([draft.chapter_number for draft in drafts])
                return [
                    SubmissionResult(chapter_number=draft.chapter_number, success=True)
                    for draft in drafts
                ]

        service = Service()
        gateway = Gateway()
        app = PublisherApp.__new__(PublisherApp)
        app._selected_book_id = book.book_id
        app._service = service
        app._gateway = gateway
        app._root = object()
        app._load_book = lambda _book_id: None

        with (
            patch("publisher.ui.read_chapter_body", return_value="正文"),
            patch(
                "publisher.ui.messagebox.askokcancel",
                side_effect=AssertionError("不应显示二次确认"),
            ),
            patch("publisher.ui.messagebox.showinfo") as showinfo,
        ):
            app._publish_first_day()

        self.assertEqual(service.confirmed_batches, [[1], [2]])
        self.assertEqual(service.recorded, [1, 2])
        self.assertEqual(gateway.submitted_batches, [[1], [2]])
        showinfo.assert_called_once_with(
            "发布完成",
            "已提交 2 章到番茄后台，未等待待发布状态。",
            parent=app._root,
        )

    def test_publish_reports_the_gateway_failure_when_later_drafts_are_not_returned(self):
        first_chapter = Chapter(Path("第001章-开始.txt"), 1, "开始", 1200, "hash")
        second_chapter = Chapter(Path("第002章-继续.txt"), 2, "继续", 1300, "hash")
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 0, 0),
            chapters=(first_chapter, second_chapter),
        )
        book = BookConfig(
            book_id="book-1",
            name="测试作品",
            source_dir=Path("."),
            publish_time=time(0, 0),
            mode=PublishMode.WORDS,
            limit=10000,
            next_chapter=1,
            publish_start_date=date(2026, 7, 27),
        )

        class Service:
            def __init__(self) -> None:
                self.recorded: list[tuple[int, bool, str | None]] = []

            def get_book(self, _book_id: str) -> BookConfig:
                return book

            def reconcile_remote_submissions(
                self, _book_id: str, _remote_numbers: set[int]
            ) -> None:
                pass

            def next_pending_day(self, _book_id: str, _remote_chapters=None) -> ScheduledDay:
                return day

            def confirm_batch(self, _book_id: str, _chapter_numbers: list[int]) -> str:
                return "token"

            def record_submission(
                self,
                _book_id: str,
                chapter_number: int,
                success: bool,
                _token: str,
                error: str | None,
            ) -> None:
                self.recorded.append((chapter_number, success, error))

        class Gateway:
            def launch(self) -> None:
                pass

            def preflight(self, _book_name: str) -> PreflightResult:
                return PreflightResult(PreflightStatus.READY, "ready")

            def existing_remote_chapters(self):
                return []

            def submit_batch(self, _drafts, _book_name: str):
                return [
                    SubmissionResult(
                        chapter_number=1,
                        success=False,
                        blocked=True,
                        error="章节内容写入后被后台清空，已停止提交",
                    )
                ]

        service = Service()
        app = PublisherApp.__new__(PublisherApp)
        app._selected_book_id = book.book_id
        app._service = service
        app._gateway = Gateway()
        app._root = object()
        app._load_book = lambda _book_id: None
        app._refresh_schedule = lambda: None

        with (
            patch("publisher.ui.read_chapter_body", return_value="正文"),
            patch("publisher.ui.messagebox.showerror") as showerror,
        ):
            app._publish_first_day()

        self.assertEqual(
            service.recorded,
            [(1, False, "章节内容写入后被后台清空，已停止提交")],
        )
        showerror.assert_called_once_with(
            "提交已停止",
            "第1章未提交：章节内容写入后被后台清空，已停止提交",
            parent=app._root,
        )

    def test_publish_confirmation_lists_the_day_chapters_and_ai_declaration(self):
        chapter = Chapter(Path("第001章-开始.txt"), 1, "开始", 1200, "hash")
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 0, 0),
            chapters=(chapter,),
        )

        summary = format_publish_confirmation(day, ai_generated=True)

        self.assertIn("2026-07-27 00:00", summary)
        self.assertIn("第1章 开始", summary)
        self.assertIn("总字数：1200", summary)
        self.assertIn("AI生成：是", summary)

    def test_check_edge_syncs_remote_chapter_status_into_the_schedule(self):
        book = BookConfig(
            book_id="book-1",
            name="测试作品",
            source_dir=Path("."),
            publish_time=time(0, 0),
            mode=PublishMode.WORDS,
            limit=10000,
            next_chapter=216,
            publish_start_date=date(2026, 7, 27),
        )
        remote = RemoteChapter(216, 1800, datetime(2026, 8, 1, 0, 0))

        class Service:
            def __init__(self) -> None:
                self.synced: tuple[str, set[int]] | None = None

            def get_book(self, _book_id: str) -> BookConfig:
                return book

            def reconcile_remote_submissions(
                self, book_id: str, remote_numbers: set[int]
            ) -> None:
                self.synced = (book_id, remote_numbers)

        class Gateway:
            def launch(self) -> None:
                pass

            def preflight(self, _book_name: str) -> PreflightResult:
                return PreflightResult(PreflightStatus.READY, "后台已连接")

            def existing_remote_chapters(self):
                return [remote]

        service = Service()
        app = PublisherApp.__new__(PublisherApp)
        app._selected_book_id = book.book_id
        app._service = service
        app._gateway = Gateway()
        app._root = object()
        app._load_book = lambda _book_id: None

        with patch("publisher.ui.messagebox.showinfo") as showinfo:
            app._check_edge()

        self.assertEqual(service.synced, (book.book_id, {216}))
        showinfo.assert_called_once_with(
            "后台检查",
            "后台已连接\n已同步 1 章状态。",
            parent=app._root,
        )

    def test_parse_publish_start_date_allows_a_paused_book(self):
        self.assertIsNone(parse_publish_start_date(""))
        self.assertEqual(parse_publish_start_date("2026-08-01"), date(2026, 8, 1))

    def test_parse_publish_end_chapter_allows_no_limit(self):
        self.assertIsNone(parse_publish_end_chapter(""))
        self.assertEqual(parse_publish_end_chapter("30"), 30)

    def test_parse_publish_times_normalizes_common_separators(self):
        self.assertEqual(
            parse_publish_times("8:00，12:00;20:00"),
            (time(8, 0), time(12, 0), time(20, 0)),
        )
        with self.assertRaisesRegex(ValueError, "发布时间"):
            parse_publish_times("12:00,08:00")
        with self.assertRaisesRegex(ValueError, "发布时间"):
            parse_publish_times("08:00,08:00")

    def test_save_policy_passes_the_complete_publish_time_list(self):
        class Service:
            def list_books(self):
                return []

            def update_policy(self, _book_id, **kwargs) -> None:
                self.kwargs = kwargs

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        service = Service()
        app = PublisherApp(root, service, object())
        app._selected_book_id = "book-1"
        app._mode_var.set(PublishMode.CHAPTERS.value)
        app._limit_var.set("3")
        app._time_var.set("08:00，12:00")
        app._start_date_var.set("2026-08-15")
        app._chapter_start_var.set("1")
        app._chapter_end_var.set("")
        app._load_book = lambda _book_id: None

        app._save_policy()

        self.assertEqual(service.kwargs["publish_time"], time(8, 0))
        self.assertEqual(
            service.kwargs["publish_times"],
            (time(8, 0), time(12, 0)),
        )

    def test_load_book_shows_recovery_controls_for_a_recorded_failure(self):
        book = BookConfig(
            book_id="book-1",
            name="测试作品",
            source_dir=Path("."),
            publish_time=time(8, 0),
            mode=PublishMode.CHAPTERS,
            limit=1,
            next_chapter=1,
            publish_start_date=date(2026, 8, 15),
        )

        class Service:
            def list_books(self):
                return []

            def get_book(self, _book_id: str) -> BookConfig:
                return book

            def get_schedule(self, _book_id: str):
                return []

            def failure_status(self, _book_id: str):
                return 8, "network error"

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())

        app._load_book(book.book_id)

        self.assertEqual(app._failure_var.get(), "第8章未完成")
        self.assertEqual(app._recovery_button.winfo_manager(), "pack")
        self.assertEqual(app._diagnostic_button.winfo_manager(), "pack")

    def test_export_diagnostics_uses_only_state_and_schedule(self):
        class Service:
            def list_books(self):
                return []

            def get_book_state(self, book_id: str):
                return {"book_id": book_id}

            def get_schedule(self, book_id: str):
                return [("schedule", book_id)]

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        app._selected_book_id = "book-1"
        destination = Path("C:/temp/fanqie-diagnostic.json")

        with (
            patch(
                "publisher.ui.filedialog.asksaveasfilename",
                return_value=str(destination),
            ),
            patch("publisher.ui.write_diagnostic_report", return_value=destination) as export,
            patch("publisher.ui.messagebox.showinfo") as show_info,
        ):
            app._export_diagnostics()

        export.assert_called_once_with(
            destination,
            version="0.2.0",
            state={"book_id": "book-1"},
            schedule=[("schedule", "book-1")],
        )
        show_info.assert_called_once()

    def test_format_rows_summarize_every_chapter_number_for_a_day(self):
        chapters = (
            Chapter(Path("第082章-合规负责人.txt"), 82, "她拒绝当合规负责人", 5715, "hash"),
            Chapter(Path("第083章-观察者.txt"), 83, "观察者不是一个人", 3850, "hash"),
            Chapter(Path("第084章-试验.txt"), 84, "她面试", 4020, "hash"),
        )
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 8, 0),
            chapters=chapters,
            over_limit=False,
            status="pending",
        )

        self.assertEqual(
            format_schedule_rows([day]),
            [("2026-07-27 08:00", "第82、83、84章（3章）", "13585", "待发布")],
        )

    def test_publish_preview_rows_list_each_chapter_without_body_text(self):
        chapter = Chapter(
            Path("第082章-合规负责人.txt"),
            82,
            "她拒绝当合规负责人",
            5715,
            "hash",
        )
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 8, 0),
            chapters=(chapter,),
            status="pending",
        )

        self.assertEqual(
            format_publish_preview_rows([day]),
            [("第82章", "她拒绝当合规负责人", "5715", "2026-07-27 08:00", "待发布")],
        )

    def test_format_schedule_detail_rows_keeps_each_chapter_on_its_own_row(self):
        chapters = (
            Chapter(Path("第082章-合规负责人.txt"), 82, "她拒绝当合规负责人", 5715, "hash"),
            Chapter(Path("第083章-观察者.txt"), 83, "观察者不是一个人", 3850, "hash"),
        )
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 8, 0),
            chapters=chapters,
        )

        self.assertEqual(
            format_schedule_detail_rows(day),
            [
                ("第82章", "她拒绝当合规负责人", "5715"),
                ("第83章", "观察者不是一个人", "3850"),
            ],
        )

    def test_format_schedule_detail_title_shows_time_and_total_characters(self):
        day = ScheduledDay(
            publish_at=datetime(2026, 7, 27, 8, 0),
            chapters=(
                Chapter(Path("第082章-合规负责人.txt"), 82, "合规负责人", 5715, "hash"),
                Chapter(Path("第083章-观察者.txt"), 83, "观察者", 3850, "hash"),
            ),
        )

        self.assertEqual(
            format_schedule_detail_title(day),
            "2026-07-27 08:00 | 9565 字 | 当天章节",
        )
