import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from publisher.activity import RunControl
from publisher.models import NovelOperation
from publisher.qt_theme import QtThemeStore
from publisher.qt_ui import PublisherWindow


class FakeService:
    def list_books(self):
        return []

    def list_short_stories(self):
        return []


class QtUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_store_preserves_a_selected_theme(self):
        with TemporaryDirectory() as temporary:
            store = QtThemeStore(Path(temporary) / "ui-settings.json")

            store.save("Codex 黑曜")

            self.assertEqual(store.load(), "Codex 黑曜")

    def test_window_keeps_header_actions_reachable_at_minimum_width(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)
        window.resize(980, 680)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.minimumWidth(), 980)
        self.assertTrue(window.utility_menu_button.isVisible())
        self.assertGreater(window.utility_menu_button.geometry().right(), 0)
        self.assertLessEqual(
            window.utility_menu_button.geometry().right(), window.width()
        )

    def test_novel_page_has_a_resizable_book_list_and_primary_operation(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.novel_splitter.count(), 2)
        self.assertEqual(window.novel_operation_button.text(), "发布全部排程")

    def test_operation_picker_changes_the_primary_operation_label(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)

        window.novel_operation_box.setCurrentText("修改排期")

        self.assertEqual(window.novel_operation_button.text(), "修改排期")

    def test_short_story_extra_categories_remove_a_later_selected_item(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)
        categories = (
            "婚恋",
            "家庭",
            "虐文",
            "婆媳",
            "打脸逆袭",
            "现代",
            "追妻火葬场",
        )

        window.set_story_extra_categories(categories)
        window.story_extra_list.setCurrentRow(6)
        window.remove_story_extra_category()

        self.assertEqual(window.story_extra_categories(), categories[:-1])

    def test_short_story_extra_categories_show_all_seven_selected_items(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)
        categories = (
            "婚恋",
            "家庭",
            "虐文",
            "婆媳",
            "打脸逆袭",
            "现代",
            "追妻火葬场",
        )
        window.resize(1180, 800)
        window.navigation.setCurrentRow(1)
        window.set_story_extra_categories(categories)
        window.show()
        self.app.processEvents()

        last_item = window.story_extra_list.item(len(categories) - 1)
        last_rect = window.story_extra_list.visualItemRect(last_item)

        self.assertLessEqual(
            last_rect.bottom(), window.story_extra_list.viewport().height()
        )

    def test_running_task_disables_publish_controls_but_keeps_stop_available(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)

        window.set_task_controls_enabled(False)

        self.assertFalse(window.novel_operation_button.isEnabled())
        self.assertFalse(window.story_publish_button.isEnabled())
        self.assertFalse(window.story_open_edge_button.isEnabled())
        self.assertTrue(window.stop_task_button.isEnabled())

    def test_busy_publish_actions_keep_the_existing_stop_control(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)
        control = RunControl()
        window._task_running = True
        window._task_control = control
        window._selected_book_id = "book-1"

        window._start_publish_novel()
        window._start_direct_novel_operation(NovelOperation.IMMEDIATE)

        self.assertIs(window._task_control, control)
        self.assertEqual(window.task_status_label.text(), "已有任务正在运行")

    def test_main_uses_the_qt_run_app_entry_point(self):
        import main
        from publisher.qt_ui import run_app

        self.assertIs(main.run_app, run_app)

    def test_qt_runner_exports_the_application_runtime(self):
        from publisher.qt_ui import QApplication

        self.assertTrue(hasattr(QApplication, "instance"))

    def test_dark_theme_marks_scroll_content_with_the_theme_surface(self):
        window = PublisherWindow(FakeService(), object())
        self.addCleanup(window.close)

        window._apply_theme("Codex 深色")

        self.assertEqual(window.novel_editor.objectName(), "contentPane")
        self.assertEqual(window.story_editor.objectName(), "contentPane")

    def test_initial_window_size_keeps_a_margin_on_a_1200_pixel_screen(self):
        from publisher.qt_ui import initial_window_size

        self.assertEqual(initial_window_size(1200, 900), (1160, 800))
