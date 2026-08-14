# Novel Operation Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add immediate publish, server draft, content edit, and pending-schedule editing alongside the existing scheduled publishing flow.

**Architecture:** NovelOperation represents a one-run action without changing a book's saved scheduling policy. The workflow reads one remote snapshot per run, builds a numbered action list, and delegates external writes to explicit browser methods. Remote editor routes remain in browser memory only; they are never persisted in state or activity history.

**Tech Stack:** Python 3.14, standard-library dataclasses/enums/unittest, Tk/ttk, Playwright connected to the account-specific Edge profile.

## Verified Platform Facts

- The logged-in chapter manager exposes 新建章节 and returns a ready preflight result for the selected local work.
- A pending chapter opens an existing editor with input.serial-input, the title input, the ProseMirror editor, and 下一步.
- The official author change log states that scheduled chapters can change schedule or convert to immediate publication.
- Useful page DOM can be ready while background requests keep loading. Browser actions must wait for target controls, not networkidle or a history-navigation completion event.

## Global Constraints

- Never log, save, show, export, or commit remote editor URLs, platform IDs, credentials, manuscript bodies, chapter titles, or browser profile data.
- Read the remote chapter list once at operation start; do not rescan every chapter.
- Stop before the next chapter when RunControl is requested. Never force-close Edge during a write.
- CAPTCHA, verification, quota, risk review, agreement, unknown success state, missing editor route, and disallowed platform status stop with a recoverable result.
- Existing scheduled publishing remains the default and uses its already tested implementation unchanged.
- Draft mode requires a visible save-success signal. Reused draft identifiers are unsafe and must stop rather than silently count as separate drafts.

---

### Task 1: Explicit Operation Types and Source Selection

**Files:**
- Modify: publisher/models.py
- Modify: publisher/service.py
- Modify: tests/test_models.py
- Modify: tests/test_service.py

**Interfaces:**
- Produce NovelOperation with scheduled, immediate, draft, edit-content, and reschedule values.
- Produce PublishingService.selected_source_chapters(book_id) respecting the stored start/end chapter range.

- [ ] Write failing tests for enum values and selected source range.
- [ ] Run: python -m unittest tests.test_models tests.test_service -v. Expect failure because the operation enum and source selector are absent.
- [ ] Add the enum and delegate selected_source_chapters to the existing contiguous source scan.
- [ ] Run the focused tests again. Commit with: feat: define novel operation modes.

### Task 2: Remote Action Snapshot

**Files:**
- Modify: publisher/browser.py
- Modify: tests/test_browser.py

**Interfaces:**
- Produce ManagedChapter(chapter_number, status, editor_path) as an in-memory browser value.
- Produce EdgePublisherGateway.managed_chapters(book_name).

- [ ] Write a failing DOM-fixture test that extracts one pending row's chapter number, normalized pending status, and publish editor path.
- [ ] Run: python -m unittest tests.test_browser -v. Expect failure because no managed snapshot exists.
- [ ] Reuse the current table/pagination helpers to scan all pages. Parse only number, safe status, and the /publish/ path from each row. Reject duplicate numbers and rows without an editor route.
- [ ] Run browser tests and commit with: feat: snapshot remote chapter actions.

### Task 3: Explicit Browser Write Paths

**Files:**
- Modify: publisher/browser.py
- Modify: tests/test_browser.py

**Interfaces:**
- Produce submit_immediately, save_drafts, update_existing, and reschedule_existing batch methods.
- Reuse SubmissionResult, PublishBlockedError, content checks, picker dismissal, and response-code verification.

- [ ] Write failing tests: immediate settings leave the schedule switch false; existing-content edit does not write the serial input; draft fails without a visible save confirmation; reschedule changes only date/time controls.
- [ ] Run: python -m unittest tests.test_browser -v. Expect the four methods to be absent.
- [ ] Implement immediate publishing as new editor -> verified fields -> existing content checks -> schedule switch off -> AI declaration -> confirmed publish result.
- [ ] Implement server draft as new editor -> verified fields -> explicit save control -> bounded success confirmation. Track draft identifiers only inside the run and stop on reuse.
- [ ] Implement content edit through an existing editor path, rewrite title/body only, keep chapter number, preserve schedule settings, and require confirmed server result.
- [ ] Implement reschedule through a pending editor path, preserve title/body, set date/time in the existing publish settings, and require confirmed server result.
- [ ] Check the stop callback before every item and halt on first failure. Run browser tests and commit with: feat: add explicit novel gateway operations.

### Task 4: One-Snapshot Workflows

**Files:**
- Modify: publisher/workflows.py
- Modify: tests/test_workflows.py

**Interfaces:**
- Produce NovelOperationReport with operation, successful numbers, skipped numbers, failed chapter, error, cancellation, and remaining numbers.
- Produce run_novel_operation(service, gateway, book_id, operation, read_body, control=None, activity_log=None, on_progress=None).

- [ ] Write failing tests: immediate syncs one remote snapshot and skips published local chapters; content edit skips missing/non-editable remote chapters; reschedule chooses only remote pending chapters.
- [ ] Run: python -m unittest tests.test_workflows -v. Expect the dispatcher to be absent.
- [ ] Make scheduled delegate to the existing scheduled workflow. The four new operations launch/preflight once and take one managed snapshot. Immediate reconciles successful remote numbers only after browser confirmation. Draft, edit, and reschedule never mark a chapter as published.
- [ ] Record only safe operation/state/chapter/error-category activity values. Run workflow tests and commit with: feat: run explicit novel publishing operations.

### Task 5: Direct Operation Picker and Product Verification

**Files:**
- Modify: publisher/ui.py
- Modify: tests/test_ui.py
- Modify: README.md

**Interfaces:**
- Add a compact operation selector and a primary action label that follows the selected mode.
- Reuse the current range and schedule policy controls without a second confirmation dialog.

- [ ] Write failing UI tests that changing to draft changes the primary action label and that content edit creates the shared RunControl.
- [ ] Run: python -m unittest tests.test_ui -v. Expect the picker to be absent.
- [ ] Keep scheduled as default. Share the chapter range with immediate/draft/content edit and share schedule inputs with scheduled/reschedule. Completion shows count-only results; activity log keeps privacy redaction.
- [ ] Add concise README text for platform edit permissions and the draft-reuse stop condition.
- [ ] Run: python -m unittest discover -s tests -v; git diff --check; powershell -ExecutionPolicy Bypass -File .\build.ps1. Commit with: feat: expose novel operation modes.

