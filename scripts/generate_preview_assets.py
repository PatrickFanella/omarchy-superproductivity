#!/usr/bin/env python3
"""Generate synthetic publication previews with ImageMagick.

The script never talks to Super Productivity or the desktop. It renders a
small, fixed SVG fixture and asks ImageMagick to rasterize and assemble it.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


WIDTH = 960
HEIGHT = 720
FORBIDDEN_TOKENS = ("rpt_", "cal_", "local-rest-api-token", "onnwee", "sputnik")
HOME_PATH = re.compile(r"(?:/(?:home|users)/|\b[a-z]:[\\/]+users[\\/]+)", re.IGNORECASE)
HOME_PATH_BYTES = re.compile(rb"(?:/(?:home|users)/|\b[a-z]:[\\/]+users[\\/]+)", re.IGNORECASE)
PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{4,}")
ID_FIELD = re.compile(
    r"\b(?:task|project|parent)[_-]?id\b\s*[\"']?\s*[:=]\s*[\"']?([a-z0-9._:-]+)",
    re.IGNORECASE,
)
METADATA_BLOCK = re.compile(r"<metadata(?:\s[^>]*)?>(.*?)</metadata\s*>", re.IGNORECASE | re.DOTALL)
METADATA_KEYS = frozenset({
    "fixture", "taskId", "projectId", "parentId", "title", "projectTitle",
    "dueWithTime", "isDone",
})
PLAN_TITLE = "Plan launch"
DRAFT_TITLE = "Draft release notes"
REVIEW_TITLE = "Review checklist"
NEXT_TITLE = "Prepare launch brief"
WORK_PROJECT = "Work"
PERSONAL_PROJECT = "Personal"
TASK_TITLES = frozenset({PLAN_TITLE, DRAFT_TITLE, REVIEW_TITLE, NEXT_TITLE})
PROJECTS = frozenset({WORK_PROJECT, PERSONAL_PROJECT})
FRAME_DELAYS = (120, 120, 110, 120, 100, 120, 130, 150)  # centiseconds; 9.7 s total
MAX_GIF_DURATION_CS = 1500

POPUP_X = 270
POPUP_Y = 50
POPUP_W = 420
POPUP_H = 620
CONTENT_X = 288
CONTENT_Y = 68
CONTENT_W = 384
VIEW_H = 584

BG = "#090b10"
PANEL = "#11151d"
PANEL_2 = "#161b25"
TEXT = "#edf1f7"
DIM = "#929aa8"
FAINT = "#252c38"
ACCENT = "#8bd5ca"
URGENT = "#f06568"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def rect(x: int, y: int, w: int, h: int, fill: str, *, radius: int = 8,
         stroke: str = "none", stroke_width: int = 0, opacity: float = 1) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'opacity="{opacity}"/>'
    )


def text(x: int, y: int, value: object, *, size: int = 14, fill: str = TEXT,
         weight: int = 400, anchor: str = "start", spacing: float = 0,
         family: str = "JetBrains Mono, monospace") -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'letter-spacing="{spacing}">{esc(value)}</text>'
    )


def button(x: int, y: int, w: int, label: str, *, accent: bool = False,
           urgent: bool = False, muted: bool = False) -> str:
    border = URGENT if urgent else (ACCENT if accent else "#404957")
    fg = DIM if muted else (URGENT if urgent else (ACCENT if accent else TEXT))
    fill = "#20171c" if urgent else ("#132321" if accent else "#171c25")
    opacity = 0.55 if muted else 1
    return "".join((
        rect(x, y, w, 32, fill, radius=7, stroke=border, stroke_width=1, opacity=opacity),
        text(x + w // 2, y + 21, label, size=11, fill=fg, weight=650,
             anchor="middle"),
    ))


def metric(x: int, y: int, w: int, label: str, value: str, *, warning: bool = False,
           emphasis: bool = False) -> str:
    fill = "#27171d" if warning else ("#142321" if emphasis else PANEL_2)
    border = URGENT if warning else ("#416a65" if emphasis else FAINT)
    value_color = URGENT if warning else (ACCENT if emphasis else TEXT)
    return "".join((
        rect(x, y, w, 48, fill, radius=7, stroke=border, stroke_width=1),
        text(x + w // 2, y + 18, label, size=8, fill=DIM, weight=700, anchor="middle", spacing=1),
        text(x + w // 2, y + 39, value, size=14, fill=value_color, weight=700, anchor="middle"),
    ))


def task_row(y: int, title: str, project: str, clock: str, *, child: bool,
             current: bool = False, parent: bool = False) -> str:
    x = CONTENT_X + (18 if child else 0)
    w = CONTENT_W - (18 if child else 0)
    fill = "#142522" if current else PANEL
    stroke = ACCENT if current else "none"
    pieces = [rect(x, y, w, 58, fill, radius=7, stroke=stroke,
                   stroke_width=1 if current else 0)]
    tx = x + 10
    if parent:
        pieces.append(text(x + 10, y + 34, "▾", size=13, fill=DIM))
        tx = x + 31
    pieces.extend((
        text(tx, y + 24, title, size=11, fill=ACCENT if current else TEXT,
             weight=700 if current or parent else 500),
        text(tx, y + 43, ("CURRENT · " if current else "") + clock + " · " + project,
             size=8, fill=URGENT if "over" in clock else (ACCENT if current else DIM)),
    ))
    if not parent:
        pieces.append(button(x + w - 134, y + 13, 54, "Active" if current else "Start",
                             accent=current, muted=current))
        pieces.append(button(x + w - 74, y + 13, 66, "Complete"))
    return "".join(pieces)


def toggle(x: int, y: int, enabled: bool) -> str:
    track = "#25423d" if enabled else "#252c38"
    knob_x = x + 27 if enabled else x + 9
    return "".join((
        rect(x, y, 44, 24, track, radius=12, stroke=ACCENT if enabled else "#404957", stroke_width=1),
        f'<circle cx="{knob_x}" cy="{y + 12}" r="8" fill="{ACCENT if enabled else DIM}"/>',
    ))


def checkbox(x: int, y: int, checked: bool, label: str = "Add & switch",
             focused: bool = False) -> str:
    border = ACCENT if focused or checked else "#404957"
    pieces = [rect(x, y, 110, 26, "#142321" if focused else "transparent", radius=4)]
    pieces.append(rect(x + 7, y + 7, 12, 12, ACCENT if checked else "transparent",
                       radius=2, stroke=border, stroke_width=1))
    if checked:
        pieces.append(text(x + 13, y + 17, "✓", size=9, fill=BG, weight=800,
                           anchor="middle", family="DejaVu Sans, sans-serif"))
    pieces.append(text(x + 25, y + 17, label, size=9,
                       fill=ACCENT if checked else TEXT, weight=650))
    if focused:
        pieces.append(rect(x, y + 24, 110, 2, ACCENT, radius=1))
    return "".join(pieces)


def settings_frame_svg(frame: int, title_value: str, detail: str) -> str:
    """Return a truthful settings viewport scrolled to the alert controls."""
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<metadata>{"fixture":"synthetic","taskId":"demo-current","projectId":"demo-work","parentId":"demo-plan"}</metadata>',
        '<defs>',
        '<filter id="demo-shadow" x="-20%" y="-20%" width="140%" height="150%" filterUnits="objectBoundingBox"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#000000" flood-opacity="0.62"/></filter>',
        '<pattern id="demo-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.7" fill="#ffffff" opacity="0.035"/></pattern>',
        f'<clipPath id="settings-viewport"><rect x="{CONTENT_X}" y="{CONTENT_Y}" width="{CONTENT_W}" height="{VIEW_H}" rx="7"/></clipPath>',
        '</defs>',
        rect(0, 0, WIDTH, HEIGHT, BG, radius=0),
        '<path d="M0 530 L280 330 L430 430 L700 130 L960 300 L960 720 L0 720 Z" fill="#0d1318" opacity="0.75"/>',
        rect(0, 0, WIDTH, HEIGHT, 'url(#demo-grid)', radius=0),
        rect(0, 0, WIDTH, 32, "#07090d", radius=0),
        text(20, 21, "MON  09:41", size=9, fill=DIM, weight=650, spacing=0.7),
        text(480, 21, "●  " + title_value + "  " + detail, size=9, fill=URGENT, weight=650, anchor="middle"),
        text(940, 21, "VOL  NET  87%", size=9, fill=DIM, weight=650, anchor="end"),
        '<g filter="url(#demo-shadow)">',
        rect(POPUP_X, POPUP_Y, POPUP_W, POPUP_H, PANEL, radius=13, stroke="#2d3542", stroke_width=1),
        '</g>',
        rect(POPUP_X + 1, POPUP_Y + 1, POPUP_W - 2, POPUP_H - 2, 'url(#demo-grid)', radius=12),
        '<g clip-path="url(#settings-viewport)">',
        text(CONTENT_X, 86, "GENERAL", size=9, fill=TEXT, weight=800, spacing=1),
        text(CONTENT_X + CONTENT_W, 86, "SETTINGS · SCROLLED", size=8, fill=DIM,
             weight=650, anchor="end", spacing=0.5),
        rect(CONTENT_X, 98, CONTENT_W, 56, PANEL_2, radius=7),
        text(CONTENT_X + 10, 122, "Start next after Complete", size=11, fill=TEXT, weight=550),
        text(CONTENT_X + 10, 140, "Start the next runnable task after panel completion", size=8, fill=DIM),
        toggle(CONTENT_X + CONTENT_W - 54, 114, True),
        rect(CONTENT_X, 166, CONTENT_W, 56, PANEL_2, radius=7, stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + 10, 190, "Auto-next schedule window", size=11, fill=TEXT, weight=650),
        text(CONTENT_X + 10, 208, "Only scheduled tasks within ±window · 1–1440 minutes", size=8, fill=DIM),
        rect(CONTENT_X + CONTENT_W - 76, 178, 68, 32, "#0e1219", radius=7,
             stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + CONTENT_W - 42, 199, "30", size=10, fill=TEXT,
             weight=650, anchor="middle"),
        rect(CONTENT_X, 234, CONTENT_W, 78, PANEL_2, radius=7, stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + 10, 259, "Alert volume", size=11, fill=TEXT, weight=650),
        text(CONTENT_X + 10, 278, "Countdown and scheduled-start alerts and previews", size=8, fill=DIM),
        rect(CONTENT_X + CONTENT_W - 82, 247, 74, 32, "#0e1219", radius=7,
             stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + CONTENT_W - 45, 268, "100", size=10, fill=TEXT,
             weight=650, anchor="middle"),
        text(CONTENT_X + CONTENT_W - 45, 299, "0 muted  ·  100%", size=8, fill=DIM,
             anchor="middle"),
        rect(CONTENT_X, 324, CONTENT_W, 82, PANEL_2, radius=7),
        text(CONTENT_X + 10, 348, "Alert sound path", size=11, fill=TEXT, weight=550),
        text(CONTENT_X + 10, 366, "Custom sound for countdown expiry and scheduled start", size=8, fill=DIM),
        rect(CONTENT_X + 10, 376, CONTENT_W - 20, 22, "#0e1219", radius=6,
             stroke="#3c4552", stroke_width=1),
        text(CONTENT_X + 20, 391, "Bundled sound", size=8, fill="#707987"),
        rect(CONTENT_X, 418, CONTENT_W, 66, PANEL_2, radius=7),
        text(CONTENT_X + 10, 442, "Notification urgency", size=11, fill=TEXT, weight=550),
        text(CONTENT_X + 10, 460, "Countdown expiry and scheduled start", size=8, fill=DIM),
        button(CONTENT_X + CONTENT_W - 84, 435, 76, "Critical", accent=True),
        button(CONTENT_X, 498, 140, "Test notification"),
        button(CONTENT_X + 148, 498, 128, "Preview sound", accent=True),
        text(CONTENT_X, 553, "Volume saves immediately after editing.",
             size=8, fill=DIM),
        '</g>',
        rect(POPUP_X + POPUP_W - 7, CONTENT_Y, 2, VIEW_H, "#313946", radius=1),
        rect(POPUP_X + POPUP_W - 7, CONTENT_Y + 176, 2, 292, ACCENT, radius=1, opacity=0.7),
        text(POPUP_X - 12, POPUP_Y + POPUP_H - 6, f"0{frame}", size=9, fill="#596170", anchor="end"),
        '</svg>',
    ]
    return "".join(p)


def idle_next_frame_svg(frame: int) -> str:
    """Return an idle viewport with one consistent synthetic next start."""
    synthetic_now_ms = 1787564460000  # Monday 09:41 UTC
    next_task = {
        "taskId": "demo-next",
        "title": NEXT_TITLE,
        "projectId": "demo-personal",
        "projectTitle": PERSONAL_PROJECT,
        "dueWithTime": 1787566500000,  # Monday 10:15 UTC
        "isDone": False,
    }
    if next_task["isDone"] or "parentId" in next_task or next_task["dueWithTime"] <= synthetic_now_ms:
        raise ValueError("idle next fixture must be eligible for Model.nextScheduledTask")
    start_time = "10:15"
    next_title = next_task["title"]
    project_title = next_task["projectTitle"]
    metadata = json.dumps({"fixture": "synthetic", **next_task}, separators=(",", ":"))
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<metadata>{esc(metadata)}</metadata>',
        '<defs>',
        '<filter id="demo-shadow" x="-20%" y="-20%" width="140%" height="150%" filterUnits="objectBoundingBox"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#000000" flood-opacity="0.62"/></filter>',
        '<pattern id="demo-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.7" fill="#ffffff" opacity="0.035"/></pattern>',
        f'<clipPath id="idle-viewport"><rect x="{CONTENT_X}" y="{CONTENT_Y}" width="{CONTENT_W}" height="{VIEW_H}" rx="7"/></clipPath>',
        '</defs>',
        rect(0, 0, WIDTH, HEIGHT, BG, radius=0),
        '<path d="M0 530 L280 330 L430 430 L700 130 L960 300 L960 720 L0 720 Z" fill="#0d1318" opacity="0.75"/>',
        rect(0, 0, WIDTH, HEIGHT, 'url(#demo-grid)', radius=0),
        rect(0, 0, WIDTH, 32, "#07090d", radius=0),
        text(20, 21, "MON  09:41", size=9, fill=DIM, weight=650, spacing=0.7),
        text(480, 21, "◷  Next " + start_time + " · " + next_title, size=9,
             fill=TEXT, weight=650, anchor="middle", family="DejaVu Sans, sans-serif"),
        text(940, 21, "VOL  NET  87%", size=9, fill=DIM, weight=650, anchor="end"),
        '<g filter="url(#demo-shadow)">',
        rect(POPUP_X, POPUP_Y, POPUP_W, POPUP_H, PANEL, radius=13, stroke="#2d3542", stroke_width=1),
        '</g>',
        rect(POPUP_X + 1, POPUP_Y + 1, POPUP_W - 2, POPUP_H - 2, 'url(#demo-grid)', radius=12),
        '<g clip-path="url(#idle-viewport)">',
        rect(CONTENT_X, 68, 37, 37, "transparent", radius=19, stroke=ACCENT, stroke_width=2),
        '<path d="M306.5 77 L306.5 86.5 L314 91" fill="none" stroke="#8bd5ca" stroke-width="2" stroke-linecap="round"/>',
        text(CONTENT_X + 51, 79, "NEXT SCHEDULED", size=8, fill=TEXT, weight=800, spacing=1.3),
        text(CONTENT_X + 51, 99, next_title, size=16, fill=TEXT, weight=750),
        text(CONTENT_X + CONTENT_W - 40, 83, "↻", size=15, fill=DIM, anchor="middle"),
        text(CONTENT_X + CONTENT_W - 20, 84, "⚙", size=15, fill=DIM,
             anchor="middle", family="DejaVu Sans, sans-serif"),
        text(CONTENT_X + CONTENT_W, 83, "↗", size=15, fill=DIM, anchor="end"),
        text(CONTENT_X + CONTENT_W, 123, "Starts at " + start_time, size=11,
             fill=TEXT, weight=700, anchor="end"),
        text(CONTENT_X, 147, "Next at " + start_time + ": " + next_title + ". Start it from Today when ready.",
             size=9, fill=DIM),
        rect(CONTENT_X, 163, CONTENT_W, 1, FAINT, radius=0),
        text(CONTENT_X + 3, 192, "▾  QUICK ADD", size=9, fill=TEXT, weight=800, spacing=1),
        rect(CONTENT_X, 206, CONTENT_W - 45, 38, "#0e1219", radius=7,
             stroke="#343c49", stroke_width=1),
        text(CONTENT_X + 12, 230, "Write report 30m +Work #focus @tomorrow", size=9, fill="#707987"),
        rect(CONTENT_X + CONTENT_W - 38, 206, 38, 38, "#132321", radius=7,
             stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + CONTENT_W - 19, 232, "+", size=18, fill=ACCENT, weight=650, anchor="middle"),
        text(CONTENT_X, 263, "+project, @schedule, #tag", size=8, fill=DIM),
        checkbox(CONTENT_X + CONTENT_W - 110, 250, False),
        rect(CONTENT_X, 290, CONTENT_W, 1, FAINT, radius=0),
        text(CONTENT_X + 3, 319, "▾  TODAY", size=9, fill=TEXT, weight=800, spacing=1),
        text(CONTENT_X + CONTENT_W - 3, 319, "3", size=9, fill=DIM, anchor="end"),
        rect(CONTENT_X, 332, CONTENT_W, 38, "#0e1219", radius=7,
              stroke="#343c49", stroke_width=1),
        text(CONTENT_X + 12, 356, "Search title, project, or parent", size=10, fill="#707987"),
        text(CONTENT_X + CONTENT_W - 12, 356, "⌕", size=15, fill=DIM, anchor="end"),
        task_row(377, next_title, project_title + " · Mon 10:15 AM", "20:00 left", child=False),
        task_row(442, PLAN_TITLE, WORK_PROJECT, "18:24 left", child=False, parent=True),
        task_row(507, DRAFT_TITLE, WORK_PROJECT, "25:00 left", child=True),
        '</g>',
        text(POPUP_X - 12, POPUP_Y + POPUP_H - 6, f"0{frame}", size=9, fill="#596170", anchor="end"),
        '</svg>',
    ]
    return "".join(p)


def frame_svg(frame: int) -> str:
    """Return a complete SVG showing one truthful viewport state."""
    if frame == 8:
        return idle_next_frame_svg(frame)
    state = {
        1: (PLAN_TITLE, "18:24 left", "", False, "parent", 0, "idle", ""),
        2: (PLAN_TITLE, "18:22 left", "release", False, "parent", 72, "idle", ""),
        3: (DRAFT_TITLE, "23:20 left", "", False, "draft", 152, "idle", ""),
        4: (DRAFT_TITLE, "+04:12", "", True, "draft", 0, "idle", ""),
        5: (DRAFT_TITLE, "+04:14", "", True, "draft", 178, "running",
            f"{REVIEW_TITLE} 20m +{PERSONAL_PROJECT}"),
        6: (DRAFT_TITLE, "+04:16", "", True, "draft", 178, "done", ""),
        7: (DRAFT_TITLE, "14:58 left", "", False, "draft", 154, "switch",
            f"{REVIEW_TITLE} 20m +{PERSONAL_PROJECT}"),
    }[frame]
    title_value, detail, search, overtime, current, scroll, add_state, quick = state
    if frame == 6:
        return settings_frame_svg(frame, title_value, detail)
    current_clock = f"{detail} over" if overtime else detail
    fg = URGENT if overtime else TEXT
    progress = 1 if overtime else (0.62 if frame < 3 else 0.38)
    feedback_height = 44 if add_state in {"running", "done"} else 0
    content_height = (640 if search else 705) + feedback_height + 58
    thumb_h = int(VIEW_H * VIEW_H / content_height)
    thumb_y = CONTENT_Y + int(scroll * (VIEW_H - thumb_h) / (content_height - VIEW_H))

    def sy(value: int) -> int:
        return CONTENT_Y + value - scroll

    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<metadata>{"fixture":"synthetic","taskId":"demo-current","projectId":"demo-work","parentId":"demo-plan"}</metadata>',
        '<defs>',
        '<filter id="demo-shadow" x="-20%" y="-20%" width="140%" height="150%" filterUnits="objectBoundingBox"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#000000" flood-opacity="0.62"/></filter>',
        '<pattern id="demo-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="0.7" fill="#ffffff" opacity="0.035"/></pattern>',
        f'<clipPath id="demo-viewport"><rect x="{CONTENT_X}" y="{CONTENT_Y}" width="{CONTENT_W}" height="{VIEW_H}" rx="7"/></clipPath>',
        '</defs>',
        rect(0, 0, WIDTH, HEIGHT, BG, radius=0),
        '<path d="M0 530 L280 330 L430 430 L700 130 L960 300 L960 720 L0 720 Z" fill="#0d1318" opacity="0.75"/>',
        rect(0, 0, WIDTH, HEIGHT, 'url(#demo-grid)', radius=0),
        rect(0, 0, WIDTH, 32, "#07090d", radius=0),
        text(20, 21, "MON  09:41", size=9, fill=DIM, weight=650, spacing=0.7),
        text(480, 21, "●  " + title_value + "  " + detail, size=9,
             fill=URGENT if overtime else ACCENT, weight=650, anchor="middle"),
        text(940, 21, "VOL  NET  87%", size=9, fill=DIM, weight=650, anchor="end"),
        '<g filter="url(#demo-shadow)">',
        rect(POPUP_X, POPUP_Y, POPUP_W, POPUP_H, PANEL, radius=13, stroke="#2d3542", stroke_width=1),
        '</g>',
        rect(POPUP_X + 1, POPUP_Y + 1, POPUP_W - 2, POPUP_H - 2, 'url(#demo-grid)', radius=12),
        '<g clip-path="url(#demo-viewport)">',
        rect(CONTENT_X, sy(0), 37, 37, "transparent", radius=19,
             stroke=URGENT if overtime else ACCENT, stroke_width=2),
    ]
    if overtime:
        p.append(text(CONTENT_X + 18, sy(25), "!", size=19, fill=URGENT, weight=800, anchor="middle"))
    else:
        p.append(rect(CONTENT_X + 13, sy(13), 11, 11, ACCENT, radius=6))
    p.extend((
        text(CONTENT_X + 51, sy(11), "OVERTIME" if overtime else "CURRENT FOCUS", size=8, fill=fg, weight=800, spacing=1.3),
        text(CONTENT_X + 51, sy(31), title_value, size=16, fill=fg, weight=750),
        text(CONTENT_X + CONTENT_W - 40, sy(15), "↻", size=15, fill=DIM, anchor="middle"),
        text(CONTENT_X + CONTENT_W - 20, sy(16), "⚙", size=15, fill=ACCENT if frame == 5 else DIM,
             anchor="middle", family="DejaVu Sans, sans-serif"),
        text(CONTENT_X + CONTENT_W, sy(15), "↗", size=15, fill=DIM, anchor="end"),
        text(CONTENT_X, sy(61), WORK_PROJECT + " · Today", size=9, fill=DIM),
        text(CONTENT_X + CONTENT_W, sy(61), detail, size=11, fill=fg, weight=700, anchor="end"),
        rect(CONTENT_X, sy(73), CONTENT_W, 4, "#252b35", radius=2),
        rect(CONTENT_X, sy(73), int(CONTENT_W * progress), 4, URGENT if overtime else ACCENT, radius=2),
        metric(CONTENT_X, sy(89), 122, "OVERTIME" if overtime else "REMAINING", detail,
               warning=overtime, emphasis=not overtime),
        metric(CONTENT_X + 131, sy(89), 122, "ESTIMATE", "20:00" if overtime else ("25:00" if frame >= 3 else "30:00")),
        metric(CONTENT_X + 262, sy(89), 122, "SPENT", "24:12" if overtime else ("01:40" if frame >= 3 else "11:36")),
        button(CONTENT_X, sy(149), 76, "Stop", urgent=overtime),
        "" if current == "parent" else button(CONTENT_X + 83, sy(149), 91, "Complete"),
        button(CONTENT_X + (83 if current == "parent" else 181), sy(149), 71, "+5m", accent=frame == 3),
        button(CONTENT_X + (161 if current == "parent" else 259), sy(149), 75, "+15m"),
        rect(CONTENT_X, sy(189), 281, 32, "#121720", radius=7, stroke="#3c4552", stroke_width=1),
        text(CONTENT_X + 12, sy(210), "Minutes (1–1440)", size=9, fill="#6f7886"),
        button(CONTENT_X + 288, sy(189), 96, "Extend"),
        rect(CONTENT_X, sy(233), CONTENT_W, 1, FAINT, radius=0),
        text(CONTENT_X + 3, sy(262), "▾  QUICK ADD", size=9, fill=TEXT, weight=800, spacing=1),
        rect(CONTENT_X, sy(276), CONTENT_W - 45, 38, "#0e1219", radius=7,
             stroke=ACCENT if quick else "#343c49", stroke_width=1),
        text(CONTENT_X + 12, sy(300), quick or "Write report 30m +Work #focus @tomorrow", size=9,
             fill=TEXT if quick else "#707987"),
        rect(CONTENT_X + CONTENT_W - 38, sy(276), 38, 38, "#132321", radius=7,
             stroke=ACCENT, stroke_width=1),
        text(CONTENT_X + CONTENT_W - 19, sy(302), "…" if add_state == "running" else "+",
             size=18, fill=ACCENT, weight=650, anchor="middle"),
        text(CONTENT_X, sy(329), "+project, @schedule, #tag", size=8, fill=DIM),
        checkbox(CONTENT_X + CONTENT_W - 110, sy(311), add_state == "switch",
                 focused=frame == 7),
    ))
    if add_state in {"running", "done"}:
        feedback = "Creating task once" if add_state == "running" else "Task created"
        feedback_fill = "#142321" if add_state == "done" else "#171c25"
        feedback_border = "#416a65" if add_state == "done" else "#404957"
        p.extend((
            rect(CONTENT_X, sy(371), CONTENT_W, 36, feedback_fill, radius=7,
                 stroke=feedback_border, stroke_width=1),
            text(CONTENT_X + 11, sy(394), feedback, size=9,
                 fill=ACCENT if add_state == "done" else DIM, weight=650),
        ))
    today_y = 383 + feedback_height
    p.extend((
        rect(CONTENT_X, sy(today_y), CONTENT_W, 1, FAINT, radius=0),
        text(CONTENT_X + 3, sy(today_y + 29), "▾  TODAY", size=9, fill=TEXT, weight=800, spacing=1),
        text(CONTENT_X + CONTENT_W - 3, sy(today_y + 29), "2" if search else "3", size=9, fill=DIM, anchor="end"),
        rect(CONTENT_X, sy(today_y + 42), CONTENT_W, 38, "#0e1219", radius=7,
             stroke=ACCENT if search else "#343c49", stroke_width=1),
        text(CONTENT_X + 12, sy(today_y + 66), search or "Search title, project, or parent", size=10,
             fill=TEXT if search else "#707987"),
        text(CONTENT_X + CONTENT_W - 12, sy(today_y + 66), "⌕", size=15,
             fill=ACCENT if search else DIM, anchor="end"),
    ))
    if search:
        p.extend((
            task_row(sy(today_y + 87), PLAN_TITLE, WORK_PROJECT,
                     current_clock if current == "parent" else "18:22 left", child=False,
                     current=current == "parent", parent=True),
            task_row(sy(today_y + 152), DRAFT_TITLE, WORK_PROJECT, "25:00 left", child=True),
        ))
    else:
        p.extend((
            task_row(sy(today_y + 87), PLAN_TITLE, WORK_PROJECT,
                     current_clock if current == "parent" else "18:24 left", child=False,
                     current=current == "parent", parent=True),
            task_row(sy(today_y + 152), DRAFT_TITLE, WORK_PROJECT,
                     current_clock if current == "draft" else "25:00 left",
                     child=True, current=current == "draft"),
            task_row(sy(today_y + 217), REVIEW_TITLE, PERSONAL_PROJECT, "20:00 left", child=True),
        ))
    p.extend((
        '</g>',
        rect(POPUP_X + POPUP_W - 7, CONTENT_Y, 2, VIEW_H, "#313946", radius=1),
        rect(POPUP_X + POPUP_W - 7, thumb_y, 2, thumb_h, ACCENT, radius=1, opacity=0.7),
    ))
    if scroll > 72:
        p.extend((
            rect(CONTENT_X + 4, CONTENT_Y + VIEW_H - 42, 92, 36,
                  PANEL, radius=8, stroke=ACCENT, stroke_width=2 if frame == 3 else 1),
            text(CONTENT_X + 50, CONTENT_Y + VIEW_H - 19, "↑ Go top",
                 size=9, fill=TEXT, weight=700, anchor="middle"),
        ))
    p.extend((
        text(POPUP_X - 12, POPUP_Y + POPUP_H - 6, f"0{frame}", size=9, fill="#596170", anchor="end"),
        '</svg>',
    ))
    return "".join(p)


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, check=True, text=True, capture_output=True, cwd=cwd)
    return result.stdout.strip()


def scan_sources(source_dir: Path) -> None:
    def validate_json(value: object, path: Path) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                folded = key.casefold()
                if folded.endswith("id") and (not isinstance(child, str) or not child.startswith("demo-")):
                    raise ValueError(f"non-demo ID {child!r} for {key!r} in {path}")
                if folded in {"title", "tasktitle"} and (
                    not isinstance(child, str) or child not in TASK_TITLES
                ):
                    raise ValueError(f"non-synthetic title {child!r} in {path}")
                if folded in {"project", "projectname", "projecttitle"} and (
                    not isinstance(child, str) or child not in PROJECTS
                ):
                    raise ValueError(f"non-synthetic project {child!r} in {path}")
                validate_json(child, path)
        elif isinstance(value, list):
            for child in value:
                validate_json(child, path)

    decoder = json.JSONDecoder()
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = content.lower()
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                raise ValueError(f"forbidden token {token!r} in {path}")
        if HOME_PATH.search(content):
            raise ValueError(f"home path in {path}")

        if path.suffix.casefold() == ".svg":
            blocks = METADATA_BLOCK.findall(content)
            if len(blocks) != len(re.findall(r"<metadata\b", content, re.IGNORECASE)):
                raise ValueError(f"unparseable SVG metadata block in {path}")
            for block in blocks:
                metadata = json.loads(html.unescape(block))
                if not isinstance(metadata, dict):
                    raise ValueError(f"SVG metadata must be a JSON object in {path}")
                unknown = metadata.keys() - METADATA_KEYS
                if unknown:
                    raise ValueError(f"unsupported SVG metadata keys {sorted(unknown)!r} in {path}")
                if metadata.get("fixture") != "synthetic":
                    raise ValueError(f"non-synthetic SVG fixture in {path}")
                validate_json(metadata, path)

        for offset, character in enumerate(content):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(content, offset)
            except json.JSONDecodeError:
                continue
            validate_json(value, path)


def verify_dimensions(path: Path) -> None:
    dimensions = run(["magick", "identify", "-format", "%Wx%H\\n", str(path)])
    frames = dimensions.split()
    if not frames or any(value != f"{WIDTH}x{HEIGHT}" for value in frames):
        raise ValueError(f"unexpected dimensions for {path}: {dimensions}")


def scan_final_text(content: str, path: Path, source: str) -> None:
    lowered = content.casefold()
    for token in FORBIDDEN_TOKENS:
        if token in lowered:
            raise ValueError(f"forbidden token {token!r} in {source} for {path}")
    if HOME_PATH.search(content):
        raise ValueError(f"home path in {source} for {path}")
    for match in ID_FIELD.finditer(content):
        identifier = match.group(1)
        if not identifier.casefold().startswith("demo-"):
            raise ValueError(f"non-demo ID {identifier!r} in {source} for {path}")


def verify_final_asset(path: Path) -> None:
    payload = path.read_bytes()
    lowered = payload.lower()
    for token in FORBIDDEN_TOKENS:
        if token.encode("utf-8") in lowered:
            raise ValueError(f"forbidden token {token!r} in binary bytes for {path}")
    if HOME_PATH_BYTES.search(payload):
        raise ValueError(f"home path in binary bytes for {path}")
    printable = "\n".join(
        match.group().decode("ascii") for match in PRINTABLE_RUN.finditer(payload)
    )
    scan_final_text(printable, path, "binary text")

    verbose = run(["magick", "identify", "-verbose", path.name], cwd=path.parent)
    scan_final_text(verbose, path, "ImageMagick identify output")
    if re.search(r"^\s*Profiles:\s*$", verbose, re.MULTILINE | re.IGNORECASE):
        raise ValueError(f"metadata profile remains in {path}")


def verify_gif_timing(path: Path) -> int:
    output = run(["magick", "identify", "-format", "%n %T\\n", path.name], cwd=path.parent)
    rows = output.splitlines()
    expected_count = len(FRAME_DELAYS)
    if len(rows) != expected_count:
        raise ValueError(f"unexpected GIF frame count for {path}: {len(rows)}")
    parsed = [tuple(int(value) for value in row.split()) for row in rows]
    if any(count != expected_count for count, _ in parsed):
        raise ValueError(f"inconsistent GIF frame count for {path}: {output}")
    delays = tuple(delay for _, delay in parsed)
    if delays != FRAME_DELAYS:
        raise ValueError(f"unexpected GIF delays for {path}: {delays}")
    duration_cs = sum(delays)
    if duration_cs > MAX_GIF_DURATION_CS:
        raise ValueError(f"GIF duration exceeds 15 seconds: {duration_cs / 100:.2f}s")
    return duration_cs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="plugin root; defaults to the parent of scripts/")
    args = parser.parse_args()
    root = args.root.resolve()
    source_dir = root / "assets" / "preview-src"
    screenshot_dir = root / "assets" / "screenshots"
    gif_path = root / "assets" / "demo.gif"
    marketplace_preview = root / "preview.png"
    source_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("magick") is None:
        raise RuntimeError("ImageMagick 'magick' CLI is required")

    svg_paths: list[Path] = []
    png_frames: list[Path] = []
    for index in range(1, 9):
        svg_path = source_dir / f"frame-{index:02d}.svg"
        png_path = source_dir / f"frame-{index:02d}.png"
        svg_path.write_text(frame_svg(index), encoding="utf-8")
        run(["magick", "-background", "none", str(svg_path), str(png_path)])
        svg_paths.append(svg_path)
        png_frames.append(png_path)

    scan_sources(source_dir)
    run(["magick", str(png_frames[3]), "-strip", str(screenshot_dir / "panel.png")])
    run(["magick", str(png_frames[3]), "-strip", str(marketplace_preview)])
    run(["magick", str(png_frames[7]), "-strip", str(screenshot_dir / "panel-reduced-motion.png")])

    gif_command = ["magick"]
    for delay, path in zip(FRAME_DELAYS, png_frames):
        gif_command.extend(["-delay", str(delay), str(path)])
    gif_command.extend([
        "-loop", "0", "-layers", "Optimize", "-colors", "128", "-dither", "FloydSteinberg",
        "-strip", str(gif_path),
    ])
    run(gif_command)

    final_assets = (
        marketplace_preview,
        screenshot_dir / "panel.png",
        screenshot_dir / "panel-reduced-motion.png",
        gif_path,
    )
    for generated in final_assets:
        verify_dimensions(generated)
        verify_final_asset(generated)
    duration_cs = verify_gif_timing(gif_path)
    for png_path in png_frames:
        png_path.unlink()
    duration = duration_cs / 100
    print(f"generated {len(svg_paths)} SVG frames; GIF duration {duration:.2f}s")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as error:
        print(f"preview generation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
