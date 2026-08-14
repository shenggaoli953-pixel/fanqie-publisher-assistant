# Commercial Workflow Completion Design

## Goal

Turn the current reliable publishing core into a clearer sellable Windows workflow: isolated local accounts, explicit novel operations, controllable runs, and buyer-facing guidance. The existing scheduled novel and short-story paths remain the compatibility baseline.

## Scope

This release has four independent modules, implemented and tested in order.

1. Local account profiles.
2. Explicit novel operation modes.
3. Cooperative stop control and durable activity log.
4. First-run guidance, help, version, and buyer support material.

## Account Profiles

`data/accounts.json` stores local profile names and an active profile identifier. A profile owns its own Edge user-data directory at `data/accounts/<profile-id>/edge-profile` and an independent publishing repository at `data/accounts/<profile-id>/workspace`.

The UI presents an account selector with add, rename, and switch actions. Switching is blocked while a task is running. Existing single-account users migrate lazily into one default profile that continues using the current `data/fanqie-edge-profile` and existing repository files; no login state is copied, moved, displayed, or committed.

## Novel Operation Modes

The novel tab gains an explicit mode selector:

- **定时发布**: current safe schedule behaviour.
- **立即发布**: uses the selected chapter range but requests the platform's immediate-publication setting.
- **存草稿**: uploads selected chapters without scheduling publication.
- **修改正文**: matches an existing chapter number and replaces title/body only for selected chapters.
- **修改排期**: changes only platform chapters in a confirmed pending state.

Every mode begins from a read-only remote snapshot and a local range preview. Existing direct publish stays available as the default operation and does not acquire an extra confirmation dialog. Platform CAPTCHA, login, quota, risk review, agreement, and other manual requirements always stop the run.

## Task Control and Logs

The task controller receives a cancellation token checked before each chapter. Pressing “停止任务” prevents the next chapter from starting, lets the current browser action finish or report its actual outcome, and then records the remaining chapters as unprocessed. It never forces browser closure during a write.

Each profile maintains a bounded local activity log with timestamp, operation, chapter number, safe status, and safe error category. It stores neither body text, chapter title, file path, URL, account cookies, nor browser profile data. The UI can display current-run progress and export that safe log together with the existing diagnostic report.

## Onboarding and Support

The first opening of a new profile shows a dismissible, non-blocking guide: choose account, login in Edge, add/select a work, preview, then run. A persistent help button can reopen the guide and shows the installed version. Release notes and support instructions are local text; no background network request is introduced.

## Safety and Compatibility

- Do not bypass CAPTCHA, platform checks, quotas, content review, or agreement prompts.
- Do not automatically retry a blocked submission.
- Do not expose or transfer login state between profiles.
- Existing schedules, short stories, and single-account `data/` files must remain readable.
- A stopped task is a recoverable stop, never a successful submission.

## Verification

- Test account serialization, legacy-data migration decisions, and gateway profile selection.
- Test each operation mode maps only to its permitted browser action and selected chapter range.
- Test cancellation before the next chapter, safe log redaction, and task recovery state.
- Test UI mode/account/task controls without invoking a live browser.
- Run the full regression suite and Windows package build before release.
