#!/usr/bin/env python3
"""Safely map one Steam AppID to a verified compatibility tool."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


MAX_CONFIG_BYTES = 16 * 1024 * 1024
APPID_PATTERN = re.compile(r"[1-9][0-9]{0,9}")
TOOL_PATTERN = re.compile(r"[A-Za-z0-9_.()-]+")
KEY_LINE = re.compile(rb'^(?P<indent>[ \t]*)"(?P<key>[^"\\]+)"[ \t]*(?:\r?\n)?$')
RUNNING_COMMS = {"steam", "steamwebhelper", "wineserver"}
CONFIG_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")


class MappingError(RuntimeError):
    pass


def default_config() -> Path:
    base = Path(os.environ.get("STEAM_ARM64_BASE", Path.home() / "steam-arm64"))
    return base / "client/config/config.vdf"


def active_processes(proc_root: Path) -> list[tuple[int, str]]:
    result = []
    try:
        entries = proc_root.iterdir()
    except FileNotFoundError:
        return result
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm in RUNNING_COMMS:
            result.append((int(entry.name), comm))
    return sorted(result)


def matching_brace(lines: list[bytes], opening: int) -> int:
    if lines[opening].strip() != b"{":
        raise MappingError("expected an opening VDF brace")
    depth = 0
    for index in range(opening, len(lines)):
        token = lines[index].strip()
        if token == b"{":
            depth += 1
        elif token == b"}":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                break
    raise MappingError("VDF object has unbalanced braces")


def direct_objects(
    lines: list[bytes], opening: int, closing: int
) -> dict[str, tuple[int, int, int]]:
    objects: dict[str, tuple[int, int, int]] = {}
    index = opening + 1
    while index < closing:
        match = KEY_LINE.fullmatch(lines[index])
        if match is None:
            index += 1
            continue
        next_index = index + 1
        while next_index < closing and not lines[next_index].strip():
            next_index += 1
        if next_index >= closing or lines[next_index].strip() != b"{":
            index += 1
            continue
        child_closing = matching_brace(lines, next_index)
        if child_closing > closing:
            raise MappingError("nested VDF object exceeds its parent")
        key = match.group("key").decode("ascii")
        if key in objects:
            raise MappingError(f"duplicate VDF object: {key}")
        objects[key] = (index, next_index, child_closing)
        index = child_closing + 1
    return objects


def find_mapping(lines: list[bytes]) -> tuple[int, int]:
    parent_open = -1
    parent_close = len(lines)
    for expected in CONFIG_PATH:
        objects = direct_objects(lines, parent_open, parent_close)
        try:
            _key_line, parent_open, parent_close = objects[expected]
        except KeyError as error:
            raise MappingError(f"required VDF object is missing: {expected}") from error
    return parent_open, parent_close


def block(appid: str, tool: str, priority: int, indent: bytes, newline: bytes) -> list[bytes]:
    child = indent + b"\t"
    return [
        indent + b'"' + appid.encode() + b'"' + newline,
        indent + b"{" + newline,
        child + b'"name"\t\t"' + tool.encode() + b'"' + newline,
        child + b'"config"\t\t""' + newline,
        child + b'"priority"\t\t"' + str(priority).encode() + b'"' + newline,
        indent + b"}" + newline,
    ]


def render_mapping(payload: bytes, appid: str, tool: str, priority: int) -> bytes:
    if not APPID_PATTERN.fullmatch(appid):
        raise MappingError(f"invalid Steam AppID: {appid!r}")
    if not TOOL_PATTERN.fullmatch(tool):
        raise MappingError(f"invalid compatibility tool name: {tool!r}")
    if priority < 1 or priority > 999:
        raise MappingError("priority must be between 1 and 999")
    if b"\x00" in payload:
        raise MappingError("config.vdf contains a NUL byte")
    newline = b"\r\n" if b"\r\n" in payload else b"\n"
    lines = payload.splitlines(keepends=True)
    if not lines:
        raise MappingError("config.vdf is empty")
    opening, closing = find_mapping(lines)
    objects = direct_objects(lines, opening, closing)
    if appid in objects:
        key_line, _child_open, child_close = objects[appid]
        indent = KEY_LINE.fullmatch(lines[key_line]).group("indent")
        lines[key_line : child_close + 1] = block(
            appid, tool, priority, indent, newline
        )
    else:
        parent_indent = lines[closing][: -len(lines[closing].lstrip(b" \t"))]
        lines[closing:closing] = block(
            appid, tool, priority, parent_indent + b"\t", newline
        )
    return b"".join(lines)


def load_config(path: Path) -> tuple[bytes, os.stat_result]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MappingError(f"config must be a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise MappingError("config must have exactly one hard link")
    if metadata.st_size <= 0 or metadata.st_size > MAX_CONFIG_BYTES:
        raise MappingError(f"config size is invalid: {metadata.st_size}")
    return path.read_bytes(), metadata


def install_config(
    path: Path, original: bytes, metadata: os.stat_result, rendered: bytes, base: Path
) -> Path:
    current = path.lstat()
    identity = (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)
    current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if current_identity != identity or path.read_bytes() != original:
        raise MappingError("config changed while the mapping was prepared")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups = base / "backups"
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(prefix=f"steam-compat-{stamp}-", dir=backups))
    backup = backup_dir / "config.vdf"
    shutil.copy2(path, backup, follow_symlinks=False)
    if backup.read_bytes() != original:
        raise MappingError("config backup verification failed")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".config.vdf.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(stat.S_IMODE(metadata.st_mode))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if path.read_bytes() != rendered:
        raise MappingError("installed config verification failed")
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map one Steam AppID to the verified ARM64 Proton tool."
    )
    parser.add_argument("appid")
    parser.add_argument("--tool", default="proton_11_arm64_official")
    parser.add_argument("--priority", type=int, default=250)
    parser.add_argument("--config", type=Path, default=default_config())
    parser.add_argument("--base", type=Path, default=Path.home() / "steam-arm64")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"), help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    try:
        running = active_processes(arguments.proc_root)
        if running:
            detail = ", ".join(f"{pid}:{comm}" for pid, comm in running)
            raise MappingError(f"Steam/Wine must be stopped: {detail}")
        original, metadata = load_config(arguments.config)
        rendered = render_mapping(
            original, arguments.appid, arguments.tool, arguments.priority
        )
        changed = rendered != original
        backup = None
        if changed and not arguments.dry_run:
            backup = install_config(
                arguments.config, original, metadata, rendered, arguments.base
            )
    except (OSError, MappingError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "appid": arguments.appid,
                "backup": str(backup) if backup else None,
                "changed": changed,
                "dry_run": arguments.dry_run,
                "priority": arguments.priority,
                "tool": arguments.tool,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
