#!/usr/bin/env python3
"""Warm a bounded, manifest-pinned game startup working set."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import time


MAX_FILES = 128
MAX_TOTAL_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(f"prefetch-game-files: {message}")


def load_plan(root: Path, manifest: Path) -> list[tuple[Path, int]]:
    if not root.is_dir():
        fail(f"game root is unavailable: {root}")
    root = root.resolve(strict=True)
    try:
        metadata = manifest.lstat()
    except OSError as error:
        fail(f"manifest is unavailable: {error}")
    if not stat.S_ISREG(metadata.st_mode) or manifest.is_symlink():
        fail(f"manifest is unsafe: {manifest}")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"manifest is unavailable: {error}")
    if not isinstance(document, dict):
        fail("manifest schema is unsupported")
    entries = document.get("files")
    if document.get("schema") != 1 or not isinstance(entries, list):
        fail("manifest schema is unsupported")
    if not 1 <= len(entries) <= MAX_FILES:
        fail(f"manifest must contain 1 through {MAX_FILES} files")
    manifest_limit = document.get("maximum_total_bytes")
    if (
        type(manifest_limit) is not int
        or not 1 <= manifest_limit <= MAX_TOTAL_BYTES
    ):
        fail("manifest total-byte limit is invalid")

    plan = []
    names = set()
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            fail("manifest file entry is invalid")
        name = entry.get("path")
        expected_size = entry.get("expected_size")
        read_bytes = entry.get("read_bytes")
        if not isinstance(name, str) or "\\" in name:
            fail("manifest path is invalid")
        relative = PurePosixPath(name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            fail(f"manifest path escapes the game root: {name}")
        if name in names:
            fail(f"manifest path is duplicated: {name}")
        names.add(name)
        if type(expected_size) is not int or expected_size <= 0:
            fail(f"expected size is invalid: {name}")
        if type(read_bytes) is not int or not 1 <= read_bytes <= expected_size:
            fail(f"read size is invalid: {name}")
        path = root.joinpath(*relative.parts)
        try:
            resolved = path.resolve(strict=True)
            file_metadata = path.lstat()
        except OSError as error:
            fail(f"startup file is unavailable: {name}: {error}")
        try:
            relative_resolved = resolved.relative_to(root)
        except ValueError:
            fail(f"manifest path escapes the game root: {name}")
        current = root
        for component in relative_resolved.parts[:-1]:
            current /= component
            parent_metadata = current.lstat()
            if not stat.S_ISDIR(parent_metadata.st_mode) or current.is_symlink():
                fail(f"startup file parent is unsafe: {name}")
        if (
            not stat.S_ISREG(file_metadata.st_mode)
            or path.is_symlink()
            or file_metadata.st_size != expected_size
        ):
            fail(f"startup file failed identity validation: {name}")
        total += read_bytes
        if total > manifest_limit:
            fail("manifest exceeds its total-byte limit")
        plan.append((path, read_bytes))
    return plan


def prefetch(plan: list[tuple[Path, int]]) -> dict:
    started = time.monotonic()
    total = 0
    advised = 0
    for path, length in plan:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if hasattr(os, "posix_fadvise"):
                try:
                    os.posix_fadvise(
                        descriptor, 0, length, os.POSIX_FADV_WILLNEED
                    )
                    advised += 1
                except OSError:
                    pass
            remaining = length
            while remaining:
                chunk = os.read(descriptor, min(CHUNK_BYTES, remaining))
                if not chunk:
                    fail(f"startup file ended early: {path.name}")
                remaining -= len(chunk)
                total += len(chunk)
        finally:
            os.close(descriptor)
    return {
        "schema": 1,
        "status": "complete",
        "files": len(plan),
        "bytes": total,
        "advised_files": advised,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    plan = load_plan(arguments.root, arguments.manifest)
    if arguments.check:
        result = {
            "schema": 1,
            "status": "validated",
            "files": len(plan),
            "bytes": sum(length for _, length in plan),
        }
    else:
        result = prefetch(plan)
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
