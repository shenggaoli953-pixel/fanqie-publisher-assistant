# Desktop UI and Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a polished, readable Windows desktop application with one stable executable and one desktop shortcut.

**Architecture:** Keep Tkinter/ttk to avoid a new runtime dependency, define a coherent theme and responsive panes, and package one canonical PyInstaller build that always points to the existing shared data directory.

**Tech Stack:** Tkinter/ttk, Pillow only if already available for icon conversion, PyInstaller, Windows shortcut COM.

## Global Constraints

- No nested decorative cards, oversized headings, gradients, or one-color dark/slate palette.
- Text must fit at 1020x680 and common 125% Windows scaling.
- The Edge window starts minimized but is not hidden or moved off-screen.
- The desktop contains exactly one shortcut named `番茄排程发布助手.lnk`.
- Existing old build folders may be archived or removed only after the final build passes.

---

### Task 1: Responsive workbench

**Files:**
- Modify: `publisher/ui.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: themed sidebar, notebook tabs, schedule/detail split, progress footer, log viewer, and stop/publish controls.

- [ ] Write failing widget-construction tests for supported Tk options, tab presence, progress state, and control enable/disable rules.
- [ ] Define fonts, colors, row heights, button styles, and stable grid weights.
- [ ] Replace technical mode values with Chinese labels while preserving stored enum values.
- [ ] Add inline connection and task states; reserve modal dialogs for final summary or actions requiring attention.
- [ ] Run UI tests and launch a local screenshot inspection at 1020x680 and 1440x900.

### Task 2: App identity and build

**Files:**
- Create: `assets/app-icon.png`
- Create: `assets/app-icon.ico`
- Replace: `FanqiePublisher.spec`
- Modify: `build.ps1`
- Modify: `main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `dist/FanqiePublisher/FanqiePublisher.exe` and shared `data` resolution independent of historical dist folder depth.

- [ ] Create an original tomato-orange book/clock icon and verify it at 16, 32, 48, and 256 px.
- [ ] Write failing tests for frozen and source data-directory resolution.
- [ ] Use one canonical spec with version metadata and icon.
- [ ] Build with `powershell -ExecutionPolicy Bypass -File .\build.ps1` and verify executable startup.

### Task 3: Final cleanup and acceptance

**Files:**
- Modify: `README.md`
- Test: all tests and packaged executable

**Interfaces:**
- Produces: one desktop shortcut targeting the canonical executable.

- [ ] Run `python -m unittest discover -v` and record the exact pass count.
- [ ] Launch the packaged executable and verify work list, schedule details, short-story tab, log tab, Edge restore behavior, and clean shutdown.
- [ ] Replace the existing desktop shortcut target, then enumerate the desktop and remove only obsolete Fanqie publisher shortcuts.
- [ ] Confirm `番茄排程发布助手.lnk` is the sole shortcut and its target exists.
- [ ] Run `agent-reach check-update` and record only an available update notice.
