import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
