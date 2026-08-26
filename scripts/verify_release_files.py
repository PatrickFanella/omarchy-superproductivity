#!/usr/bin/env python3
"""Verify that RELEASE_FILES.txt exactly describes the release package."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import sys


MANIFEST_NAME = "RELEASE_FILES.txt"
EXCLUDED_DIRECTORIES = {".git", ".pytest_cache", "__pycache__"}
EXCLUDED_FILES = {".qmllint.ini"}


def is_excluded(relative_path: PurePosixPath, *, directory: bool = False) -> bool:
    parts = relative_path.parts
    if ".blacktower" in parts:
        return True
    if any(part in EXCLUDED_DIRECTORIES for part in parts):
        return True
    if directory:
        return False
    name = relative_path.name
    return name in EXCLUDED_FILES or name.endswith(".log") or name.endswith((".pyc", ".pyo", ".pyd"))


def read_manifest(path: Path) -> list[str]:
    entries = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(entries) != len(set(entries)):
        duplicates = sorted(entry for entry in set(entries) if entries.count(entry) > 1)
        raise ValueError(f"duplicate manifest paths: {', '.join(duplicates)}")
    if entries != sorted(entries):
        raise ValueError("manifest paths are not in lexical order")
    for entry in entries:
        segments = entry.split("/")
        path_entry = PurePosixPath(entry)
        if (
            entry.startswith("/")
            or "\\" in entry
            or any(segment in {"", ".", ".."} for segment in segments)
            or path_entry.is_absolute()
            or path_entry.as_posix() != entry
        ):
            raise ValueError(f"unsafe manifest path: {entry!r}")
        if is_excluded(path_entry):
            raise ValueError(f"excluded path is listed: {entry}")
    return entries


def package_files(root: Path) -> set[str]:
    files: set[str] = set()
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in directory_names:
            path = current_path / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if is_excluded(relative, directory=True):
                continue
            if path.is_symlink():
                files.add(relative.as_posix())
            else:
                kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in file_names:
            path = current_path / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if not is_excluded(relative):
                files.add(relative.as_posix())
    return files


def verify(root: Path) -> int:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError(f"missing regular {MANIFEST_NAME}")
    entries = read_manifest(manifest_path)
    listed = set(entries)
    actual = package_files(root)

    for entry in entries:
        path = root / entry
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"listed path is not a regular file: {entry}")

    missing = sorted(listed - actual)
    unlisted = sorted(actual - listed)
    if missing or unlisted:
        details = []
        if missing:
            details.append("missing package files: " + ", ".join(missing))
        if unlisted:
            details.append("unlisted package files: " + ", ".join(unlisted))
        raise ValueError("; ".join(details))
    return len(entries)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        count = verify(root)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"release file verification failed: {error}", file=sys.stderr)
        return 1
    print(f"Verified {count} release files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
