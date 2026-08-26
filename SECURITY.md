# Security policy

## Supported versions

Security fixes apply to the latest release.

## Report a vulnerability

Do not open a public issue for a vulnerability that could expose a Super Productivity access token or task data.

Use GitHub's private vulnerability reporting for `patrickfanella/omarchy-superproductivity`. If private reporting is unavailable, open an issue that asks the maintainer for a private contact method. Do not include vulnerability details in that issue.

Include the affected version, reproduction steps, impact, and a proposed mitigation if you have one. You can expect an initial response within seven days. Public disclosure waits until a fix or mitigation is available.

## Trust boundaries

Omarchy loads the plugin without a sandbox inside `omarchy-shell`. The plugin has the shell process's user permissions. It starts the bundled `backend/superproductivity.py` helper and exchanges JSON through local subprocess pipes.

The helper:

- reads a Super Productivity REST API token from a direct environment value or local file;
- sends the token only to an HTTP or HTTPS URL whose host is exactly `localhost`, `127.0.0.1`, or `::1`;
- rejects URL credentials, queries, fragments, redirects, and proxy use;
- rejects token files that are not regular, user-owned files with no group or world permissions;
- opens token and lock files without following symlinks and checks for a token-file replacement race;
- serializes plugin mutations with an advisory `flock` in a private runtime directory;
- starts `notify-send`, `pw-play`, `paplay`, `canberra-gtk-play`, `hyprctl`, `gtk-launch`, or `xdg-open` with argument arrays and no shell;
- limits notification, sound, preview, and app-open subprocess lifetimes.

The plugin does not need root privileges and does not contact a hosted service.

## Remaining local risks

Loopback HTTP with a bearer token does not authenticate the server process. While Super Productivity is not listening, another local account can bind the configured port and receive the token on the next request. A health check cannot prove which process owns the port. Use the plugin only when you trust every account that can run processes on the machine.

The advisory lock serializes this plugin's helper processes. It does not serialize the Super Productivity UI or other REST clients. Stop uses an untargeted upstream endpoint. Complete, Extend, Add & switch, and auto-next use multiple requests because the API has no transaction or revision guard. The helper reports detected conflicts, partial results, and unknown dispatch outcomes, but it cannot detect every race.

Environment tokens can appear in child-process environments, crash reports, and diagnostic tools. Prefer `SUPER_PRODUCTIVITY_TOKEN_FILE` with mode `0600`.

Custom sounds are limited to readable regular files under the current home directory or `/usr/share/sounds`. They must use an accepted audio suffix and be no larger than 20 MiB. The helper treats the selected player as trusted local software.

## Protect diagnostic data

The helper does not print the token or construct shell command strings. Its JSON output can contain task titles, task IDs, project names, parent names, dates, and API error text. The Omarchy IPC `status` and `action` responses expose the same work context to local callers with access to the shell IPC endpoint.

Before you post a log or bug report:

1. Remove task titles, task IDs, project names, dates, and file paths.
2. Remove `Authorization` headers and token values.
3. Reproduce with synthetic task data when possible.
