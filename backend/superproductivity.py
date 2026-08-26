#!/usr/bin/env python3
"""Small JSON-only bridge to Super Productivity's local REST API."""

from __future__ import annotations

import datetime as dt
import fcntl
import http.client
import json
import math
import os
import re
import signal
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps
from pathlib import Path
from contextlib import contextmanager
from typing import Any

DEFAULT_API_URL = "http://127.0.0.1:3876"
DEFAULT_TOKEN_FILE = Path("~/.config/superProductivity/local-rest-api-token")
TOKEN_FILE_CANDIDATES = (
    DEFAULT_TOKEN_FILE,
    Path("~/.var/app/com.super_productivity.SuperProductivity/config/superProductivity/local-rest-api-token"),
    Path("~/snap/superproductivity/common/.config/superProductivity/local-rest-api-token"),
    Path("~/snap/superproductivity/current/.config/superProductivity/local-rest-api-token"),
)
DURATION_PART = r"\d+(?:\.\d+)?[hm]"
TIME_RE = re.compile(
    rf"(?<!\S)t?\s*(?P<left>{DURATION_PART}(?:\s+{DURATION_PART})*)"
    rf"(?:\s*(?P<slash>/)\s*(?P<right>{DURATION_PART}(?:\s+{DURATION_PART})*)?)?(?!\S)",
    re.I,
)
DUE_RE = re.compile(
    r"@(today|tomorrow|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|\d{4}-\d{2}-\d{2})\b",
    re.I,
)
TAG_RE = re.compile(r"(?<!\S)#([\w-]+)", re.UNICODE)
PROJECT_MARKER_RE = re.compile(r"(?<!\S)\+")
MAX_TASK_ID_LENGTH = 255
MAX_ALERT_TITLE_LENGTH = 200
MAX_SOUND_SIZE = 20 * 1024 * 1024
NOTIFICATION_TIMEOUT = 10
SOUND_PLAYBACK_TIMEOUT = 60
PREVIEW_PLAYBACK_TIMEOUT = 3
PREVIEW_TERM_GRACE = 0.2
AUTO_NEXT_GRACE = 0.3
DEFAULT_AUTO_NEXT_WINDOW_MINUTES = 30
MAX_ESTIMATE_MS = 365 * 24 * 60 * 60 * 1000
URGENCIES = {"low", "normal", "critical"}
SOUND_SUFFIXES = {".wav", ".ogg", ".oga", ".flac", ".mp3"}
DEFAULT_SOUND = Path(__file__).resolve().parents[1] / "assets" / "timer-complete.wav"


class BridgeError(Exception):
    pass


class RequestRejected(BridgeError):
    """The server returned a parsed rejection known not to apply."""


class DispatchUnknown(BridgeError):
    """The request was dispatched but its application is unknowable."""


def _has_unicode_control(value: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def validate_api_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError as error:
        raise BridgeError("Invalid Super Productivity API URL") from error
    if parsed.scheme not in {"http", "https"}:
        raise BridgeError("Super Productivity API URL must use HTTP or HTTPS")
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise BridgeError("Super Productivity API URL must use a loopback host")
    if "@" in parsed.netloc:
        raise BridgeError("Super Productivity API URL must not contain credentials")
    if "#" in value:
        raise BridgeError("Super Productivity API URL must not contain a fragment")
    if "?" in value:
        raise BridgeError("Super Productivity API URL must not contain a query string")
    return value.rstrip("/")


def api_url(env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    return validate_api_url(
        values.get("SUPERPRODUCTIVITY_API_URL")
        or values.get("SUPER_PRODUCTIVITY_REST_URL")
        or values.get("SP_LOCAL_REST_URL")
        or values.get("SUPER_PRODUCTIVITY_URL")
        or DEFAULT_API_URL
    )


def read_token(env: dict[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    direct = values.get("SP_LOCAL_REST_TOKEN") or values.get("SUPER_PRODUCTIVITY_TOKEN")
    if direct:
        return direct.strip()
    if "SUPER_PRODUCTIVITY_TOKEN_FILE" in values:
        path = Path(values["SUPER_PRODUCTIVITY_TOKEN_FILE"]).expanduser()
    else:
        candidates = (candidate.expanduser() for candidate in TOKEN_FILE_CANDIDATES)
        path = next((candidate for candidate in candidates if candidate.exists()), DEFAULT_TOKEN_FILE.expanduser())
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return ""
    except OSError as error:
        raise BridgeError(f"Could not read token file: {error.strerror or error}") from error
    if not stat.S_ISREG(file_stat.st_mode):
        raise BridgeError("Token file must be a regular file")
    if sys.platform.startswith("linux"):
        if file_stat.st_uid != os.geteuid():
            raise BridgeError("Token file must be owned by the current user")
        if stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise BridgeError("Token file permissions must not allow group or world access")
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except OSError as error:
        raise BridgeError(f"Could not read token file: {error.strerror or error}") from error
    try:
        opened_stat = os.fstat(descriptor)
        if (opened_stat.st_dev, opened_stat.st_ino) != (file_stat.st_dev, file_stat.st_ino):
            raise BridgeError("Token file changed while being read")
        with os.fdopen(descriptor, encoding="utf-8") as token_file:
            descriptor = -1
            return token_file.read().strip()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class Client:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = validate_api_url(base_url) if base_url else api_url()
        self.token = read_token() if token is None else token
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            RejectRedirects(),
        )

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            self.base_url + "/" + path.lstrip("/"), data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                try:
                    error_payload = json.loads(error.read().decode("utf-8"))
                except Exception as read_error:
                    raise DispatchUnknown(
                        f"Could not determine whether Super Productivity applied the request: HTTP {error.code}"
                    ) from read_error
            finally:
                error.close()
            if 400 <= error.code < 500 and isinstance(error_payload, dict) and (
                error_payload.get("ok") is False or "error" in error_payload
            ):
                detail = error_payload.get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else detail
                raise RequestRejected(str(message or f"Super Productivity returned HTTP {error.code}")) from error
            raise DispatchUnknown(
                f"Could not determine whether Super Productivity applied the request: HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException, OSError, EOFError) as error:
            raise DispatchUnknown(f"Could not complete Super Productivity request: {getattr(error, 'reason', error)}") from error
        except (ValueError, UnicodeDecodeError) as error:
            raise DispatchUnknown("Super Productivity returned invalid JSON") from error

        if isinstance(payload, dict) and payload.get("ok") is False:
            detail = payload.get("error", "Super Productivity request failed")
            message = detail.get("message") if isinstance(detail, dict) else detail
            raise DispatchUnknown(str(message))
        if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
            return payload["data"]
        return payload


def _duration_ms(value: str) -> int:
    total = 0
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)([hm])", value, re.I):
        total += round(float(amount) * (3_600_000 if unit.lower() == "h" else 60_000))
    return total


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _due_day(word: str, today: dt.date) -> str:
    lowered = word.lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", lowered):
        try:
            return dt.date.fromisoformat(lowered).isoformat()
        except ValueError as error:
            raise BridgeError(f"Invalid due date: {word}") from error
    if lowered == "today":
        return today.isoformat()
    if lowered == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    weekdays = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    target = weekdays[lowered[:3]]
    days = (target - today.weekday()) % 7 or 7
    return (today + dt.timedelta(days=days)).isoformat()


def parse_shorthand(
    text: str,
    projects: list[dict[str, Any]],
    tags: list[dict[str, Any]],
    today: dt.date | None = None,
) -> dict[str, Any]:
    if not text or not text.strip():
        raise BridgeError("Task title must not be empty")
    result: dict[str, Any] = {"title": text.strip(), "projectId": "INBOX_PROJECT"}
    remove: list[tuple[int, int]] = []

    tag_ids: list[Any] = []
    for tag in TAG_RE.finditer(text):
        name = _normalized(tag.group(1))
        match = next(
            (
                candidate
                for candidate in tags
                if candidate.get("id")
                and _normalized(candidate.get("title") or candidate.get("name")) == name
            ),
            None,
        )
        if match is None:
            raise BridgeError(f"Unknown tag: {tag.group(0)}")
        if match["id"] not in tag_ids:
            tag_ids.append(match["id"])
        remove.append(tag.span())
    if tag_ids:
        result["tagIds"] = tag_ids

    due = DUE_RE.search(text)
    if due:
        result["dueDay"] = _due_day(due.group(1), today or dt.date.today())
        remove.append(due.span())

    duration = TIME_RE.search(text)
    if duration:
        first = _duration_ms(duration.group("left"))
        if duration.group("slash"):
            result["timeSpent"] = first
            if duration.group("right"):
                result["timeEstimate"] = _duration_ms(duration.group("right"))
        else:
            result["timeEstimate"] = first
        remove.append(duration.span())

    without_metadata_chars = list(text)
    for start, end in remove:
        without_metadata_chars[start:end] = " " * (end - start)
    without_metadata = "".join(without_metadata_chars)
    markers = list(PROJECT_MARKER_RE.finditer(without_metadata))
    if len(markers) > 1:
        raise BridgeError("Only one project may be specified")
    if markers:
        marker = markers[0]
        query = _normalized(without_metadata[marker.end():])
        if not query:
            raise BridgeError("Project name must follow +")
        candidates: list[tuple[int, dict[str, Any], tuple[int, int]]] = []
        exact_candidates: list[tuple[int, dict[str, Any], tuple[int, int]]] = []
        for project in projects:
            title = _normalized(project.get("title") or project.get("name"))
            if project.get("id") and title == query:
                exact_candidates.append((len(title), project, (marker.start(), len(without_metadata.rstrip()))))
                continue
            if project.get("id") and title.startswith(query):
                candidates.append((len(title), project, (marker.start(), len(without_metadata.rstrip()))))
                continue
            title_pattern = r"\s+".join(re.escape(part) for part in title.split())
            exact = re.match(rf"{title_pattern}(?=\s|$)", without_metadata[marker.end():], re.I)
            if project.get("id") and exact:
                candidates.append((len(title), project, (marker.start(), marker.end() + exact.end())))
        if exact_candidates:
            candidates = exact_candidates
        if not candidates:
            raise BridgeError(f"Unknown project: +{query}")
        if len(candidates) != 1:
            raise BridgeError(f"Ambiguous project: +{query}")
        _, project, project_span = candidates[0]
        result["projectId"] = project["id"]
        remove.append(project_span)

    title_chars = list(text)
    for start, end in remove:
        title_chars[start:end] = " " * (end - start)
    title = "".join(title_chars)
    result["title"] = re.sub(r"\s+", " ", title).strip() or text.strip()
    return result


def validate_task_id(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TASK_ID_LENGTH:
        raise BridgeError("Invalid task ID")
    if _has_unicode_control(value):
        raise BridgeError("Invalid task ID")
    return value


def normalize_parent_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return validate_task_id(value)


def _finite_nonnegative(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def normalize_task(value: Any, projects: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BridgeError("Super Productivity returned a malformed task")
    validate_task_id(value.get("id"))
    if not isinstance(value.get("title"), str):
        raise BridgeError("Super Productivity returned a malformed task")
    for field in ("timeEstimate", "timeSpent"):
        number = value.get(field, 0)
        if not _finite_nonnegative(number):
            raise BridgeError("Super Productivity returned a malformed task")
    try:
        parent_id = normalize_parent_id(value.get("parentId"))
    except BridgeError as error:
        raise BridgeError("Super Productivity returned a malformed task") from error
    sub_task_ids = value.get("subTaskIds", [])
    due_with_time = value.get("dueWithTime")
    if not _finite_nonnegative(due_with_time) or due_with_time == 0:
        due_with_time = None
    due_day = value.get("dueDay")
    if not isinstance(due_day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_day):
        due_day = None
    project_id = value.get("projectId")
    return {
        "id": value["id"],
        "title": value["title"],
        "timeEstimate": value.get("timeEstimate", 0),
        "timeSpent": value.get("timeSpent", 0),
        "projectId": project_id,
        "projectTitle": (projects or {}).get(project_id) if isinstance(project_id, str) else None,
        "parentId": parent_id,
        "parentTitle": None,
        "subTaskIds": list(sub_task_ids) if isinstance(sub_task_ids, list) else [],
        "isDone": value.get("isDone") is True,
        "dueDay": due_day,
        "dueWithTime": due_with_time,
        "depth": 0,
    }


def normalize_task_strict(value: Any, projects: dict[str, str] | None = None) -> dict[str, Any]:
    task = normalize_task(value, projects)
    child_ids = value.get("subTaskIds", [])
    if not isinstance(child_ids, list):
        raise BridgeError("Super Productivity returned a malformed task")
    try:
        task["subTaskIds"] = [validate_task_id(child_id) for child_id in child_ids]
    except BridgeError as error:
        raise BridgeError("Super Productivity returned a malformed task") from error
    return task


def build_hierarchy(
    values: Any,
    projects: dict[str, str] | None = None,
    include_done: bool = False,
    hidden_child_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(values, list):
        raise BridgeError("Super Productivity returned a malformed task list")
    warnings: list[str] = []
    tasks: list[dict[str, Any]] = []
    raw_by_id: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for raw in values:
        try:
            task = normalize_task(raw, projects)
        except BridgeError:
            warnings.append("malformed-task")
            continue
        task_id = task["id"]
        if task_id in by_id:
            warnings.append("duplicate-task-id")
            continue
        by_id[task_id] = task
        raw_by_id[task_id] = raw
        tasks.append(task)

    owners: dict[str, str] = {}
    top_level = [task for task in tasks if not task["parentId"]]
    for parent in top_level:
        raw_children = raw_by_id[parent["id"]].get("subTaskIds", [])
        if not isinstance(raw_children, list) or any(not isinstance(child, str) for child in raw_children):
            parent["subTaskIds"] = []
            warnings.append("malformed-child-list")
            continue
        parent["subTaskIds"] = list(raw_children)
        for child_id in raw_children:
            if child_id not in by_id:
                if child_id not in (hidden_child_ids or set()):
                    warnings.append("missing-child")
                continue
            if child_id in owners and owners[child_id] != parent["id"]:
                warnings.append("conflicting-parent")
                continue
            owners[child_id] = parent["id"]

    output: list[dict[str, Any]] = []
    rendered: set[str] = set()
    for task in tasks:
        if task["id"] in rendered:
            continue
        if task["parentId"]:
            if task["parentId"] in by_id:
                continue
            warnings.append("missing-parent")
            task["depth"] = 1
            rendered.add(task["id"])
            if include_done or not task["isDone"]:
                output.append(task)
            continue
        parent = task
        if parent["id"] in owners:
            continue
        if include_done or not parent["isDone"]:
            output.append(parent)
            rendered.add(parent["id"])
        for child_id in parent["subTaskIds"]:
            child = by_id.get(child_id)
            if child is None or child_id in rendered or owners.get(child_id) != parent["id"]:
                continue
            if child.get("parentId") not in (None, parent["id"]):
                warnings.append("conflicting-parent")
            child["parentId"] = parent["id"]
            child["parentTitle"] = parent["title"]
            child["depth"] = 1
            rendered.add(child_id)
            if include_done or not child["isDone"]:
                output.append(child)

    for task in tasks:
        if task["id"] in rendered or not task["parentId"]:
            continue
        parent = by_id.get(task["parentId"])
        if parent is not None:
            warnings.append("conflicting-parent")
            task["parentTitle"] = parent["title"]
        task["depth"] = 1
        if include_done or not task["isDone"]:
            output.append(task)
    return output, warnings


def chronological_hierarchy(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    indices: dict[str, int] = {}
    for index, task in enumerate(values):
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str) or task_id in by_id:
            continue
        by_id[task_id] = task
        indices[task_id] = index

    owned: dict[str, str] = {}
    for parent in values:
        if not isinstance(parent, dict) or normalize_parent_id(parent.get("parentId")) is not None:
            continue
        parent_id = parent.get("id")
        children = parent.get("subTaskIds")
        if not isinstance(parent_id, str) or not isinstance(children, list):
            continue
        for child_id in children:
            child = by_id.get(child_id) if isinstance(child_id, str) else None
            if child is not None and normalize_parent_id(child.get("parentId")) == parent_id:
                owned.setdefault(child_id, parent_id)

    def block_key(task_id: str) -> tuple[float, int]:
        due = by_id[task_id].get("dueWithTime")
        scheduled = (
            not isinstance(due, bool)
            and isinstance(due, (int, float))
            and math.isfinite(due)
            and due > 0
        )
        if not scheduled or not isinstance(due, (int, float)):
            return math.inf, indices[task_id]
        return float(due), indices[task_id]

    roots = sorted((task_id for task_id in by_id if task_id not in owned), key=block_key)
    output: list[dict[str, Any]] = []
    for root_id in roots:
        parent = by_id[root_id]
        root = dict(parent)
        if normalize_parent_id(root.get("parentId")) is not None:
            root["depth"] = 0
            root["parentTitle"] = None
        output.append(root)
        children = parent.get("subTaskIds")
        if normalize_parent_id(parent.get("parentId")) is not None or not isinstance(children, list):
            continue
        emitted: set[str] = set()
        for child_id in children:
            if not isinstance(child_id, str) or child_id in emitted or owned.get(child_id) != root_id:
                continue
            emitted.add(child_id)
            child = dict(by_id[child_id])
            child.update({"parentId": parent["id"], "parentTitle": parent.get("title"), "depth": 1})
            output.append(child)
    return output


def _project_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, list):
        raise BridgeError("Super Productivity returned a malformed project list")
    return {
        item["id"]: item["title"]
        for item in payload
        if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("title"), str)
    }


def _hydrate_today_children(today: list[Any], bulk: list[Any]) -> tuple[list[Any], set[str]]:
    present_ids = {
        item.get("id") for item in today
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    bulk_by_id: dict[str, dict[str, Any]] = {}
    for item in bulk:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        bulk_by_id.setdefault(item["id"], item)

    hydrated = list(today)
    added: set[str] = set()
    hidden: set[str] = set()
    for parent in today:
        if not isinstance(parent, dict) or parent.get("parentId"):
            continue
        child_ids = parent.get("subTaskIds", [])
        if not isinstance(child_ids, list):
            continue
        for child_id in child_ids:
            if not isinstance(child_id, str) or child_id in present_ids or child_id in added:
                continue
            child = bulk_by_id.get(child_id)
            if child is None:
                continue
            if child.get("isDone") is True:
                hidden.add(child_id)
                continue
            hydrated.append(child)
            added.add(child_id)
    return hydrated, hidden


def _scheduled_today(values: list[Any], projects: dict[str, str] | None = None) -> list[dict[str, Any]]:
    scheduled: list[tuple[float, int, dict[str, Any]]] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict) or value.get("isDone") is True or value.get("parentId"):
            continue
        due_with_time = value.get("dueWithTime")
        if (isinstance(due_with_time, bool) or not isinstance(due_with_time, (int, float))
                or not math.isfinite(due_with_time) or due_with_time <= 0):
            continue
        try:
            task = normalize_task(value, projects)
        except BridgeError:
            continue
        scheduled.append((float(due_with_time), index, task))
    scheduled.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scheduled]


def status(client: Client) -> dict[str, Any]:
    warnings: list[str] = []
    today_payload: Any = None
    projects_payload: Any = None
    tasks_payload: Any = None
    today_ok = projects_ok = tasks_ok = False
    today_fetched_at: int | None = None
    try:
        today_payload = client.request("GET", "/tasks?tagId=TODAY")
        today_fetched_at = time.time_ns() // 1_000_000
        if not isinstance(today_payload, list):
            raise BridgeError("malformed")
        today_ok = True
    except BridgeError:
        today_fetched_at = None
        warnings.append("today-unavailable")
    try:
        projects_payload = client.request("GET", "/projects")
        projects = _project_map(projects_payload)
        projects_ok = True
    except BridgeError:
        projects = {}
        warnings.append("projects-unavailable")
    try:
        tasks_payload = client.request("GET", "/tasks")
        if not isinstance(tasks_payload, list):
            raise BridgeError("malformed")
        tasks_ok = True
    except BridgeError:
        warnings.append("tasks-unavailable")
    current_payload = _parse_current_payload(client.request("GET", "/task-control/current"))
    fetched_at = time.time_ns() // 1_000_000
    today_tasks: list[dict[str, Any]] = []
    scheduled_tasks: list[dict[str, Any]] | None = None
    if today_ok:
        scheduled_tasks = _scheduled_today(today_payload, projects)
        hierarchy_payload, hidden_child_ids = (
            _hydrate_today_children(today_payload, tasks_payload) if tasks_ok else (today_payload, set())
        )
        today_tasks, hierarchy_warnings = build_hierarchy(
            hierarchy_payload, projects, hidden_child_ids=hidden_child_ids
        )
        today_tasks = chronological_hierarchy(today_tasks)
        warnings.extend(hierarchy_warnings)
    task = None if current_payload is None else normalize_task(current_payload, projects)
    if task and task["parentId"] and today_ok:
        parent = next((candidate for candidate in today_tasks if candidate["id"] == task["parentId"]), None)
        task["parentTitle"] = parent["title"] if parent else None
        task["depth"] = 1
    signed = None if task is None else task["timeEstimate"] - task["timeSpent"]
    return {
        "ok": True,
        "task": task,
        "todayTasks": today_tasks,
        "scheduledTasks": scheduled_tasks,
        "todayFetchedAt": today_fetched_at,
        "fetchedAt": fetched_at,
        "signedRemainingMs": signed,
        "remainingMs": max(0, signed or 0),
        "overtimeMs": max(0, -(signed or 0)),
        "context": {"todayOk": today_ok, "projectsOk": projects_ok, "tasksOk": tasks_ok, "warnings": warnings},
    }


def _task_path(task_id: str) -> str:
    return "/tasks/" + urllib.parse.quote(validate_task_id(task_id), safe="")


def _parse_current_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return normalize_task_strict(value)
    except BridgeError as error:
        raise BridgeError("Super Productivity returned a malformed task for current task") from error


def _current_id(value: Any) -> str | None:
    current = _parse_current_payload(value)
    return None if current is None else current["id"]


def mutation_result(kind: str, target: str | None, state: str, stage: str, applied: bool | None, **values: Any) -> dict[str, Any]:
    result = {
        "ok": state == "succeeded",
        "kind": kind,
        "targetTaskId": target,
        "state": state,
        "stage": stage,
        "mutationApplied": applied,
        "expectedCurrentId": values.pop("expectedCurrentId", None),
        "observedCurrentId": values.pop("observedCurrentId", None),
        "finalCurrentId": values.pop("finalCurrentId", None),
        "raceDetected": values.pop("raceDetected", False),
        "createdTaskId": values.pop("createdTaskId", None),
        "message": values.pop("message", ""),
    }
    result.update(values)
    return result


def structured_mutator(kind: str):
    def decorate(function):
        @wraps(function)
        def wrapped(client: Client, *args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return function(client, *args, **kwargs)
            except Exception as error:
                target = None
                if kind != "add" and args and isinstance(args[0], str):
                    target = args[0]
                return mutation_result(
                    kind,
                    target,
                    "failed",
                    "preflight",
                    False,
                    message=str(error) or error.__class__.__name__,
                )
        return wrapped
    return decorate


@contextmanager
def mutation_lock():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/superproductivity-{os.getuid()}")
    try:
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        runtime_stat = runtime.lstat()
    except OSError as error:
        raise BridgeError(f"Could not secure mutation lock directory: {error.strerror or error}") from error
    if not stat.S_ISDIR(runtime_stat.st_mode):
        raise BridgeError("Mutation lock directory must be a directory, not a symlink")
    if runtime_stat.st_uid != os.geteuid():
        raise BridgeError("Mutation lock directory must be owned by the current user")
    if stat.S_IMODE(runtime_stat.st_mode) & 0o077:
        raise BridgeError("Mutation lock directory must not allow group or world access")
    path = runtime / "patrickfanella-superproductivity.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise BridgeError(f"Could not securely open mutation lock: {error.strerror or error}") from error
    locked = False
    try:
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise BridgeError("Mutation lock must be a regular file")
        if lock_stat.st_uid != os.geteuid():
            raise BridgeError("Mutation lock must be owned by the current user")
        if stat.S_IMODE(lock_stat.st_mode) & 0o077:
            raise BridgeError("Mutation lock must not allow group or world access")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _request_mutation(client: Client, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[Any, str | None]:
    try:
        return client.request(method, path, body), None
    except RequestRejected as error:
        return None, str(error)
    except (DispatchUnknown, BridgeError) as error:
        raise DispatchUnknown(str(error)) from error


_EXPECTED_CURRENT_UNSET = object()


def _start_unlocked(
    client: Client,
    task_id: str,
    kind: str = "start",
    expected_current_id: object = _EXPECTED_CURRENT_UNSET,
) -> dict[str, Any]:
    task_id = validate_task_id(task_id)
    try:
        requested = client.request("GET", _task_path(task_id))
    except BridgeError as error:
        return mutation_result(kind, task_id, "failed", "preflight", False, message=str(error))
    if not isinstance(requested, dict):
        return mutation_result(kind, task_id, "failed", "preflight", False, message="Malformed requested task")
    actual_id = task_id
    children = requested.get("subTaskIds", [])
    if requested.get("parentId"):
        children = []
    elif not isinstance(children, list) or any(not isinstance(value, str) for value in children):
        return mutation_result(kind, task_id, "conflict", "preflight", False, message="Malformed child state")
    elif children:
        try:
            all_tasks = client.request("GET", "/tasks?includeDone=true")
        except BridgeError as error:
            return mutation_result(kind, task_id, "failed", "preflight", False, message=str(error))
        if not isinstance(all_tasks, list):
            return mutation_result(kind, task_id, "conflict", "preflight", False, message="Malformed child state")
        task_map = {item.get("id"): item for item in all_tasks if isinstance(item, dict) and isinstance(item.get("id"), str)}
        if any(child not in task_map for child in children):
            return mutation_result(kind, task_id, "conflict", "preflight", False, message="Missing child")
        actual_id = next((child for child in children if task_map[child].get("isDone") is not True), "")
        if not actual_id:
            return mutation_result(kind, task_id, "conflict", "preflight", False, message="No unfinished child")
    if expected_current_id is not _EXPECTED_CURRENT_UNSET:
        try:
            observed = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result(kind, task_id, "conflict", "preflight", False, expectedCurrentId=expected_current_id, message=str(error))
        if observed != expected_current_id:
            return mutation_result(kind, task_id, "conflict", "preflight", False, expectedCurrentId=expected_current_id, observedCurrentId=observed, finalCurrentId=observed, raceDetected=True, message="Current task changed before switch")
    try:
        _, rejection = _request_mutation(client, "POST", "/task-control/current", {"taskId": task_id})
    except DispatchUnknown as error:
        return mutation_result(kind, task_id, "unknown", "dispatch", None, message=str(error))
    if rejection:
        return mutation_result(kind, task_id, "failed", "dispatch", False, message=rejection)
    try:
        observed = _current_id(client.request("GET", "/task-control/current"))
    except BridgeError as error:
        return mutation_result(kind, task_id, "unknown", "verify", True, message=str(error))
    if observed != actual_id:
        return mutation_result(kind, task_id, "unknown", "verify", True, finalCurrentId=observed, observedCurrentId=observed, raceDetected=True, actualTaskId=actual_id, message="Unexpected current task")
    return mutation_result(kind, task_id, "succeeded", "done", True, finalCurrentId=observed, observedCurrentId=observed, actualTaskId=actual_id, message="Task started")


@structured_mutator("start")
def start(client: Client, task_id: str) -> dict[str, Any]:
    try:
        task_id = validate_task_id(task_id)
    except BridgeError as error:
        return mutation_result("start", task_id if isinstance(task_id, str) else None, "failed", "validation", False, message=str(error))
    with mutation_lock():
        return _start_unlocked(client, task_id)


@structured_mutator("stop")
def stop(client: Client, expected_current_id: str) -> dict[str, Any]:
    try:
        expected_current_id = validate_task_id(expected_current_id)
    except BridgeError as error:
        return mutation_result("stop", expected_current_id if isinstance(expected_current_id, str) else None, "failed", "validation", False, expectedCurrentId=expected_current_id if isinstance(expected_current_id, str) else None, message=str(error))
    with mutation_lock():
        try:
            observed = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("stop", expected_current_id, "failed", "preflight", False, expectedCurrentId=expected_current_id, message=str(error))
        if observed != expected_current_id:
            return mutation_result("stop", expected_current_id, "conflict", "preflight", False, expectedCurrentId=expected_current_id, observedCurrentId=observed, finalCurrentId=observed, raceDetected=True, message="Current task changed")
        try:
            _, rejection = _request_mutation(client, "POST", "/task-control/stop")
        except DispatchUnknown as error:
            return mutation_result("stop", expected_current_id, "unknown", "dispatch", None, expectedCurrentId=expected_current_id, observedCurrentId=observed, message=str(error))
        if rejection:
            return mutation_result("stop", expected_current_id, "failed", "dispatch", False, expectedCurrentId=expected_current_id, observedCurrentId=observed, message=rejection)
        try:
            final = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("stop", expected_current_id, "unknown", "verify", True, expectedCurrentId=expected_current_id, observedCurrentId=observed, message=str(error))
        if final is not None:
            return mutation_result("stop", expected_current_id, "partial", "verify", True, expectedCurrentId=expected_current_id, observedCurrentId=observed, finalCurrentId=final, raceDetected=True, message="Stop postcondition did not hold")
        return mutation_result("stop", expected_current_id, "succeeded", "done", True, expectedCurrentId=expected_current_id, observedCurrentId=observed, message="Task stopped")


def _fresh_children(client: Client, parent: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    children = parent.get("subTaskIds", [])
    if not isinstance(children, list):
        return None, "Malformed child state"
    try:
        for child_id in children:
            validate_task_id(child_id)
    except BridgeError:
        return None, "Malformed child state"
    if len(children) != len(set(children)):
        return None, "Duplicate child state"
    if not children:
        return [], None
    try:
        payload = client.request("GET", "/tasks?includeDone=true")
    except BridgeError as error:
        return None, str(error)
    if not isinstance(payload, list):
        return None, "Malformed child state"
    task_map: dict[str, dict[str, Any]] = {}
    for item in payload:
        try:
            normalized = normalize_task(item)
        except BridgeError:
            return None, "Malformed child state"
        task_id = normalized["id"]
        if task_id in task_map:
            return None, "Duplicate child state"
        task_map[task_id] = item
    if any(child_id not in task_map for child_id in children):
        return None, "Missing child"
    return [task_map[child_id] for child_id in children], None


def _auto_next_eligible(task: dict[str, Any], now_ms: int, window_ms: int) -> bool:
    due = task.get("dueWithTime")
    return (
        task.get("isDone") is not True
        and not task.get("subTaskIds")
        and not isinstance(due, bool)
        and isinstance(due, (int, float))
        and math.isfinite(due)
        and due > 0
        and abs(due - now_ms) <= window_ms
    )


def _runnable_ids(flattened: list[dict[str, Any]]) -> list[str]:
    return [
        task["id"] for task in flattened
        if not task.get("isDone") and not task.get("subTaskIds")
    ]


def _auto_next_candidate(
    flattened: list[dict[str, Any]],
    target_id: str,
    now_ms: int | None = None,
    window_ms: int = DEFAULT_AUTO_NEXT_WINDOW_MINUTES * 60_000,
) -> str | None:
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    by_id = {task["id"]: task for task in flattened}
    target = by_id.get(target_id)
    if target is None:
        return None
    positions = {task["id"]: index for index, task in enumerate(flattened)}
    if target.get("depth") == 1 and target.get("parentId"):
        parent = by_id.get(target["parentId"])
        siblings = parent.get("subTaskIds", []) if parent else []
        if target_id in siblings:
            for sibling_id in siblings[siblings.index(target_id) + 1:]:
                sibling = by_id.get(sibling_id)
                if sibling is not None and _auto_next_eligible(sibling, now_ms, window_ms):
                    return sibling_id
        anchor_id = target["parentId"]
    else:
        anchor_id = target_id
    anchor_position = positions.get(anchor_id, positions[target_id])
    if anchor_id in by_id and by_id[anchor_id].get("subTaskIds"):
        owned = [positions[value] for value in by_id[anchor_id]["subTaskIds"] if value in positions]
        anchor_position = max([anchor_position] + owned)
    return next((
        task["id"] for task in flattened[anchor_position + 1:]
        if _auto_next_eligible(task, now_ms, window_ms)
    ), None)


def validate_auto_next_window(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
        raise BridgeError("Auto-next window must be an integer from 1 to 1440 minutes")
    return value


@structured_mutator("complete-list")
def complete_listed_task(client: Client, task_id: str) -> dict[str, Any]:
    try:
        task_id = validate_task_id(task_id)
    except BridgeError as error:
        return mutation_result(
            "complete-list", task_id if isinstance(task_id, str) else None,
            "failed", "validation", False, message=str(error),
        )
    with mutation_lock():
        try:
            raw_target = client.request("GET", _task_path(task_id))
            target = normalize_task_strict(raw_target)
        except BridgeError as error:
            return mutation_result("complete-list", task_id, "failed", "preflight", False, message=str(error))
        if target["id"] != task_id:
            return mutation_result("complete-list", task_id, "conflict", "preflight", False, message="Requested task ID changed")
        if target["isDone"]:
            return mutation_result("complete-list", task_id, "conflict", "preflight", False, message="Task is already done")
        if target["subTaskIds"]:
            return mutation_result(
                "complete-list", task_id, "conflict", "preflight", False,
                message="Task retains subtasks; complete the parent in Super Productivity",
            )
        try:
            before = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete-list", task_id, "failed", "preflight", False, message=str(error))
        try:
            _, rejection = _request_mutation(client, "PATCH", _task_path(task_id), {"isDone": True})
        except DispatchUnknown as error:
            return mutation_result(
                "complete-list", task_id, "unknown", "dispatch", None,
                expectedCurrentId=before, observedCurrentId=before, message=str(error),
            )
        if rejection:
            return mutation_result(
                "complete-list", task_id, "failed", "dispatch", False,
                expectedCurrentId=before, observedCurrentId=before, message=rejection,
            )
        try:
            verified = normalize_task_strict(client.request("GET", _task_path(task_id)))
        except BridgeError as error:
            return mutation_result(
                "complete-list", task_id, "unknown", "verify", True,
                expectedCurrentId=before, observedCurrentId=before, message=str(error),
            )
        if verified["id"] != task_id or not verified["isDone"]:
            return mutation_result(
                "complete-list", task_id, "partial", "verify", True,
                expectedCurrentId=before, observedCurrentId=before, raceDetected=True,
                message="Completion postcondition did not hold",
            )
        if before != task_id:
            return mutation_result(
                "complete-list", task_id, "succeeded", "done", True,
                expectedCurrentId=before, observedCurrentId=before,
                message="Listed task completed",
            )
        try:
            final = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result(
                "complete-list", task_id, "partial", "verify", True,
                expectedCurrentId=before, observedCurrentId=before,
                message=str(error),
            )
        if final == task_id:
            return mutation_result(
                "complete-list", task_id, "partial", "verify", True,
                expectedCurrentId=before, observedCurrentId=before, finalCurrentId=final,
                raceDetected=True, message="Completed listed task remains current",
            )
        return mutation_result(
            "complete-list", task_id, "succeeded", "done", True,
            expectedCurrentId=before, observedCurrentId=before, finalCurrentId=final,
            message="Listed task completed",
        )


@structured_mutator("complete")
def complete(
    client: Client,
    task_id: str,
    auto_next: bool = False,
    auto_next_window_minutes: int = DEFAULT_AUTO_NEXT_WINDOW_MINUTES,
) -> dict[str, Any]:
    try:
        task_id = validate_task_id(task_id)
    except BridgeError as error:
        return mutation_result("complete", task_id if isinstance(task_id, str) else None, "failed", "validation", False, expectedCurrentId=task_id if isinstance(task_id, str) else None, message=str(error), autoNext="not-run")
    if auto_next:
        try:
            auto_next_window_minutes = validate_auto_next_window(auto_next_window_minutes)
        except BridgeError as error:
            return mutation_result("complete", task_id, "failed", "validation", False, expectedCurrentId=task_id, message=str(error), autoNext="not-run")
    window_ms = auto_next_window_minutes * 60_000
    with mutation_lock():
        try:
            observed = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "failed", "preflight", False, expectedCurrentId=task_id, message=str(error), autoNext="not-run")
        if observed != task_id:
            return mutation_result("complete", task_id, "conflict", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=observed, raceDetected=True, message="Current task changed", autoNext="not-run")
        candidate = None
        try:
            raw_target = client.request("GET", _task_path(task_id))
            target = normalize_task_strict(raw_target)
        except BridgeError as error:
            return mutation_result("complete", task_id, "failed", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="not-run")
        if target["id"] != task_id:
            return mutation_result("complete", task_id, "conflict", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message="Requested task ID changed", autoNext="not-run")
        if target["isDone"]:
            return mutation_result("complete", task_id, "conflict", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message="Task is already done", autoNext="not-run")
        if target["subTaskIds"]:
            return mutation_result(
                "complete", task_id, "conflict", "preflight", False,
                expectedCurrentId=task_id, observedCurrentId=observed,
                message="Task retains subtasks; complete the parent in Super Productivity",
                autoNext="not-run",
            )
        if auto_next:
            try:
                selection_now_ms = time.time_ns() // 1_000_000
                today = client.request("GET", "/tasks?tagId=TODAY")
                bulk = client.request("GET", "/tasks")
                if not isinstance(today, list) or not isinstance(bulk, list):
                    raise BridgeError("Super Productivity returned a malformed task list")
                hierarchy_payload, hidden_child_ids = _hydrate_today_children(today, bulk)
                flattened, _ = build_hierarchy(
                    hierarchy_payload,
                    include_done=True,
                    hidden_child_ids=hidden_child_ids,
                )
                candidate = _auto_next_candidate(
                    chronological_hierarchy(flattened), task_id, selection_now_ms, window_ms
                )
            except BridgeError as error:
                return mutation_result("complete", task_id, "failed", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="not-run")
        try:
            dispatch_current = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "failed", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="not-run")
        if dispatch_current != task_id:
            return mutation_result(
                "complete", task_id, "conflict", "preflight", False,
                expectedCurrentId=task_id, observedCurrentId=dispatch_current,
                finalCurrentId=dispatch_current, raceDetected=True,
                message="Current task changed before completion", autoNext="not-run",
            )
        observed = dispatch_current
        try:
            _, rejection = _request_mutation(client, "PATCH", _task_path(task_id), {"isDone": True})
        except DispatchUnknown as error:
            return mutation_result("complete", task_id, "unknown", "dispatch", None, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="not-run")
        if rejection:
            return mutation_result("complete", task_id, "failed", "dispatch", False, expectedCurrentId=task_id, observedCurrentId=observed, message=rejection, autoNext="not-run")
        try:
            verified = normalize_task_strict(client.request("GET", _task_path(task_id)))
        except BridgeError as error:
            return mutation_result("complete", task_id, "unknown", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="not-run")
        if verified["id"] != task_id or not verified["isDone"]:
            return mutation_result("complete", task_id, "partial", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, raceDetected=True, message="Completion postcondition did not hold", autoNext="not-run")
        if not auto_next:
            try:
                final = _current_id(client.request("GET", "/task-control/current"))
            except BridgeError as error:
                return mutation_result("complete", task_id, "partial", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error), autoNext="disabled")
            if final == task_id:
                return mutation_result("complete", task_id, "partial", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=final, raceDetected=True, message="Completed task remains current", autoNext="disabled")
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=final, message="Task completed", autoNext="disabled")
        try:
            first_current = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message=str(error), autoNext="current-unknown")
        if first_current == task_id:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=first_current, followupMutationApplied=False, raceDetected=True, message="Completed task remains current", autoNext="current-not-cleared", nextTaskId=candidate)
        if first_current is not None:
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=first_current, followupMutationApplied=False, message="Task completed", autoNext="skipped-upstream-current", nextTaskId=candidate)
        time.sleep(AUTO_NEXT_GRACE)
        try:
            second_current = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message=str(error), autoNext="current-unknown", nextTaskId=candidate)
        if second_current == task_id:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=second_current, followupMutationApplied=False, raceDetected=True, message="Completed task remains current", autoNext="current-not-cleared", nextTaskId=candidate)
        if second_current is not None:
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=second_current, followupMutationApplied=False, message="Task completed", autoNext="skipped-upstream-current", nextTaskId=candidate)
        if candidate is None:
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message="Task completed", autoNext="no-candidate")
        try:
            fresh_candidate = normalize_task_strict(client.request("GET", _task_path(candidate)))
        except BridgeError as error:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message=str(error), autoNext="candidate-stale", nextTaskId=candidate)
        revalidation_now_ms = time.time_ns() // 1_000_000
        if fresh_candidate["id"] != candidate or not _auto_next_eligible(
            fresh_candidate, revalidation_now_ms, window_ms
        ):
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message="Task completed; auto-next candidate is no longer eligible", autoNext="skipped-candidate", nextTaskId=candidate)
        try:
            third_current = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "partial", "followup-preflight", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message=str(error), autoNext="current-unknown", nextTaskId=candidate)
        if third_current is not None:
            return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=third_current, followupMutationApplied=False, message="Task completed", autoNext="skipped-upstream-current", nextTaskId=candidate)
        try:
            _, rejection = _request_mutation(client, "POST", "/task-control/current", {"taskId": candidate})
        except DispatchUnknown as error:
            return mutation_result("complete", task_id, "unknown", "followup-dispatch", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=None, message=str(error), autoNext="unknown", nextTaskId=candidate)
        if rejection:
            return mutation_result("complete", task_id, "partial", "followup-dispatch", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=False, message=rejection, autoNext="failed", nextTaskId=candidate)
        try:
            final = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("complete", task_id, "unknown", "followup-verify", True, expectedCurrentId=task_id, observedCurrentId=observed, followupMutationApplied=None, message=str(error), autoNext="unknown", nextTaskId=candidate)
        if final != candidate:
            return mutation_result("complete", task_id, "partial", "followup-verify", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=final, followupMutationApplied=True, raceDetected=True, message="Auto-next postcondition did not hold", autoNext="mismatch", nextTaskId=candidate)
        return mutation_result("complete", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=final, followupMutationApplied=True, message="Task completed and next task started", autoNext="started", nextTaskId=candidate)


@structured_mutator("extend")
def extend(client: Client, task_id: str, minutes: Any) -> dict[str, Any]:
    try:
        task_id = validate_task_id(task_id)
    except BridgeError as error:
        return mutation_result("extend", task_id if isinstance(task_id, str) else None, "failed", "validation", False, expectedCurrentId=task_id if isinstance(task_id, str) else None, message=str(error))
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 1440:
        return mutation_result("extend", task_id, "failed", "validation", False, expectedCurrentId=task_id, message="Minutes must be a whole number from 1 to 1440")
    with mutation_lock():
        try:
            observed = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("extend", task_id, "failed", "preflight", False, expectedCurrentId=task_id, message=str(error))
        if observed != task_id:
            return mutation_result("extend", task_id, "conflict", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, finalCurrentId=observed, raceDetected=True, message="Current task changed")
        try:
            task = client.request("GET", _task_path(task_id))
        except BridgeError as error:
            return mutation_result("extend", task_id, "failed", "preflight", False, expectedCurrentId=task_id, observedCurrentId=observed, message=str(error))
        old = task.get("timeEstimate") if isinstance(task, dict) else None
        intended = (old + minutes * 60_000) if isinstance(old, (int, float)) and _finite_nonnegative(old) else None
        if intended is None or intended > MAX_ESTIMATE_MS:
            return mutation_result("extend", task_id, "failed", "validation", False, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, message="Estimate must be finite and at most 365 days")
        try:
            written, rejection = _request_mutation(client, "PATCH", _task_path(task_id), {"timeEstimate": intended})
        except DispatchUnknown as error:
            return mutation_result("extend", task_id, "unknown", "dispatch", None, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, writtenEstimate=None, finalEstimate=None, message=str(error))
        if rejection:
            return mutation_result("extend", task_id, "failed", "dispatch", False, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, writtenEstimate=None, finalEstimate=None, message=rejection)
        written_estimate = written.get("timeEstimate") if isinstance(written, dict) else intended
        try:
            final_task = client.request("GET", _task_path(task_id))
            final_estimate = final_task.get("timeEstimate") if isinstance(final_task, dict) else None
        except BridgeError as error:
            return mutation_result("extend", task_id, "unknown", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, writtenEstimate=written_estimate, finalEstimate=None, message=str(error))
        if final_estimate != intended:
            return mutation_result("extend", task_id, "partial", "verify", True, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, writtenEstimate=written_estimate, finalEstimate=final_estimate, raceDetected=True, message="Estimate changed after write")
        return mutation_result("extend", task_id, "succeeded", "done", True, expectedCurrentId=task_id, observedCurrentId=observed, oldEstimate=old, intendedEstimate=intended, writtenEstimate=written_estimate, finalEstimate=final_estimate, message="Task extended")


def _safe_alert_title(value: str) -> str:
    sanitized = "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf"} else character
        for character in value
    )
    cleaned = " ".join(sanitized.split())
    return (cleaned or "Task")[:MAX_ALERT_TITLE_LENGTH]


def _side_effect(command: list[str], timeout: int = NOTIFICATION_TIMEOUT) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timed out"}
    except OSError:
        return {"ok": False, "error": "Command unavailable"}
    if completed.returncode != 0:
        return {"ok": False, "error": "Command failed"}
    return {"ok": True}


def resolve_sound(value: str | None) -> Path:
    if not value:
        path = DEFAULT_SOUND
    else:
        if _has_unicode_control(value):
            raise BridgeError("Invalid sound file")
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme or parsed.netloc:
            raise BridgeError("Invalid sound file")
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise BridgeError("Invalid sound file") from error

    try:
        path = path.resolve(strict=True)
        details = path.stat()
    except OSError as error:
        raise BridgeError("Invalid sound file") from error
    home = Path.home().resolve()
    shared = Path("/usr/share/sounds")
    if not (path == DEFAULT_SOUND.resolve() or path.is_relative_to(home) or path.is_relative_to(shared)):
        raise BridgeError("Invalid sound file")
    if (
        not stat.S_ISREG(details.st_mode)
        or not os.access(path, os.R_OK)
        or details.st_size > MAX_SOUND_SIZE
        or path.suffix.casefold() not in SOUND_SUFFIXES
    ):
        raise BridgeError("Invalid sound file")
    return path


def validate_urgency(value: str) -> str:
    if value not in URGENCIES:
        raise BridgeError("Urgency must be low, normal, or critical")
    return value


def validate_volume(value: Any) -> int:
    if isinstance(value, bool):
        raise BridgeError("Volume must be an integer from 0 to 100")
    if isinstance(value, str):
        if not re.fullmatch(r"\d+", value):
            raise BridgeError("Volume must be an integer from 0 to 100")
        volume = int(value)
    elif isinstance(value, int):
        volume = value
    else:
        raise BridgeError("Volume must be an integer from 0 to 100")
    if not 0 <= volume <= 100:
        raise BridgeError("Volume must be an integer from 0 to 100")
    return volume


def _player_command(path: Path, volume: int = 100) -> list[str] | None:
    volume = validate_volume(volume)
    canberra_db = -200.0 if volume == 0 else 20 * math.log10(volume / 100)
    players = (
        ("pw-play", ["pw-play", "--volume", f"{volume / 100:.2f}", str(path)]),
        ("paplay", ["paplay", "--volume", str(round(volume * 65536 / 100)), str(path)]),
        ("canberra-gtk-play", ["canberra-gtk-play", f"--volume={canberra_db:.2f}", "-f", str(path)]),
    )
    return next((argv for executable, argv in players if shutil.which(executable)), None)


def alert(
    title: str,
    urgency: str = "critical",
    sound_path: str | None = None,
    silent: bool = False,
    volume: int = 100,
) -> tuple[dict[str, Any], int]:
    urgency = validate_urgency(urgency)
    volume = validate_volume(volume)
    notification = _side_effect([
        "notify-send",
        f"--urgency={urgency}",
        "--icon=alarm-symbolic",
        "--",
        "Super Productivity",
        _safe_alert_title(title),
    ])
    sound: dict[str, Any] = {"requested": not silent, "volume": volume, "ok": False}
    if not silent:
        try:
            path = resolve_sound(sound_path)
            command = _player_command(path, volume)
            sound = _side_effect(command, timeout=SOUND_PLAYBACK_TIMEOUT) if command else {"ok": False, "error": "No sound player available"}
            sound["requested"] = True
            sound["volume"] = volume
        except BridgeError:
            sound = {"requested": True, "volume": volume, "ok": False, "error": "Invalid sound file"}

    ok = notification["ok"] or sound["ok"]
    return {"ok": ok, "notification": notification, "sound": sound}, 0 if ok else 1


def test_notification(urgency: str) -> tuple[dict[str, Any], int]:
    urgency = validate_urgency(urgency)
    result = _side_effect([
        "notify-send", f"--urgency={urgency}", "--icon=alarm-symbolic", "--",
        "Super Productivity", "Notification test",
    ])
    return {"ok": result["ok"], "notification": result}, 0 if result["ok"] else 1


def _terminate_player(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=PREVIEW_TERM_GRACE)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def preview_sound(sound_path: str | None = None, volume: int = 100) -> tuple[dict[str, Any], int]:
    volume = validate_volume(volume)
    path = resolve_sound(sound_path)
    command = _player_command(path, volume)
    if command is None:
        return {"ok": False, "sound": {"requested": True, "volume": volume, "ok": False, "error": "No sound player available"}}, 1
    old_handler = None
    threading_is_main = threading.current_thread() is threading.main_thread()
    old_mask: Any = set()
    blocked = False
    process = None
    try:
        if threading_is_main:
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
            blocked = True
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if threading_is_main:
            old_handler = signal.getsignal(signal.SIGTERM)
            def forward_term(_signum: int, _frame: Any) -> None:
                _terminate_player(process)
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, forward_term)
        try:
            if blocked:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
                blocked = False
            return_code = process.wait(timeout=PREVIEW_PLAYBACK_TIMEOUT)
        except subprocess.TimeoutExpired:
            _terminate_player(process)
            return {"ok": True, "sound": {"requested": True, "volume": volume, "ok": True, "capped": True}}, 0
    except OSError:
        if process is not None:
            _terminate_player(process)
        return {"ok": False, "sound": {"requested": True, "volume": volume, "ok": False, "error": "Command unavailable"}}, 1
    except BaseException:
        if process is not None:
            _terminate_player(process)
        raise
    finally:
        if blocked:
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        if threading_is_main and old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)
    ok = return_code == 0
    return {"ok": ok, "sound": {"requested": True, "volume": volume, "ok": ok}}, 0 if ok else 1


@structured_mutator("add")
def add(client: Client, shorthand: str, start_after: bool = False) -> dict[str, Any]:
    with mutation_lock():
        before = None
        if start_after:
            try:
                before = _current_id(client.request("GET", "/task-control/current"))
            except BridgeError as error:
                return mutation_result("add", None, "failed", "preflight", False, message=str(error), followupMutationApplied=False)
        try:
            projects = client.request("GET", "/projects")
            tags = client.request("GET", "/tags")
            task = parse_shorthand(
                shorthand,
                projects if isinstance(projects, list) else [],
                tags if isinstance(tags, list) else [],
            )
        except BridgeError as error:
            return mutation_result("add", None, "failed", "validation", False, expectedCurrentId=before if start_after else None, message=str(error), followupMutationApplied=False if start_after else None)
        try:
            created, rejection = _request_mutation(client, "POST", "/tasks", task)
        except DispatchUnknown as error:
            return mutation_result("add", None, "unknown", "dispatch", None, expectedCurrentId=before if start_after else None, message=str(error), followupMutationApplied=None if start_after else None)
        if rejection:
            return mutation_result("add", None, "failed", "dispatch", False, expectedCurrentId=before if start_after else None, message=rejection, followupMutationApplied=False if start_after else None)
        try:
            created_id = validate_task_id(created.get("id") if isinstance(created, dict) else None)
        except BridgeError:
            return mutation_result("add", None, "unknown", "verify", None, expectedCurrentId=before if start_after else None, message="Creation response did not contain a task ID", followupMutationApplied=None if start_after else None)
        if not start_after:
            result = mutation_result("add", created_id, "succeeded", "done", True, createdTaskId=created_id, message="Task added")
            result["task"] = created
            return result
        try:
            observed = _current_id(client.request("GET", "/task-control/current"))
        except BridgeError as error:
            return mutation_result("add", created_id, "partial", "followup-preflight", True, expectedCurrentId=before, createdTaskId=created_id, followupMutationApplied=False, message=str(error))
        if observed != before:
            return mutation_result("add", created_id, "partial", "followup-preflight", True, expectedCurrentId=before, observedCurrentId=observed, finalCurrentId=observed, createdTaskId=created_id, followupMutationApplied=False, raceDetected=True, message="Current task changed before switch")
        started = _start_unlocked(client, created_id, "add", before)
        if started["state"] == "succeeded":
            started.update({"targetTaskId": created_id, "createdTaskId": created_id, "expectedCurrentId": before, "mutationApplied": True, "followupMutationApplied": True, "message": "Task added and started"})
            return started
        followup = started["mutationApplied"]
        state = "unknown" if started["state"] == "unknown" else "partial"
        return mutation_result("add", created_id, state, "followup-" + started["stage"] if started["stage"] != "done" else "followup-verify", True, expectedCurrentId=before, observedCurrentId=observed, finalCurrentId=started.get("finalCurrentId"), createdTaskId=created_id, followupMutationApplied=followup, raceDetected=started.get("raceDetected", False), message=started["message"])


def show() -> dict[str, Any]:
    target = os.environ.get("SUPER_PRODUCTIVITY_APP_URL", "superproductivity://")
    commands = [
        ["hyprctl", "dispatch", "focuswindow", "title:^Super Productivity$"],
        ["gtk-launch", "superproductivity.desktop"],
        ["xdg-open", target],
    ]
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return {"ok": True, "message": "Super Productivity opened"}
    raise BridgeError("Could not open Super Productivity")


def run(argv: list[str]) -> tuple[dict[str, Any], int]:
    usage = "Usage: superproductivity.py status|add <task> [--start]|start <id>|stop <id>|complete <id> [--auto-next [--auto-next-window MINUTES]]|complete-task <id>|extend <id> <minutes>|test-notification --urgency VALUE|preview-sound [--sound PATH] [--volume VALUE]|alert --urgency VALUE [--sound PATH|--silent] [--volume VALUE] -- TITLE|show"
    if not argv:
        raise BridgeError(usage)
    command = argv[0]
    if command == "status" and len(argv) == 1:
        return status(Client()), 0
    if command == "add" and len(argv) in (2, 3) and (len(argv) == 2 or argv[2] == "--start"):
        result = add(Client(), argv[1], len(argv) == 3)
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "start" and len(argv) == 2:
        result = start(Client(), argv[1])
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "stop" and len(argv) == 2:
        result = stop(Client(), argv[1])
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "complete" and len(argv) >= 2:
        auto_next = False
        window = DEFAULT_AUTO_NEXT_WINDOW_MINUTES
        window_seen = False
        index = 2
        while index < len(argv):
            option = argv[index]
            if option == "--auto-next" and not auto_next:
                auto_next = True
                index += 1
            elif option == "--auto-next-window" and not window_seen and index + 1 < len(argv):
                raw_window = argv[index + 1]
                if not re.fullmatch(r"\d+", raw_window):
                    raise BridgeError("Auto-next window must be an integer from 1 to 1440 minutes")
                window = validate_auto_next_window(int(raw_window))
                window_seen = True
                index += 2
            else:
                raise BridgeError("Invalid complete arguments")
        if window_seen and not auto_next:
            raise BridgeError("--auto-next-window requires --auto-next")
        result = complete(Client(), argv[1], auto_next, window)
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "complete-task" and len(argv) == 2:
        result = complete_listed_task(Client(), argv[1])
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "extend" and len(argv) == 3:
        minutes: Any = int(argv[2]) if re.fullmatch(r"\d+", argv[2]) else argv[2]
        result = extend(Client(), argv[1], minutes)
        return result, 0 if result["state"] == "succeeded" else 1
    if command == "test-notification" and len(argv) == 3 and argv[1] == "--urgency":
        return test_notification(argv[2])
    if command == "preview-sound":
        sound_path = None
        volume = 100
        volume_seen = False
        index = 1
        while index < len(argv):
            option = argv[index]
            if option == "--sound" and index + 1 < len(argv) and sound_path is None:
                sound_path = argv[index + 1]
                index += 2
            elif option == "--volume" and index + 1 < len(argv) and not volume_seen:
                volume = validate_volume(argv[index + 1])
                volume_seen = True
                index += 2
            else:
                raise BridgeError("Invalid preview-sound arguments")
        return preview_sound(sound_path, volume)
    if command == "alert" and "--" in argv[1:]:
        delimiter = argv.index("--", 1)
        options = argv[1:delimiter]
        title_parts = argv[delimiter + 1:]
        urgency = None
        sound_path = None
        silent = False
        volume = 100
        volume_seen = False
        index = 0
        while index < len(options):
            option = options[index]
            if option == "--urgency" and index + 1 < len(options) and urgency is None:
                urgency = options[index + 1]
                index += 2
            elif option == "--sound" and index + 1 < len(options) and sound_path is None and not silent:
                sound_path = options[index + 1]
                index += 2
            elif option == "--silent" and not silent and sound_path is None:
                silent = True
                index += 1
            elif option == "--volume" and index + 1 < len(options) and not volume_seen:
                volume = validate_volume(options[index + 1])
                volume_seen = True
                index += 2
            else:
                raise BridgeError("Invalid alert arguments")
        if urgency is None or not title_parts:
            raise BridgeError("Invalid alert arguments")
        return alert(" ".join(title_parts), urgency, sound_path, silent, volume)
    if command == "show" and len(argv) == 1:
        return show(), 0
    raise BridgeError(usage)


def main(argv: list[str] | None = None) -> int:
    try:
        output, code = run(list(sys.argv[1:] if argv is None else argv))
    except Exception as error:
        output, code = {"ok": False, "error": str(error) or error.__class__.__name__}, 1
    sys.stdout.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
