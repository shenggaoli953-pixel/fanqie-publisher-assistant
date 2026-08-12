# Short Story Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate local-to-Fanqie short-story workflow without weakening the novel publisher.

**Architecture:** Parse short stories into their own model and repository, then automate the dedicated short-story manager/editor with a separate browser adapter sharing only the Edge session and diagnostics.

**Tech Stack:** Python 3.14, dataclasses, JSON, Playwright, Tkinter, unittest.

## Global Constraints

- Short-story publishing must not mutate novel books, schedules, or chapter state.
- Accept `.txt` and `.md`; preserve user source files unchanged.
- A cover, primary category, AI declaration, and explicit short-story publication consent are required before submission.
- The software must not silently accept a newly presented font/image legal agreement.
- No test story may remain published; temporary drafts created during inspection must be removed.

---

### Task 1: Short-story model and parser

**Files:**
- Create: `publisher/short_story.py`
- Modify: `publisher/repository.py`
- Test: `tests/test_short_story.py`

**Interfaces:**
- Produces: `ShortStoryConfig`, `ShortStoryDraft`, `scan_short_story_source(path)`, and repository load/save methods.
- `scan_short_story_source` accepts one file or recursively ordered files and strips a matching first heading only from the upload copy.

- [ ] Write failing tests for TXT/MD, folder merge, encodings, heading cleanup, empty body, missing cover, and old-data defaults.
- [ ] Implement the parser and atomic `short_stories.json` storage.
- [ ] Run `python -m unittest tests.test_short_story -v` and verify pass.

### Task 2: Short-story browser adapter

**Files:**
- Create: `publisher/short_story_browser.py`
- Modify: `publisher/browser.py`
- Test: `tests/test_short_story_browser.py`

**Interfaces:**
- Produces: `ShortStoryPublisher.preflight(config)` and `submit(config, draft)`.
- Reuses the controlled Edge page and `ActivityLog`; owns `/short-manage` and `/publish-short` selectors.

- [ ] Write failing DOM-fake tests for empty short-story manager, delayed editor reset, local cover input, category menu, AI radio, publication checkbox, and missing legal-agreement readiness.
- [ ] Implement editor stability using the same body-first principle as novels.
- [ ] Upload the configured local cover only after platform agreement readiness is detected.
- [ ] Submit only when all required settings can be read back from the page.
- [ ] Verify success by response or the short-story manager entry.
- [ ] Run short-story browser tests and verify pass.

### Task 3: UI and safe real-page check

**Files:**
- Modify: `publisher/ui.py`
- Modify: `publisher/jobs.py`
- Test: `tests/test_ui.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Produces: work type selector, short-story form, prepare-browser action, publish action, and inline readiness report.

- [ ] Write failing tests that selecting short story hides novel schedule controls and validates cover/category/consent.
- [ ] Implement add/edit short-story form and background submission job.
- [ ] Verify on the real blank short-story account that empty manager is accepted and editor title/body are stable.
- [ ] Stop before external publication when no genuine user short-story source and cover are configured; report the exact remaining preparation state.
