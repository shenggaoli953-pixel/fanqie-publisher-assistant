# 番茄后台实提交 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Submit the first local pending publishing day to Fanqie after explicit confirmation and verify it in chapter management.

**Architecture:** Keep chapter parsing and scheduling local. Add pure draft validation helpers plus an Edge CDP gateway that drives only the documented author-page flow and checks the remote row before returning success.

**Tech Stack:** Python 3.14, unittest, Tkinter, Playwright for Python, Microsoft Edge.

## Global Constraints

- Never store or print credentials, cookies, tokens, or verification codes.
- Submit only after a Tkinter confirmation dialog.
- Stop after the first platform or page error; do not retry or bypass limits.
- Chapter numbers sent to Fanqie are decimal integers without leading zeroes.

---

### Task 1: Validate backend draft fields

**Files:**
- Modify: `publisher/browser.py`
- Modify: `tests/test_browser.py`

- [ ] Write a failing test that a chapter number of `1` becomes `"1"` and a blank title raises `ValueError`.
- [ ] Run `python -m unittest tests.test_browser -v` and observe failure.
- [ ] Add a small pure helper returning validated number, title and body fields.
- [ ] Re-run the browser test module and observe success.

### Task 2: Expose one safe local batch

**Files:**
- Modify: `publisher/service.py`
- Modify: `tests/test_service.py`

- [ ] Write a failing test that the first pending, non-over-limit day is returned.
- [ ] Run `python -m unittest tests.test_service -v` and observe failure.
- [ ] Add the minimal `next_pending_day` service method.
- [ ] Re-run the service test module and observe success.

### Task 3: Add the live Edge gateway

**Files:**
- Modify: `publisher/browser.py`
- Modify: `tests/test_browser.py`

- [ ] Add a failing unit test for the pure remote-row matcher, including number, title and datetime.
- [ ] Run `python -m unittest tests.test_browser -v` and observe failure.
- [ ] Implement Edge launching/attachment, author page navigation, draft filling, comprehensive detection only, scheduled publication, AI selection, and chapter-manager verification. Treat an exhausted comprehensive-detection quota as a blocking error.
- [ ] Re-run the browser tests and use a non-submitting preflight check against the logged-in Edge session.

### Task 4: Connect the desktop UI

**Files:**
- Modify: `publisher/models.py`
- Modify: `publisher/ui.py`
- Modify: `main.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_ui.py`

- [ ] Write failing tests for persisting the per-book AI declaration and formatting the confirmation summary.
- [ ] Run the focused model and UI tests and observe failure.
- [ ] Add the AI declaration control, Edge opening/checking, first-day confirmation, gateway call and result recording.
- [ ] Re-run all unit tests.

### Task 5: Package and verify

**Files:**
- Modify: `build.ps1`
- Modify: `README.md`

- [ ] Update PyInstaller packaging to include Playwright runtime imports.
- [ ] Build a new executable without replacing the existing release.
- [ ] Launch the executable and verify the main window opens; do not submit a live chapter during packaging verification.
