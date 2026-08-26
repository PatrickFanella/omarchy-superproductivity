# Contributing

## Report a bug

Include your Omarchy version, Super Productivity version, plugin version, and the output of these commands:

```bash
omarchy plugin validate .
backend/superproductivity.py status
omarchy-shell patrickfanella.superproductivity status
```

Replace task titles, task IDs, project names, parent names, dates, and home paths with synthetic values. Remove API error details if they contain work data. Never post the access token or an `Authorization` header.

For a possible vulnerability, follow the private process in [SECURITY.md](SECURITY.md#report-a-vulnerability).

## Submit a change

1. Fork and clone the repository.
2. Make one focused change.
3. Add or update tests.
4. Run the checks in [Develop](README.md#develop).
5. Open a pull request that states the behavior change and validation results.

Do not add runtime Python or JavaScript packages without explaining why the standard library cannot solve the problem.

## Run the checks

Verify that the release file list exactly matches the package tree:

```bash
python3 scripts/verify_release_files.py
```

Run the Python tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_backend.py tests/test_phase1_backend.py tests/test_preview_assets.py
```

Run every Node test:

```bash
node --test tests/*.test.js
```

Compile the helper, validate the manifest and entry points, and lint QML against Omarchy:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile backend/superproductivity.py
omarchy plugin validate .
qmllint -I /usr/share/omarchy/shell BarWidget.qml Panel.qml Service.qml
```

Regenerate the bundled sound and preview assets, then require a clean diff:

```bash
python3 scripts/generate_default_sound.py
git diff --exit-code -- assets/timer-complete.wav
python3 scripts/generate_preview_assets.py
git diff --exit-code -- assets/demo.gif assets/preview-src assets/screenshots
```

## Test mutation changes

Cover each result state that the change can produce: `succeeded`, `partial`, `conflict`, `failed`, and `unknown`. Assert the `stage`, `mutationApplied`, and `followupMutationApplied` values where applicable. Include races between preflight, dispatch, and verification for compound operations.

Tests must not depend on a live Super Productivity database. Use synthetic task titles and IDs. Do not add real screenshots, logs, token paths, or task data to fixtures.
