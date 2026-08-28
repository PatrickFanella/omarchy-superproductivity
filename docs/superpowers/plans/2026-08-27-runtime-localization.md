# Runtime Localization Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. Recommended path:
> dispatch a fresh subagent per task, review each result with `review-quality`,
> then continue. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Localize plugin-owned UI, accessibility text, notifications, and user-facing errors into English, German, Spanish, French, Italian, Brazilian Portuguese, Dutch, Polish, Croatian, and Simplified Chinese, following the system locale with per-key English fallback.

**Architecture:** Add one build-free `I18n.js` module containing the canonical English catalog, locale overlays, locale normalization, placeholder interpolation, and semantic protocol-label mappings. `Service.qml` owns the effective locale and exposes translation to `BarWidget.qml` and `Panel.qml`; Python keeps existing English CLI/IPC fields while adding optional semantic message metadata and backward-compatible localized notification arguments.

**Tech Stack:** QML/Qt 6, QML JavaScript, Node.js test runner, Python 3.10+ unittest.

---

## File structure

- Create `I18n.js`: catalogs, locale resolution, fallback, interpolation, warning/state/stage/message mappings.
- Create `tests/i18n.test.js`: catalog parity, locale aliases, fallback, placeholders, semantic mappings.
- Modify `Service.qml`: effective locale, translated service errors and notification payloads, translated warning display.
- Modify `BarWidget.qml`: translated labels, tooltips, and accessibility names.
- Modify `Panel.qml`: translated visible strings, feedback, state labels, and accessibility text; content-safe controls.
- Modify `ActionModel.js`: retain additive `messageKey` and `messageArgs` metadata unchanged.
- Modify `backend/superproductivity.py`: additive semantic mutation metadata and localized notification title/body options while retaining English contracts and defaults.
- Modify `tests/action-model.test.js`, `tests/test_backend.py`, and `tests/test_phase1_backend.py`: compatibility and localization-boundary coverage.
- Modify `RELEASE_FILES.txt`: package new runtime/test/plan files.

### Task 1: Translation runtime and catalog tests

- [ ] Write `tests/i18n.test.js` first. Assert `resolveLocale()` maps `de_DE.UTF-8→de`, `pt_BR→pt-BR`, `zh_CN→zh-CN`, `hr_HR→hr`, `C→en`, and unsupported locales to `en`. Assert missing keys fall back to English, named placeholders interpolate without changing untranslated values, every locale uses only English keys, and placeholders match English.
- [ ] Run `node --test tests/i18n.test.js`; expect failure because `I18n.js` does not exist.
- [ ] Create `I18n.js` as a plain QML-compatible JavaScript module with optional `module.exports`. Define `SUPPORTED_LOCALES`, `resolveLocale(localeName)`, `translate(localeName, key, args)`, `warningText(localeName, code)`, `resultText(localeName, result)`, `stateText(localeName, state)`, and `stageText(localeName, stage)`. Interpolate `{name}` placeholders; preserve unknown placeholders; fall back per key to English.
- [ ] Add complete catalogs for `en`, `de`, `es`, `fr`, `it`, `pt-BR`, `nl`, `pl`, `hr`, and `zh-CN`. Translate whole templates, not fragments. Never translate task/project/tag content, Quick Add syntax, setting keys, enum values, warning codes, action kinds/states/stages, IPC names, CLI flags, paths, or environment variables.
- [ ] Run `node --test tests/i18n.test.js`; expect pass.

### Task 2: Service and bar localization

- [ ] Add source-contract tests to `tests/manifest.test.js` proving `Service.qml` and `BarWidget.qml` import `I18n.js`, Service resolves `Qt.locale().name`, and notification commands pass translated summary/body after `--` without changing protocol codes.
- [ ] Run `node --test tests/manifest.test.js`; expect the new assertions to fail.
- [ ] Import `I18n.js` in `Service.qml`. Add `readonly property string localeName: I18n.resolveLocale(Qt.locale().name)` and `function tr(key, args) { return I18n.translate(localeName, key, args || {}) }`.
- [ ] Replace Service-owned display errors, preview/test feedback, scheduled-alert text, untitled-task fallbacks, and alert fallback text with complete translation templates. Keep `actionFinished`, IPC JSON fields, setting values, warning codes, and raw backend diagnostics compatible. Expose translated context-warning display separately rather than mutating protocol values.
- [ ] Import `I18n.js` in `BarWidget.qml`; translate idle/next/no-estimate labels, missing-service text, tooltips, and accessibility names through the effective Service locale, with direct system-locale fallback before Service loads.
- [ ] Run `node --test tests/manifest.test.js tests/i18n.test.js`; expect pass.

### Task 3: Panel localization and layout safety

- [ ] Add source-contract assertions in `tests/manifest.test.js` that `Panel.qml` imports `I18n.js`, routes display state through semantic mapping, and no longer uppercases raw protocol state for accessibility/display.
- [ ] Run `node --test tests/manifest.test.js`; expect the new assertions to fail.
- [ ] Import `I18n.js` in `Panel.qml` and add one translation helper using `engine.localeName` or resolved system locale. Replace all plugin-owned visible strings, placeholders, tooltips, feedback, status/error messages, and accessibility text from the inventory with catalog keys and complete named-placeholder templates.
- [ ] Use semantic mappings for warning codes, request errors, mutation message keys, states, stages, and kinds. Prefer `messageKey`/`messageArgs`; use stable result fields next; retain raw English/upstream `message` only as diagnostic fallback.
- [ ] Preserve user-authored task/project/parent/tag values verbatim. Preserve `+project`, `@schedule`, `#tag`, units embedded in protocol values, and all identifiers.
- [ ] Replace fixed-width translated text controls with content-driven width or adequate flexible layout where German/Polish text can clip. Keep existing maximum panel bounds and elision for user content.
- [ ] Format displayed date/time using the resolved locale instead of a fixed English day/AM-PM pattern.
- [ ] Run `qmllint -I /usr/share/omarchy/shell BarWidget.qml Panel.qml Service.qml` and `node --test tests/*.test.js`; expect pass.

### Task 4: Backward-compatible backend semantics and notifications

- [ ] Add Python tests first: `mutation_result()` retains English `message` and accepts validated optional `messageKey`/`messageArgs`; legacy `alert()` and `test_notification()` argv remain byte-for-byte unchanged; optional notification summary/body produce safe `notify-send` argv; malformed, duplicate, or missing CLI option values fail.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_backend.py tests/test_phase1_backend.py`; expect new tests to fail.
- [ ] Extend `mutation_result()` with optional `messageKey` and object `messageArgs`, emitted only when present. Add semantic keys to fixed mutation outcomes and synthetic QML action failures; never replace existing English `message`.
- [ ] Preserve additive metadata through `ActionModel.normalizeResult()` and validate it when present without adding it to required legacy fields.
- [ ] Extend `alert()` with optional `notification_title="Super Productivity"`; extend `test_notification()` with optional title/body defaults matching current English. Add backward-compatible CLI options `--notification-title` and `--body`; sanitize notification text through the existing safe-text boundary.
- [ ] Pass localized notification title/body from `Service.qml`. Keep old CLI forms, default function calls, JSON output shapes, exit codes, and IPC behavior working.
- [ ] Run Python unit tests, Node tests, and Python compile check; expect pass.

### Task 5: Packaging and full verification

- [ ] Add `I18n.js`, `tests/i18n.test.js`, and this plan to `RELEASE_FILES.txt` in sorted path order.
- [ ] Run `python3 scripts/verify_release_files.py`; expect pass.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_backend.py tests/test_phase1_backend.py tests/test_preview_assets.py`; expect pass.
- [ ] Run `node --test tests/*.test.js`; expect pass.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile backend/superproductivity.py`; expect pass.
- [ ] Run `omarchy plugin validate .`; expect pass.
- [ ] Run `qmllint -I /usr/share/omarchy/shell BarWidget.qml Panel.qml Service.qml`; expect no new errors.
- [ ] Run preview/default-sound generators and verify generated artifacts remain unchanged.
- [ ] Review the diff for untranslated plugin-owned UI strings, translated protocol tokens, placeholder mismatches, clipped controls, and changes to legacy backend English fields.

## Self-review

- Scope covered: runtime UI, accessibility text, notifications, and user-facing errors; manifest/docs/assets intentionally remain English.
- Locale policy covered: system locale, exact locale then language fallback, per-key English fallback.
- Compatibility covered: backend English messages and IPC fields remain; metadata/options are additive.
- Translation set covered: `en`, `de`, `es`, `fr`, `it`, `pt-BR`, `nl`, `pl`, `hr`, `zh-CN`.
