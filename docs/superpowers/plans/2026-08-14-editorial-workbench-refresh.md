# Editorial Workbench Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the Tkinter publishing workbench so it has clearer typography, calmer structure, distinct themes, and a scrollable short-story extra-category list without altering any publishing behavior.

**Architecture:** Keep `PublisherApp` as the only presentation layer. Update its palette and ttk styles in `publisher/ui.py`, then make small, contained layout changes inside `_build_window()`, `_build_novel_tab()`, and `_build_short_story_tab()`. The extra-category widget continues to read and write the existing `_story_extra_var` through `_set_story_extra_categories()`; only its view gains a vertical scrollbar.

**Tech Stack:** Python 3.14, Tkinter/ttk, unittest, PyInstaller, Windows 11.

## Global Constraints

- Do not modify novel scheduling, remote synchronization, browser automation, short-story publishing workflow, category suggestion rules, data models, or the `data/` file format.
- Use `Segoe UI` only at fixed, readable control sizes; do not use a thin font weight or viewport-scaled font size.
- Keep all existing theme choices working and retain `ui-settings.json` persistence.
- Keep the main publish action as the only `Primary.TButton` in each publishing surface.
- Keep the extra-category limit at 7 and total category limit at 8.
- Do not send any real chapter or short-story submission during verification.

---

### Task 1: Lock the visual and category-list behavior with UI tests

**Files:**
- Modify: `tests/test_ui.py:50-68`
- Modify: `tests/test_ui.py:134-171`

**Interfaces:**
- Consumes: `PublisherApp(root, service, gateway)` and its existing `_set_story_extra_categories(categories: tuple[str, ...]) -> None` method.
- Produces: regression coverage for readable default styles and for deleting a selected category after the list has been scrolled.

- [ ] **Step 1: Write the failing typography and palette test**

Add this method to `UiFormattingTests` after `test_app_uses_the_quiet_writing_workbench_theme`:

```python
    def test_default_workbench_uses_readable_neutral_styles(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        style = ttk.Style(root)

        self.assertEqual(app._header.cget("background"), "#FFFFFF")
        self.assertEqual(style.lookup("Primary.TButton", "background"), "#1F1F1F")
        self.assertEqual(style.lookup("App.Treeview", "rowheight"), 38)
        self.assertIn("Segoe UI", style.lookup("App.Treeview", "font"))
```

- [ ] **Step 2: Write the failing scroll-and-delete test**

Replace the existing one-item removal assertion with this test method:

```python
    def test_short_story_extra_categories_scroll_and_remove_later_item(self):
        class Service:
            def list_books(self):
                return []

        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        app = PublisherApp(root, Service(), object())
        categories = ("婚恋", "家庭", "虐文", "婆媳", "打脸逆袭", "现代", "追妻火葬场")

        app._set_story_extra_categories(categories)
        app._story_extra_list.yview_moveto(1.0)
        app._story_extra_list.selection_set(6)
        app._remove_story_extra_category()

        self.assertEqual(app._story_extra_list.cget("height"), 4)
        self.assertEqual(app._story_extra_scrollbar.cget("orient"), "vertical")
        self.assertEqual(app._story_extra_categories(), categories[:-1])
```

- [ ] **Step 3: Run the focused tests to verify the new expectations fail**

Run:

```powershell
python -m unittest tests.test_ui.UiFormattingTests.test_default_workbench_uses_readable_neutral_styles tests.test_ui.UiFormattingTests.test_short_story_extra_categories_scroll_and_remove_later_item -v
```

Expected: FAIL because the old palette, table row height, list height, and scrollbar attribute do not yet match the new expectations.

- [ ] **Step 4: Commit the red tests**

```powershell
git add tests/test_ui.py
git commit -m "test: describe refreshed workbench UI"
```

### Task 2: Establish a crisp visual system and reorganize the main workbench

**Files:**
- Modify: `publisher/ui.py:31-208`
- Modify: `publisher/ui.py:334-590`
- Modify: `publisher/ui.py:593-927`

**Interfaces:**
- Consumes: `_UI_THEMES`, `_theme_name_var`, `_task_status_var`, existing `ttk` widget style names.
- Produces: a neutral default palette, fixed readable fonts, 38px schedule rows, and a lighter toolbar without changing callbacks or widget variables.

- [ ] **Step 1: Replace the default palette values with the approved neutral workbench palette**

Set the `Codex 浅色` palette entries that drive the default workspace to:

```python
        "canvas": "#F7F7F8",
        "surface": "#FFFFFF",
        "sidebar": "#EAECF0",
        "header": "#FFFFFF",
        "header_status": "#F0F0F0",
        "header_foreground": "#1F1F1F",
        "text": "#1F1F1F",
        "title": "#1F1F1F",
        "muted": "#707070",
        "section": "#303030",
        "primary": "#1F1F1F",
        "primary_active": "#000000",
        "secondary": "#F3F3F3",
        "entry_border": "#E0E0E0",
        "table_heading": "#F7F7F7",
        "table_selection": "#EAEAEA",
        "focus": "#5F5F5F",
```

Keep all status keys (`pending`, `partial`, `submitted`, `over_limit`) and all theme dictionary keys so `_configure_styles()` remains total for every theme.

- [ ] **Step 2: Apply readable fixed typography and compact workbench dimensions**

In `_configure_styles()`, keep the existing named styles but use these sizes:

```python
        body_font = ("Segoe UI", 10)
        body_bold_font = ("Segoe UI", 10, "bold")
        title_font = ("Segoe UI", 18, "bold")
        table_font = ("Segoe UI", 10)
```

Use those tuples for labels, entries, comboboxes, checkbuttons and treeviews. Configure `Title.TLabel` with `title_font`, `App.Treeview` with `rowheight=38` and `table_font`, and `App.Treeview.Heading` with `body_bold_font`. Keep all custom style names intact so existing tests and UI construction continue to use the same contracts.

- [ ] **Step 3: Rebalance the toolbar and page spacing without moving behavior**

Inside `_build_window()`:

```python
        self._root.minsize(980, 680)
        self._root.geometry("1180x800+40+40")
        self._header = tk.Frame(self._root, background=palette["header"], height=56)
```

Keep the title, theme selector, status label and progress bar in their existing order. Reduce their outer padding so the header is a compact toolbar. Keep the notebook and its tabs, but use `padx=16` and `pady=(10, 12)` for the main work area. In both `_build_novel_tab()` and `_build_short_story_tab()`, retain the sidebars and callbacks while applying `padding=(18, 18)` to sidebars; use `padding=(24, 12)` for the novel work surface so both schedule tables remain usable at the minimum window size.

- [ ] **Step 4: Run the visual and existing UI tests**

Run:

```powershell
python -m unittest tests.test_ui -v
```

Expected: PASS, including the new default palette and typography expectation.

- [ ] **Step 5: Commit the visual-system work**

```powershell
git add publisher/ui.py tests/test_ui.py
git commit -m "feat: refresh publishing workbench visuals"
```

### Task 3: Make short-story extra categories scrollable and removable at any position

**Files:**
- Modify: `publisher/ui.py:1032-1061`
- Test: `tests/test_ui.py:50-78`

**Interfaces:**
- Consumes: `_story_extra_list: tk.Listbox`, `_story_extra_categories() -> tuple[str, ...]`, `_set_story_extra_categories(categories: tuple[str, ...]) -> None`, and `_remove_story_extra_category() -> None`.
- Produces: `_story_extra_scrollbar: ttk.Scrollbar` connected to the listbox through `yscrollcommand` and `yview`.

- [ ] **Step 1: Add a scrollbar container around the existing listbox**

Replace the standalone listbox grid block with this structure:

```python
        extra_list_frame = ttk.Frame(form, style="Surface.TFrame")
        extra_list_frame.grid(
            row=7, column=1, columnspan=2, sticky="nsew", padx=(12, 8), pady=(7, 4)
        )
        extra_list_frame.columnconfigure(0, weight=1)
        self._story_extra_list = tk.Listbox(
            extra_list_frame,
            height=4,
            exportselection=False,
            borderwidth=0,
            activestyle="none",
            font=("Segoe UI", 10),
        )
        self._story_extra_list.grid(row=0, column=0, sticky="nsew")
        self._story_extra_scrollbar = ttk.Scrollbar(
            extra_list_frame,
            orient="vertical",
            command=self._story_extra_list.yview,
        )
        self._story_extra_scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self._story_extra_list.configure(yscrollcommand=self._story_extra_scrollbar.set)
        self._configure_listbox_theme(self._story_extra_list, self._theme_palette())
```

Retain the label, remove button and `_set_story_extra_categories()` implementation. Do not add a separate data collection or change category order.

- [ ] **Step 2: Run the focused category test**

Run:

```powershell
python -m unittest tests.test_ui.UiFormattingTests.test_short_story_extra_categories_scroll_and_remove_later_item -v
```

Expected: PASS. The seventh selected category is removed even after the listbox has been scrolled.

- [ ] **Step 3: Commit the category-list behavior**

```powershell
git add publisher/ui.py tests/test_ui.py
git commit -m "feat: scroll short story extra categories"
```

### Task 4: Verify the full application and package it

**Files:**
- Verify only: `publisher/ui.py`
- Verify only: `tests/`
- Generated and ignored: `release/FanqiePublisher/`

**Interfaces:**
- Consumes: all existing publication services and the updated `PublisherApp`.
- Produces: a verified local build; no external submission or data migration.

- [ ] **Step 1: Run the complete regression suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Build the distributable package**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Expected: test suite passes first and `release/FanqiePublisher/FanqiePublisher.exe` is generated.

- [ ] **Step 3: Launch source mode and inspect the finished layout**

Run:

```powershell
Start-Process pythonw.exe -ArgumentList 'main.py' -WorkingDirectory 'C:\Users\11038\Documents\电赛小说\番茄排程发布助手'
```

Inspect the default and minimum window sizes. Confirm that the novel page, short-story page, theme selector, category scrollbar and delete action are visible. Close the local window after inspection without submitting anything to Fanqie.

- [ ] **Step 4: Commit final verification-only documentation if any test expectation needed adjustment**

Run:

```powershell
git status --short
```

Expected: clean worktree. Do not create a no-op commit.
