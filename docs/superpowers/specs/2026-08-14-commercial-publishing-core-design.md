# Commercial Publishing Core Design

## Goal

Make the release workflow predictable enough for external users: they can inspect every scheduled chapter before submission, use several publish times per day, and resume safely after a real failure without exposing manuscript or account data.

## Scope

This first productization slice delivers three connected capabilities:

1. Multiple daily publish times for novel schedules.
2. A read-only pre-publish overview that lists each chapter, title, character count, planned time, and current status.
3. A failure-recovery surface and an exportable diagnostic summary containing no manuscript text, source paths, browser profile data, cookies, or account identifiers.

The next slice will add onboarding, release-update checks, and buyer-facing documentation. It is intentionally separate so a packaging change cannot destabilize the publishing path.

## Decisions

### Scheduling

`BookConfig` retains `publish_time` for backwards compatibility and gains an optional ordered `publish_times` tuple. Existing saved books with no tuple continue to use their single time. New settings accept one or more comma-separated `HH:MM` values; invalid, duplicate, or descending times are rejected before a schedule is rebuilt.

The planner first applies the existing daily word/episode limit. It then assigns the day’s chapters to the selected times in source order. When several chapters belong to one time slot, later chapters use one-minute offsets so every planned timestamp is strictly increasing. The planner emits one `ScheduledDay` per chapter; this preserves the existing gateway contract because each draft already carries its own `publish_at` value.

The remote daily-limit fitter retains the slot time from the pending schedule instead of replacing it with the old single `publish_time` value.

### Preview and Recovery

The service exposes a flattened schedule view containing chapter number, title, character count, publish time, and status. The UI opens it as a read-only modal before a new submission run; it does not include the chapter body and does not add another confirmation prompt after the user starts publishing.

`BookState` records `last_failed_chapter` beside the existing failure message. A successful retry of that chapter clears the failure marker. The recovery action invokes the existing ordered publisher from the failed chapter onward; it never skips a failed chapter or submits a later chapter first.

### Diagnostics

Diagnostics are generated locally as a small JSON report. It includes app version, generated time, anonymized book identifier, schedule dates/times, chapter numbers, statuses, and error category/message after URLs and filesystem paths are redacted. It contains no chapter body, title, source path, cookie, browser profile, account name, or remote URL. The UI lets the user choose where to save the report only after they explicitly request export.

## Boundaries

- Do not bypass CAPTCHA, verification, risk checks, platform quotas, or review.
- Do not retry a blocked/erroring platform submission automatically; a user starts a recovery run after reading the recorded failure.
- Do not change short-story submission behavior in this slice.
- Existing single-time books and repository payloads remain readable without migration.

## Files and Responsibilities

- `publisher/models.py`: compatible config/state fields and preview record types.
- `publisher/planner.py`: daily-limit grouping and multi-time expansion.
- `publisher/service.py`: policy parsing boundary, flattened preview, failed-run state.
- `publisher/workflows.py`: report the stopped chapter without changing browser behavior.
- `publisher/diagnostics.py`: safe local diagnostic serialization and redaction.
- `publisher/ui.py`: multi-time field, preview modal, recovery and diagnostic actions.
- `tests/test_models.py`, `tests/test_planner.py`, `tests/test_service.py`, `tests/test_workflows.py`, `tests/test_diagnostics.py`, `tests/test_ui.py`: regression and behavior coverage.

## Verification

- Test compatibility with legacy one-time configuration.
- Test time parsing, duplicate rejection, daily-limit preservation, and strictly increasing planned timestamps.
- Test failure records survive repository reload and recovery publishes the failed chapter before any later one.
- Test diagnostic output excludes body-like input, source paths, URLs, account names, and browser data.
- Run the full regression suite and package build before release.
