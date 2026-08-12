# Reliable Novel Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every novel chapter submission observable, recoverable, and verifiably reflected in Fanqie's chapter manager.

**Architecture:** Keep the existing service and JSON schedule, but replace optimistic page automation with a single-page state machine. A background job runner emits progress events to Tkinter and records local diagnostics.

**Tech Stack:** Python 3.14, Tkinter/ttk, Playwright sync API over Edge CDP, unittest, PyInstaller.

## Global Constraints

- Preserve existing `data/books.json` and `data/state/*.json` without resetting submitted chapters.
- Never read or log browser cookies, passwords, tokens, request headers, or storage state.
- Edge launches minimized and remains restorable from the Windows taskbar.
- Only a verified platform response or chapter-manager reconciliation may mark a chapter successful.
- This directory is not a Git repository, so test gates replace commit steps.

---

### Task 1: Diagnostics and result types

**Files:**
- Create: `publisher/activity_log.py`
- Modify: `publisher/browser.py`
- Test: `tests/test_activity_log.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Produces: `PublishStage`, `ProgressEvent`, `FailureKind`, and `ActivityLog`.
- Produces: `SubmissionResult` fields `verified`, `failure_kind`, and `details` with backward-compatible defaults.

- [ ] Write failing tests for log rotation, redaction, and result defaults.
- [ ] Run `python -m unittest tests.test_activity_log tests.test_browser -v` and verify failure.
- [ ] Implement a 2 MB rotating UTF-8 log with three backups and failure screenshot paths.
- [ ] Run the focused tests and verify pass.

### Task 2: One controlled Edge page

**Files:**
- Modify: `publisher/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Produces: `EdgePublisherGateway._ensure_work_page()` and `_goto_with_login_retry(url)`.
- Guarantees: one app-controlled page per dedicated profile; stale app pages are closed only inside that profile.

- [ ] Write failing tests proving repeated `launch()` reuses the work page and navigation waits through one delayed login redirect.
- [ ] Run `python -m unittest tests.test_browser.BrowserTests -v` and verify failure.
- [ ] Reuse a live page instead of unconditional `context.new_page()`, wait for delayed SPA redirects, and preserve visible/minimized Edge launch behavior.
- [ ] Run browser tests and verify pass.

### Task 3: Stable draft filling

**Files:**
- Modify: `publisher/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Produces: `_wait_for_editor_ready(page)`, `_write_body(page, body)`, `_write_metadata(page, fields)`, and `_verify_draft(page, fields)`.
- `_fill_draft_fields(page, fields)` writes body first, waits for stability, writes number/title last, and verifies immediately before returning.

- [ ] Write a fake page test where first body write asynchronously clears number/title.
- [ ] Run the focused test and verify the old metadata-first implementation fails.
- [ ] Implement readiness waits, body-first order, two stable observations 500 ms apart, and final metadata verification.
- [ ] Add a test that `chapter_number` remains unpadded decimal text.
- [ ] Run all browser tests and verify pass.

### Task 4: Verified submission and reconciliation

**Files:**
- Modify: `publisher/browser.py`
- Modify: `publisher/service.py`
- Test: `tests/test_browser.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Produces: `_wait_publish_result(page, confirm_button)` returning `success`, `daily_limit`, `failed`, or `unknown`.
- Produces: `reconcile_remote_submissions()` that merges verified remote chapters without discarding older valid local history outside the active range.

- [ ] Write failing tests for `code == 0`, nonzero code, dialog disappearance without confirmation, daily limit, and unknown-result manager reconciliation.
- [ ] Run browser and service tests and verify failure.
- [ ] Listen only to response URL/body for `/api/author/publish_article/v0/`; do not log the request.
- [ ] On unknown result navigate to manager, read all pages, and decide by chapter number/title presence before retrying.
- [ ] Run focused tests and verify pass.

### Task 5: Background job, progress, and stop

**Files:**
- Create: `publisher/jobs.py`
- Modify: `publisher/ui.py`
- Test: `tests/test_jobs.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `PublishJob.start()`, `PublishJob.request_stop()`, `PublishJob.events`, and `BatchSummary`.
- UI consumes events through `root.after()` and never calls Playwright from Tk's main thread.

- [ ] Write failing tests for sequential chapter execution, stop-before-next, final single summary, and failure continuation rules.
- [ ] Implement the worker and event queue.
- [ ] Replace intermediate modal notifications with inline status; show one final summary only.
- [ ] Run `python -m unittest tests.test_jobs tests.test_ui -v` and verify pass.

### Task 6: Novel regression and real-page verification

**Files:**
- Modify: `README.md`
- Test: all tests

**Interfaces:**
- Consumes: current `data` and dedicated Edge profile.
- Produces: a verified next-chapter result and diagnostic log.

- [ ] Run `python -m unittest discover -v`.
- [ ] On the real next pending chapter, verify editor stabilization and final number/title/body without clicking publish.
- [ ] Submit exactly one authorized pending chapter, capture interface result, then confirm it appears in the manager.
- [ ] Run a two-chapter batch only after the single chapter passes, and verify no skipped number.
- [ ] Update README with recovery, stop, logs, and browser behavior.
