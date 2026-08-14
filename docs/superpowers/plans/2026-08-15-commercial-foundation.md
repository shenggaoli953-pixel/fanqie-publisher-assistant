# Commercial Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated local accounts, cooperative task stopping, privacy-safe activity history, and first-run help without changing the existing successful publishing protocol.

**Architecture:** `AccountRegistry` maps a local account to a private workspace and Edge profile. It retains existing root `data/` files as a legacy default account. Workflows receive a small cancellation token and optional activity writer so they stop before the next chapter instead of interrupting an active browser write.

**Tech Stack:** Python 3.14, standard-library JSON/threading/unittest, Tk/ttk, Playwright gateway.

## Global Constraints

- Never copy, display, serialize, or commit Edge login state, cookies, platform account names, or manuscript text.
- Existing `data/books.json`, `data/short_stories.json`, `data/state/`, and `data/fanqie-edge-profile/` stay usable as the default account.
- A stop request must not interrupt a current browser write or allow a later chapter to start.
- CAPTCHA, verification, quotas, content review, and agreements remain stopping conditions.
- Preserve direct scheduled publishing with no extra confirmation.

---

### Task 1: Account Registry and Legacy Paths

**Files:**
- Create: `publisher/accounts.py`
- Create: `tests/test_accounts.py`

**Interfaces:**
- Produces `AccountProfile(profile_id: str, display_name: str, guide_seen: bool = False)`.
- Produces `AccountRegistry(data_dir: Path)` with `profiles()`, `active()`, `add()`, `rename()`, `set_active()`, `mark_guide_seen()`, `workspace_dir()`, and `edge_profile_dir()`.

- [ ] **Step 1: Write failing account tests**

```python
def test_registry_exposes_legacy_paths_without_moving_data(self):
    registry = AccountRegistry(self.root / "data")
    account = registry.active()
    self.assertEqual(account.profile_id, "legacy")
    self.assertEqual(registry.workspace_dir(account.profile_id), self.root / "data")
    self.assertEqual(registry.edge_profile_dir(account.profile_id), self.root / "data" / "fanqie-edge-profile")

def test_new_profile_has_isolated_workspace_and_edge_profile(self):
    registry = AccountRegistry(self.root / "data")
    account = registry.add("作家 B")
    self.assertEqual(registry.workspace_dir(account.profile_id), self.root / "data" / "accounts" / account.profile_id / "workspace")
    self.assertEqual(registry.edge_profile_dir(account.profile_id), self.root / "data" / "accounts" / account.profile_id / "edge-profile")
```

- [ ] **Step 2: Run the new tests**

Run: `python -m unittest tests.test_accounts -v`

Expected: FAIL because `publisher.accounts` is absent.

- [ ] **Step 3: Implement a registry with atomic JSON writes**

```python
@dataclass(frozen=True)
class AccountProfile:
    profile_id: str
    display_name: str
    guide_seen: bool = False

class AccountRegistry:
    LEGACY_ID = "legacy"

    def workspace_dir(self, profile_id: str) -> Path:
        return self.data_dir if profile_id == self.LEGACY_ID else self.data_dir / "accounts" / profile_id / "workspace"

    def edge_profile_dir(self, profile_id: str) -> Path:
        return self.data_dir / "fanqie-edge-profile" if profile_id == self.LEGACY_ID else self.data_dir / "accounts" / profile_id / "edge-profile"
```

Reject blank display names and unknown IDs. Persist only generated local IDs, local display names, the active ID, and guide state in `accounts.json`.

- [ ] **Step 4: Run account tests and commit**

Run: `python -m unittest tests.test_accounts -v`

```bash
git add publisher/accounts.py tests/test_accounts.py
git commit -m "feat: add isolated local publishing accounts"
```

### Task 2: Profile-Scoped Application Context

**Files:**
- Create: `publisher/application.py`
- Modify: `main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Produces `ApplicationContext(data_dir: Path)` with `accounts`, `active_profile()`, `service()`, `gateway_factory()`, and `switch(profile_id)`.

- [ ] **Step 1: Write the failing profile switch test**

```python
def test_context_switches_service_and_gateway_to_selected_profile(self):
    context = ApplicationContext(self.root)
    account = context.accounts.add("作家 B")
    context.switch(account.profile_id)
    self.assertEqual(context.service()._repository._data_dir, context.accounts.workspace_dir(account.profile_id))
    self.assertEqual(context.gateway_factory()()._profile_dir, context.accounts.edge_profile_dir(account.profile_id))
```

- [ ] **Step 2: Run the test**

Run: `python -m unittest tests.test_main.MainTests.test_context_switches_service_and_gateway_to_selected_profile -v`

Expected: FAIL because `ApplicationContext` is absent.

- [ ] **Step 3: Build services and gateway factories from the active account**

```python
class ApplicationContext:
    def service(self) -> PublishingService:
        return PublishingService(JsonRepository(self.accounts.workspace_dir(self.active_profile().profile_id)))

    def gateway_factory(self) -> Callable[[], EdgePublisherGateway]:
        path = self.accounts.edge_profile_dir(self.active_profile().profile_id)
        return lambda: EdgePublisherGateway(path)
```

Pass one `ApplicationContext` into the application entry point. Keep `application_data_dir` callable and preserve current package data resolution.

- [ ] **Step 4: Run main tests and commit**

Run: `python -m unittest tests.test_main -v`

```bash
git add publisher/application.py main.py tests/test_main.py
git commit -m "feat: scope services to active publishing account"
```

### Task 3: Cooperative Stop and Safe Activity History

**Files:**
- Create: `publisher/activity.py`
- Create: `tests/test_activity.py`
- Modify: `publisher/browser.py`
- Modify: `publisher/workflows.py`
- Modify: `tests/test_browser.py`
- Modify: `tests/test_workflows.py`

**Interfaces:**
- Produces `RunControl.request_stop()` and `RunControl.stop_requested()`.
- Produces `ActivityLog(workspace_dir: Path)` with `append(operation, state, chapter_number=None, error=None)` and `recent()`.
- Extends gateway `submit_batch(..., should_stop: Callable[[], bool] | None = None)`.
- Extends `PublishRunReport` with `cancelled: bool` and `remaining_numbers: tuple[int, ...]`.

- [ ] **Step 1: Write failing cancellation and privacy tests**

```python
def test_publish_stops_before_next_chapter_when_requested(self):
    control = RunControl()
    gateway = _Gateway(on_submit=lambda number: control.request_stop() if number == 1 else None)
    report = publish_all_scheduled(self.service, gateway, "book", read_body=body, control=control)
    self.assertTrue(report.cancelled)
    self.assertEqual(report.submitted_numbers, (1,))
    self.assertEqual(report.remaining_numbers, (2, 3))

def test_activity_log_omits_private_error_text(self):
    log = ActivityLog(self.root)
    log.append("scheduled", "failed", chapter_number=8, error="C:/private https://x 正文 标题")
    payload = (self.root / "activity.json").read_text(encoding="utf-8")
    for value in ("C:/private", "https://", "正文", "标题"):
        self.assertNotIn(value, payload)
```

- [ ] **Step 2: Run the new tests**

Run: `python -m unittest tests.test_activity tests.test_workflows.WorkflowTests.test_publish_stops_before_the_next_chapter_when_requested -v`

Expected: FAIL because task-control interfaces are absent.

- [ ] **Step 3: Check the stop token before each draft and write a bounded safe log**

```python
for draft in drafts:
    if should_stop is not None and should_stop():
        results.append(SubmissionResult(draft.chapter_number, False, cancelled=True))
        break
    self._submit_one(draft)
```

Workflows convert the cancellation sentinel into a stopped report, write `scheduled`, `submitted`, `failed`, or `stopped` records, and preserve remaining chapter numbers. The log retains at most 500 JSON records and writes atomically.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m unittest tests.test_activity tests.test_browser tests.test_workflows -v`

```bash
git add publisher/activity.py publisher/browser.py publisher/workflows.py tests/test_activity.py tests/test_browser.py tests/test_workflows.py
git commit -m "feat: add cooperative task stop and activity history"
```

### Task 4: Workbench Account, Stop, Log, and Help Controls

**Files:**
- Modify: `publisher/ui.py`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes `ApplicationContext`, `RunControl`, and `ActivityLog`.
- Produces compact account switch/add/rename controls, `停止任务`, `活动记录`, and `帮助` actions.

- [ ] **Step 1: Write the failing UI behavior tests**

```python
def test_stop_task_requests_a_safe_stop_without_closing_gateway(self):
    app = PublisherApp(root, context)
    app._task_control = RunControl()
    app._task_running = True
    app._request_task_stop()
    self.assertTrue(app._task_control.stop_requested())
    self.assertEqual(app._task_status_var.get(), "将在当前章节结束后停止")

def test_switch_account_refreshes_when_idle(self):
    app = PublisherApp(root, context)
    app._switch_account(second.profile_id)
    self.assertEqual(context.active_profile().profile_id, second.profile_id)
    self.assertIsNone(app._selected_book_id)
```

- [ ] **Step 2: Run the new UI tests**

Run: `python -m unittest tests.test_ui.UiFormattingTests.test_stop_task_requests_a_safe_stop_without_closing_gateway tests.test_ui.UiFormattingTests.test_switch_account_refreshes_when_idle -v`

Expected: FAIL because UI methods are absent.

- [ ] **Step 3: Add non-blocking controls and local help**

```python
def _request_task_stop(self) -> None:
    if self._task_control is not None:
        self._task_control.request_stop()
        self._task_status_var.set("将在当前章节结束后停止")

def _switch_account(self, profile_id: str) -> None:
    if self._task_running:
        messagebox.showinfo("任务正在进行", "请先停止当前任务。", parent=self._root)
        return
    self._context.switch(profile_id)
    self._reload_context()
```

Show a dismissible guide only for accounts where `guide_seen` is false. Help shows local usage steps, installed version, and safe feedback guidance; it starts no browser task and performs no network request.

- [ ] **Step 4: Run UI tests and commit**

Run: `python -m unittest tests.test_ui -v`

```bash
git add publisher/ui.py tests/test_ui.py
git commit -m "feat: add account and task controls to workbench"
```

### Task 5: Documentation and Product Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document account isolation and task control**

State that each local account requires its own Edge login; switches do not copy login state; stopping waits for the active chapter; activity exports omit titles, bodies, paths, URLs, and login data.

- [ ] **Step 2: Run full checks**

Run: `python -m unittest discover -s tests -v`

Run: `git diff --check`

Expected: all tests pass and no whitespace errors.

- [ ] **Step 3: Build and commit**

Run: `powershell -ExecutionPolicy Bypass -File .\\build.ps1`

Expected: exit code 0 and `release\\FanqiePublisher\\FanqiePublisher.exe` exists.

```bash
git add README.md
git commit -m "docs: explain account and task workflow"
```

The next implementation plan begins with a read-only inspection of the current Fanqie author pages before adding immediate publish, draft, content-edit, and reschedule. Those mode selectors are not shown before their browser actions have direct verification.
