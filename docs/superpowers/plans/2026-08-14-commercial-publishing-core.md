# Commercial Publishing Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-time daily schedules, a read-only pre-publish overview, explicit failure recovery, and privacy-safe local diagnostics.

**Architecture:** Keep the browser gateway unchanged. Extend the persisted scheduling model compatibly, make the planner emit timestamped single-chapter schedule entries, and expose service-level preview and recovery data to the Tk workbench. Diagnostics are a separate pure module so no account, manuscript, or browser data can enter an export by accident.

**Tech Stack:** Python 3.14, standard-library `unittest`, Tk/ttk, JSON repository, Playwright gateway.

## Global Constraints

- Existing `publish_time` payloads remain readable and retain their single-time behavior.
- Never bypass CAPTCHA, platform quota, risk detection, content review, or verification.
- Diagnostic export must omit body text, titles, source paths, URLs, browser profiles, cookies, and account names.
- No automatic retry after a real platform failure; recovery is user-initiated.
- Run `python -m unittest discover -s tests -v` and `powershell -ExecutionPolicy Bypass -File .\\build.ps1` before release.

---

### Task 1: Compatible Multi-Time Configuration

**Files:**
- Modify: `publisher/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces: `BookConfig.publish_times: tuple[time, ...]` and `BookConfig.effective_publish_times: tuple[time, ...]`.
- Produces: `BookState.last_failed_chapter: int | None`.

- [ ] **Step 1: Write the failing model tests**

```python
def test_book_config_round_trip_preserves_multiple_publish_times(self):
    config = BookConfig(..., publish_time=time(8), publish_times=(time(8), time(12)))
    self.assertEqual(BookConfig.from_dict(config.to_dict()).effective_publish_times, (time(8), time(12)))

def test_legacy_book_config_uses_its_original_single_publish_time(self):
    config = BookConfig.from_dict({..., "publish_time": "08:00"})
    self.assertEqual(config.effective_publish_times, (time(8),))

def test_book_config_rejects_duplicate_or_descending_publish_times(self):
    with self.assertRaisesRegex(ValueError, "publish_times"):
        BookConfig(..., publish_times=(time(12), time(8)))
```

- [ ] **Step 2: Run model tests and verify they fail because the new field/property is missing**

Run: `python -m unittest tests.test_models -v`

- [ ] **Step 3: Add the compatible fields and serializer changes**

```python
publish_times: tuple[time, ...] = ()

@property
def effective_publish_times(self) -> tuple[time, ...]:
    return self.publish_times or (self.publish_time,)
```

Validate unique ascending values in `__post_init__`, serialize the tuple as `publish_times`, and leave legacy payload handling on `publish_time`.

- [ ] **Step 4: Add `last_failed_chapter` to `BookState` serialization with a `None` default for old state files**

- [ ] **Step 5: Run model tests and commit**

Run: `python -m unittest tests.test_models -v`

Commit: `git commit -m "feat: persist multi-time schedules and failure state"`

### Task 2: Multi-Time Planner

**Files:**
- Modify: `publisher/planner.py`
- Modify: `tests/test_planner.py`

**Interfaces:**
- Consumes: `BookConfig.effective_publish_times`.
- Produces: `build_schedule(...) -> list[ScheduledDay]` with chronological, one-chapter entries.

- [ ] **Step 1: Write failing scheduler tests**

```python
def test_chapter_mode_distributes_a_day_across_each_selected_time(self):
    config = config_for(..., publish_times=(time(8), time(12), time(20)))
    schedule = build_schedule([chapter(1, 1), ..., chapter(5, 1)], config, date(2026, 8, 15))
    self.assertEqual([day.publish_at.strftime("%H:%M") for day in schedule], ["08:00", "08:01", "12:00", "12:01", "20:00"])

def test_word_limit_still_starts_the_next_day_after_time_distribution(self):
    ...
```

- [ ] **Step 2: Run planner tests and verify the new time distribution assertion fails**

Run: `python -m unittest tests.test_planner -v`

- [ ] **Step 3: Refactor `build_schedule` into daily grouping plus slot expansion**

Keep existing word/chapter limit behavior. For each daily group, calculate an ordered slot index with `position * len(times) // len(chapters)` and add a minute offset within that slot. Emit one `ScheduledDay` per chapter.

- [ ] **Step 4: Run planner tests and commit**

Run: `python -m unittest tests.test_planner -v`

Commit: `git commit -m "feat: distribute daily chapters across publish times"`

### Task 3: Preview, Remote Fit, and Recovery State

**Files:**
- Modify: `publisher/service.py`
- Modify: `publisher/workflows.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Produces: `PublishingService.schedule_preview(book_id) -> list[ScheduledDay]`.
- Produces: `PublishingService.failure_status(book_id) -> tuple[int | None, str | None]`.

- [ ] **Step 1: Write failing service/workflow tests**

```python
def test_failure_state_records_the_chapter_and_clears_after_its_successful_retry(self):
    token = self.service.confirm_batch("robot", [1])
    self.service.record_submission("robot", 1, False, token, "network error")
    self.assertEqual(self.service.failure_status("robot"), (1, "network error"))

def test_remote_fit_keeps_the_pending_slot_time(self):
    fitted = PublishingService._fit_remote_daily_limit(book, day_at_noon, remote)
    self.assertEqual(fitted.publish_at.time(), time(12))
```

- [ ] **Step 2: Run focused tests and verify missing methods/incorrect slot time fail**

Run: `python -m unittest tests.test_service tests.test_workflows -v`

- [ ] **Step 3: Implement service methods and state updates**

Store failed chapter/message in `record_submission`, clear it only after a matching success or confirmed remote reconciliation, and have the remote fitter use `day.publish_at.time()` when it changes only the date.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m unittest tests.test_service tests.test_workflows -v`

Commit: `git commit -m "feat: expose recoverable publishing state"`

### Task 4: Safe Diagnostic Export

**Files:**
- Create: `publisher/diagnostics.py`
- Create: `tests/test_diagnostics.py`

**Interfaces:**
- Produces: `write_diagnostic_report(path: Path, *, version: str, state: BookState, schedule: list[ScheduledDay]) -> Path`.

- [ ] **Step 1: Write the failing privacy test**

```python
def test_diagnostic_report_omits_story_titles_bodies_paths_urls_and_account_text(self):
    report = write_diagnostic_report(...)
    content = report.read_text(encoding="utf-8")
    for secret_like_value in ("私密标题", "正文内容", "C:/secret", "https://", "账号A"):
        self.assertNotIn(secret_like_value, content)
```

- [ ] **Step 2: Run diagnostic tests and verify the module is missing**

Run: `python -m unittest tests.test_diagnostics -v`

- [ ] **Step 3: Implement JSON-only diagnostics**

Use a salted-free SHA-256 digest prefix of `book_id`, chapter numbers, timestamps, statuses, an error message with paths/URLs redacted, and an ISO generated time. Do not read source files or repository browser data.

- [ ] **Step 4: Run diagnostic tests and commit**

Run: `python -m unittest tests.test_diagnostics -v`

Commit: `git commit -m "feat: export privacy-safe diagnostics"`

### Task 5: Workbench Controls

**Files:**
- Modify: `publisher/ui.py`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: comma-separated publish-time input, `schedule_preview`, `failure_status`, and diagnostic exporter.
- Produces: read-only preview modal; `从失败处继续` and `导出诊断` actions.

- [ ] **Step 1: Write failing UI tests**

```python
def test_parse_publish_times_normalizes_full_width_separators_and_rejects_duplicates(self):
    self.assertEqual(parse_publish_times("8:00，12:00"), (time(8), time(12)))

def test_app_shows_a_failure_recovery_action_only_when_a_failure_exists(self):
    ...
```

- [ ] **Step 2: Run UI tests and verify the parser/control is missing**

Run: `python -m unittest tests.test_ui -v`

- [ ] **Step 3: Implement the UI additions without changing gateway calls**

Replace the single-time label with `发布时间（可多个）`; display a preview button beside the publish action; surface a compact failure strip only when `failure_status` is non-empty; export diagnostics through a save-file chooser; and keep the current direct publish behavior after the user presses the main action.

- [ ] **Step 4: Run UI tests and commit**

Run: `python -m unittest tests.test_ui -v`

Commit: `git commit -m "feat: add preview and recovery workbench controls"`

### Task 6: Product Verification and Release

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document multiple times, preview, recovery, and diagnostic privacy boundary**

- [ ] **Step 2: Run the complete suite and whitespace check**

Run: `python -m unittest discover -s tests -v`

Run: `git diff --check`

- [ ] **Step 3: Build the Windows package**

Run: `powershell -ExecutionPolicy Bypass -File .\\build.ps1`

- [ ] **Step 4: Perform a read-only review of the changed files, commit documentation, and publish a release**

Commit: `git commit -m "docs: describe reliable publishing workflow"`
