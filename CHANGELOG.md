# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Hydrated Today and auto-next from done-inclusive task data so retained completed children do not appear missing.
- Reconciled completion-triggered parent promotion for enabled and disabled auto-next, while preserving unrelated current tasks and bounding correction to one verified follow-up request.
- Made non-parent row clicks selection-only so tracking begins exclusively from the explicit **Start** button.
- Inherited a scheduled parent's start time when evaluating an unscheduled sibling for auto-next.

## [1.0.0] - 2026-08-25

### Added

- Current-task title, live countdown, signed overtime, project context, and scheduled time in the Omarchy bar and panel.
- Explicit Stop, Complete, fixed extension, and custom whole-minute extension controls.
- Confirmed-expiry desktop notifications with configurable urgency.
- Bundled and custom alert sounds, a 0–100% alert-volume setting, synthetic notification tests, and sound previews with bounded process cleanup.
- Searchable and collapsible Today hierarchy with parent tasks, direct subtasks, and explicit Start controls.
- Chronological Today parent blocks, with scheduled blocks ascending, unscheduled blocks last, authoritative child order, and orphaned children promoted to top-level rows.
- Explicit Complete controls on Today rows, including targeted noncurrent completion without auto-next and current-row completion with the configured auto-next behavior.
- Parent completion guards that remove **Complete** from every parent, reject completion when retained subtasks exist, and make parent <kbd>C</kbd> report guidance without mutation.
- Optional no-wrap auto-next after plugin-issued completion, with upstream-current detection and readback verification.
- Quick Add shorthand for estimates, spent time, projects, existing tags, and due dates.
- A compact borderless inline **Add & switch** checkbox that controls both Enter and the square **+**, with visible keyboard focus and partial-creation reporting.
- Full keyboard traversal, focused-row completion with <kbd>C</kbd>, Today search with <kbd>/</kbd>, scroll-position stability, and top navigation with <kbd>Home</kbd> or **Go top**.
- Completion result reporting and deterministic focus restoration after Today mutations.
- JSON backend commands for status, add, start, stop, current completion, targeted `complete-task`, extend, notification tests, sound previews, alerts, and app opening.
- IPC commands for panel visibility, status, task mutations, separate `complete(id)` and `completeTask(id)` semantics, notification tests, sound previews, and bounded action-result polling.
- An optional manual Hyprland global hotkey using the official shell toggle command. The plugin never edits user bindings.
- Serialized mutation processing with explicit succeeded, partial, conflict, failed, and unknown outcomes. Mutations have stage and application-state fields and no automatic retry.
- A queue of 16 pending mutations plus one running mutation, 30-second queued-request expiry, and retention of 64 results for 10 minutes.
- Multi-monitor singleton service with local countdown projection and independent status, notification-test, preview, and mutation lanes.
- Loopback-only REST access with URL validation, proxy and redirect blocking, private token-file checks, and a private advisory mutation lock.
- Subprocess argument boundaries, alert-title control-character cleanup, custom-sound path and size limits, and deterministic bundled-sound generation.
- Native, Flatpak, Snap, direct-token, token-file, REST URL alias, and app URL configuration.

### Changed

- Added the next scheduled task and local start time to the idle bar, panel hero, and idle guidance.
- Added one-shot scheduled-start alerts from fresh Today samples, whether idle or tracking, with startup protection and the existing alert settings.
- Suppressed scheduled-start alerts for the exact current task or its scheduled parent while preserving alerts for unrelated simultaneous crossings.
- Renamed the alert toggle to **Task alerts** and clarified that alert, sound, path, and urgency settings apply to countdown expiry and scheduled start.
- Moved Quick Add above Today. Enter and its inline square **+** both obey the persistent **Add & switch** checkbox, which defaults to off.
- Clarified the Quick Add hint as the syntax categories `+project, @schedule, #tag`. Schedule values remain `@today`, `@tomorrow`, `@YYYY-MM-DD`, or a weekday.
- Moved configuration into an in-plugin view opened by the popup's top-right gear. The plugin no longer depends on Omarchy Shell Settings.
- Restored notification tests and sound previews inside the plugin configuration view. They remain available through the backend CLI and IPC.
- An empty IPC `startAfter` follows `quickAddSwitch`, which defaults to off.
- Made Today title and context areas activate rows. Parent text toggles children, runnable leaf text starts the task, and explicit action hit areas remain separate.
- Made both completion commands reject every task with retained subtasks before mutation and recheck current-task identity immediately before current completion dispatch.
- Limited auto-next to scheduled tasks with finite start times inside a configurable ±window of 1–1440 minutes. The default is ±30 minutes; unscheduled and distant tasks are skipped.
- Made sound previews queue volume snapshots. Panel previews use displayed volume, IPC previews use configured volume, invalid explicit values are rejected, and alerts use configured volume.

[Unreleased]: https://github.com/patrickfanella/omarchy-superproductivity/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/patrickfanella/omarchy-superproductivity/releases/tag/v1.0.0
