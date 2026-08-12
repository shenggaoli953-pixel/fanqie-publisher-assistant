# Sequential Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent skipped chapters by always retrying the earliest unsubmitted chapter and by refusing to plan across a local chapter-number gap.

**Architecture:** The service remains the source of scheduling decisions. It selects only the unsubmitted part of the earliest scheduled day, refreshes a contiguous local tail, and uses the full paginated Fanqie schedule to account for already reserved daily capacity.

**Tech Stack:** Python 3.14, `unittest`, Playwright sync API.

## Global Constraints

- Never modify existing `data` state or Fanqie records as part of this code change.
- A partially submitted day must be retried before every later scheduled day.
- Publishing must stop when a missing local chapter would need to be inserted before an already-submitted later chapter.
- Do not wait for the remote `待发布` status after a normal publish action.

---

### Task 1: Select Remaining Chapters Before Later Days

**Files:**
- Modify: `tests/test_service.py`
- Modify: `publisher/service.py`

**Interfaces:**
- Produces: `PublishingService.next_pending_day(book_id: str) -> ScheduledDay`

- [x] **Step 1: Write the failing test**

```python
def test_next_pending_day_retries_only_the_unsubmitted_chapters_of_a_partial_day(self):
    self.service.update_policy("robot", PublishMode.CHAPTERS, 2, time(0, 0), date(2026, 7, 27), 1, None)
    token = self.service.confirm_batch("robot", [1, 2])
    self.service.record_submission("robot", 1, True, token)
    self.service.record_submission("robot", 2, False, token, "network error")

    day = self.service.next_pending_day("robot")

    self.assertEqual([chapter.number for chapter in day.chapters], [2])
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_service.ServiceTests.test_next_pending_day_retries_only_the_unsubmitted_chapters_of_a_partial_day -v`

Expected: the current implementation returns the later pending day.

- [x] **Step 3: Write minimal implementation**

```python
for day in self.get_schedule(book_id):
    remaining = tuple(chapter for chapter in day.chapters if chapter.number not in submitted)
    if remaining and not day.over_limit:
        return replace(day, chapters=remaining, status="pending")
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_service.ServiceTests.test_next_pending_day_retries_only_the_unsubmitted_chapters_of_a_partial_day -v`

Expected: PASS.

### Task 2: Stop Scheduling at Local Gaps and Extend When the Gap Is Filled

**Files:**
- Modify: `tests/test_chapters.py`
- Modify: `tests/test_service.py`
- Modify: `publisher/chapters.py`
- Modify: `publisher/service.py`

**Interfaces:**
- Produces: `contiguous_chapters(chapters: list[Chapter], start_number: int, end_number: int | None) -> list[Chapter]`
- Produces: `PublishingService.next_pending_day(book_id: str) -> ScheduledDay`

- [x] **Step 1: Write failing tests**

```python
self.assertEqual(
    [chapter.number for chapter in contiguous_chapters([chapter(1), chapter(3)], 1, None)],
    [1],
)
```

```python
# Create chapters 1 and 3, add the book, then create chapter 2.
# next_pending_day must extend the plan to return chapter 2 before chapter 3.
self.assertEqual([chapter.number for chapter in day.chapters], [2])
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_chapters tests.test_service -v`

Expected: missing helper and an out-of-order schedule selection failure.

- [x] **Step 3: Write minimal implementation**

```python
def contiguous_chapters(chapters, start_number, end_number):
    by_number = {chapter.number: chapter for chapter in chapters}
    result = []
    number = start_number
    while end_number is None or number <= end_number:
        chapter = by_number.get(number)
        if chapter is None:
            return result
        result.append(chapter)
        number += 1
    return result
```

Use it for initial schedules and before selecting a new day. Append newly contiguous chapters only after the final existing day. If an absent scheduled number has already been followed by a submitted chapter, raise a clear error instead of publishing out of order.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_chapters tests.test_service -v`

Expected: PASS.

### Task 3: Verify and Package

**Files:**
- Modify: `README.md`
- Run: `build.ps1`

- [x] **Step 1: Update behavior notes**

Document that every publish operation first reads the chapter manager, retries the first missing scheduled chapter, and stops instead of crossing a detected gap.

- [x] **Step 2: Run the full suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass.

- [x] **Step 3: Build the executable**

Run: `./build.ps1`

Expected: PyInstaller exits with code 0 and updates `dist-notice-submit/FanqiePublisher-NoticeSubmit/FanqiePublisher-NoticeSubmit.exe`.
