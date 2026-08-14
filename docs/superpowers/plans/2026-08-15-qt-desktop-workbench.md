# Qt Desktop Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tkinter shell with a responsive Qt desktop workbench while keeping the publishing engine, local data, and Edge login state unchanged.

**Architecture:** Add a Qt presentation module that owns all widgets, dialogs, theme persistence, and task-event polling. It calls the existing application context, service, workflows, and browser gateway without changing their contracts. `main.py` starts the new `run_app()` entry point; the legacy Tkinter module remains out of the runtime path until a later cleanup release.

**Tech Stack:** Python 3.14, PySide6/Qt Widgets, unittest, Playwright, PyInstaller, Windows 11.

## Global Constraints

- Do not modify `data/`, Edge profiles, account workspace layout, publishing workflows, browser selectors, category rules, or remote submission behavior.
- Do not submit real chapters or short stories while validating the interface.
- Use `Segoe UI Variable Text` with fixed point sizes and `QFontMetrics.elidedText()` for variable-length header status.
- At `980x680`, every header action must remain reachable through the overflow menu and no header widget may overlap or exceed the window bounds.
- The shipped package must not contain `data/`, login details, browser profiles, cookies, or local manuscript files.

---

### Task 1: Add the Qt runtime and lock the responsive-shell contract

**Files:**
- Modify: `requirements.txt`
- Create: `tests/test_qt_ui.py`
- Create: `publisher/qt_theme.py`

**Interfaces:**
- Produces: `QtThemeStore(settings_path: Path | None)` with `load() -> str` and `save(theme_name: str) -> None`.
- Produces: `THEMES: dict[str, dict[str, str]]` for all six user-facing themes.

- [ ] **Step 1: Install the official Qt binding and record the resolved version**

Run:

```powershell
python -m pip install PySide6
python -m pip show PySide6
```

Expected: `PySide6` imports under Python 3.14 and the exact installed version can be pinned in `requirements.txt`.

- [ ] **Step 2: Write the failing theme-store and shell tests**

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication
from publisher.qt_theme import QtThemeStore
from publisher.qt_ui import PublisherWindow


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
        window.resize(980, 680)
        window.show()
        self.app.processEvents()
        self.assertTrue(window.utility_menu_button.isVisible())
        self.assertGreater(window.utility_menu_button.geometry().right(), 0)
        self.assertLessEqual(window.utility_menu_button.geometry().right(), window.width())
```

- [ ] **Step 3: Run the focused tests to verify they fail before the Qt modules exist**

Run:

```powershell
python -m unittest tests.test_qt_ui -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'publisher.qt_theme'`.

- [ ] **Step 4: Implement theme persistence and the minimal responsive shell**

```python
class QtThemeStore:
    def __init__(self, settings_path: Path | None) -> None:
        self._settings_path = settings_path

    def load(self) -> str:
        # Return the saved valid theme or the Codex light default.

    def save(self, theme_name: str) -> None:
        # Atomically persist only valid theme names.


class PublisherWindow(QMainWindow):
    def __init__(self, service, gateway, *, theme_settings_path=None, context=None) -> None:
        super().__init__()
        self.setMinimumSize(980, 680)
        self.utility_menu_button = QToolButton(self)
        self.utility_menu_button.setPopupMode(QToolButton.InstantPopup)
```

Create a header with brand, page title, eliding status label, task progress indicator, and a tool menu containing account, activity, help, update, and theme actions. Build a `QListWidget` navigation rail and `QStackedWidget` content host.

- [ ] **Step 5: Run focused tests to verify the shell passes**

Run:

```powershell
python -m unittest tests.test_qt_ui.QtUiTests.test_theme_store_preserves_a_selected_theme tests.test_qt_ui.QtUiTests.test_window_keeps_header_actions_reachable_at_minimum_width -v
```

Expected: PASS.

### Task 2: Implement the novel workbench using existing service contracts

**Files:**
- Modify: `publisher/qt_ui.py`
- Modify: `tests/test_qt_ui.py`

**Interfaces:**
- Consumes: `PublishingService`, `BookConfig`, `ScheduledDay`, `NovelOperation`, `run_novel_operation`, `publish_all_scheduled`, and `sync_novel_status`.
- Produces: `PublisherWindow.refresh_books()`, `load_book(book_id: str)`, `save_policy()`, `start_novel_operation()`.

- [ ] **Step 1: Write failing tests for operation labeling and a visible novel split layout**

```python
def test_novel_page_has_a_resizable_book_list_and_primary_operation(self):
    window = PublisherWindow(FakeService(), object())
    window.show()
    self.app.processEvents()
    self.assertEqual(window.novel_splitter.count(), 2)
    self.assertEqual(window.novel_operation_button.text(), "发布全部排程")

def test_operation_picker_changes_the_primary_operation_label(self):
    window = PublisherWindow(FakeService(), object())
    window.novel_operation_box.setCurrentText("修改排期")
    self.assertEqual(window.novel_operation_button.text(), "修改排期")
```

- [ ] **Step 2: Run the focused tests and observe the expected missing-widget failure**

Run:

```powershell
python -m unittest tests.test_qt_ui.QtUiTests.test_novel_page_has_a_resizable_book_list_and_primary_operation tests.test_qt_ui.QtUiTests.test_operation_picker_changes_the_primary_operation_label -v
```

Expected: FAIL because the novel page controls are absent.

- [ ] **Step 3: Build the novel page**

Use `QSplitter(Qt.Horizontal)` for the book list and a `QScrollArea` containing form sections. The right pane must include: book summary, policy fields, schedule table, day-detail table, sync/open Edge buttons, preview, recovery, diagnostics, and the operation combo plus primary operation button. Wire policy changes to the current service methods without duplicating scheduling logic.

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
python -m unittest tests.test_qt_ui -v
```

Expected: PASS for all Qt tests created so far.

### Task 3: Implement short-story editing, categories, and queue publishing controls

**Files:**
- Modify: `publisher/qt_ui.py`
- Modify: `tests/test_qt_ui.py`

**Interfaces:**
- Consumes: `ShortStoryConfig`, `scan_short_story_source`, `suggest_short_story_categories`, `publish_all_short_stories`.
- Produces: `PublisherWindow.set_story_extra_categories(categories: tuple[str, ...])`, `story_extra_list`, and `story_publish_button`.

- [ ] **Step 1: Write a failing test for scrolling to and deleting a later extra category**

```python
def test_short_story_extra_categories_remove_a_later_selected_item(self):
    window = PublisherWindow(FakeService(), object())
    categories = ("婚恋", "家庭", "虐文", "婆媳", "打脸逆袭", "现代", "追妻火葬场")
    window.set_story_extra_categories(categories)
    window.story_extra_list.setCurrentRow(6)
    window.remove_story_extra_category()
    self.assertEqual(window.story_extra_categories(), categories[:-1])
```

- [ ] **Step 2: Run the test to verify it fails before the short-story controls are present**

Run:

```powershell
python -m unittest tests.test_qt_ui.QtUiTests.test_short_story_extra_categories_remove_a_later_selected_item -v
```

Expected: FAIL with an attribute error for the missing category controls.

- [ ] **Step 3: Build the short-story page**

Use a second splitter with a story list and a scrollable form. Include source file and directory choices, cover image, primary category, add/remove extra category controls, AI and agreement checkboxes, read-only preview, save, open Edge, and “发布全部未发布短故事”. Reuse the current service and queue workflow exactly; do not run a browser action from a UI test.

- [ ] **Step 4: Run the focused short-story test**

Run:

```powershell
python -m unittest tests.test_qt_ui.QtUiTests.test_short_story_extra_categories_remove_a_later_selected_item -v
```

Expected: PASS.

### Task 4: Reconnect tasks, dialogs, accounts, entry point, and packaging

**Files:**
- Modify: `publisher/qt_ui.py`
- Modify: `main.py`
- Modify: `FanqiePublisher.spec`
- Modify: `tests/test_main.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ApplicationContext`, `ActivityLog`, `RunControl`, `check_for_update`, `asset_path`, and the existing workflow reports.
- Produces: `run_app(data_dir: Path) -> None` executed by `main.py`.

- [ ] **Step 1: Write failing tests for the Qt entry point and task-state protection**

```python
def test_main_starts_the_qt_entry_point(self):
    with patch("main.run_app") as run_app:
        runpy.run_module("main", run_name="__main__")
    run_app.assert_called_once()

def test_running_task_disables_publish_controls_but_keeps_stop_available(self):
    window = PublisherWindow(FakeService(), object())
    window.set_task_controls_enabled(False)
    self.assertFalse(window.novel_operation_button.isEnabled())
    self.assertTrue(window.stop_task_button.isEnabled())
```

- [ ] **Step 2: Run the focused tests and observe the expected failure**

Run:

```powershell
python -m unittest tests.test_main tests.test_qt_ui -v
```

Expected: FAIL until `main.py` points to the Qt runner and task-control methods exist.

- [ ] **Step 3: Connect the existing task queue and dialogs**

Port the current background-thread task wrapper and periodic queue drain to `QTimer`. Use `QMessageBox`, `QFileDialog`, `QDialog`, and `QDateEdit` for all former Tk dialogs. Keep batch completion as a single final notification and preserve stop semantics. Add `collect_all('PySide6')` to the spec and pin the installed PySide6 version.

- [ ] **Step 4: Verify launch and package configuration**

Run:

```powershell
python -m unittest tests.test_main tests.test_qt_ui -v
python -m compileall -q publisher tests main.py
```

Expected: PASS and no compile errors.

### Task 5: Run regression, visually inspect responsive sizes, package, and release

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `publisher/version.py`
- Verify: `tests/`, `build.ps1`, `release/FanqiePublisher/`

**Interfaces:**
- Consumes: complete Qt application and existing non-UI test suite.
- Produces: a verified `v0.5.0` package without private local data.

- [ ] **Step 1: Run the full regression suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: every existing publishing test and every Qt UI test passes.

- [ ] **Step 2: Visually inspect default and minimum windows**

Run source mode, then inspect at `1180x800` and `980x680`. Confirm the header status elides rather than overlaps, the utility menu remains reachable, the novel and short-story splitters remain usable, and category removal works after scrolling. Do not publish content.

- [ ] **Step 3: Build the distributable and inspect archive privacy**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
Compress-Archive -Path .\release\FanqiePublisher -DestinationPath .\release\FanqiePublisher-v0.5.0.zip -CompressionLevel Optimal
tar -tf .\release\FanqiePublisher-v0.5.0.zip
```

Expected: build passes and archive listing contains no `data/`, Edge profile, cookie, login, manuscript, or `.env` entry.

- [ ] **Step 4: Commit, tag, and publish the verified UI replacement**

Run:

```powershell
git add publisher main.py requirements.txt FanqiePublisher.spec tests CHANGELOG.md docs
git commit -m "feat: rebuild desktop workbench with Qt"
git tag -a v0.5.0 -m "Fanqie Publisher v0.5.0"
git push origin master v0.5.0
```

Expected: GitHub release is created only after the build archive is verified.
