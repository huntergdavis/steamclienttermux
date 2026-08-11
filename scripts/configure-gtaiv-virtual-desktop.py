#!/usr/bin/env python3

"""Configure a reversible Wine virtual desktop for GTA IV's Proton prefix."""

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time


EXPLORER_SECTION = br"Software\\Wine\\Explorer"
DESKTOPS_SECTION = br"Software\\Wine\\Explorer\\Desktops"
DESKTOP_KEY = b"Desktop"
DEFAULT_KEY = b"Default"
HEADER = re.compile(rb"^\[([^]]+)\](?: [0-9]+)?$")
SIZE = re.compile(r"^([0-9]{3,5})x([0-9]{3,5})$")
RUNNING_COMMS = {
    "fexinterpreter",
    "fexloader",
    "launcher.exe",
    "playgtaiv.exe",
    "services.exe",
    "socialclubhelper.exe",
    "steam.exe",
    "wine",
    "wine64",
    "wineserver",
}
RUNNING_CMDLINE_MARKERS = (
    b"/_v2-entry-point ",
    b"/fexinterpreter ",
    b"/fexloader ",
    b"/playgtaiv.exe",
    b"/proton ",
    b"/pv-adverb ",
    b"/srt-bwrap ",
    b"/socialclubhelper.exe",
    b"/wine64 ",
    b"/wineserver ",
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def inspect_regular(path, label):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"{label} has an unexpected link count: {path}")
    return metadata


def parse_size(value):
    match = SIZE.fullmatch(value)
    if not match:
        raise ValueError("desktop size must use WIDTHxHEIGHT")
    width, height = (int(part) for part in match.groups())
    if not 640 <= width <= 8192 or not 480 <= height <= 8192:
        raise ValueError("desktop size must be between 640x480 and 8192x8192")
    return f"{width}x{height}"


def registry_sections(lines):
    sections = []
    for index, line in enumerate(lines):
        match = HEADER.fullmatch(line.rstrip(b"\r\n"))
        if match:
            sections.append((match.group(1), index))
    ranges = []
    for offset, (name, start) in enumerate(sections):
        end = sections[offset + 1][1] if offset + 1 < len(sections) else len(lines)
        ranges.append((name, start, end))
    return ranges


def find_section(lines, target):
    matches = [entry for entry in registry_sections(lines) if entry[0].lower() == target.lower()]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate Wine registry section: {target.decode()}")
    return matches[0] if matches else None


def value_pattern(key):
    return re.compile(rb'^"' + re.escape(key) + rb'"=.*$', re.IGNORECASE)


def value_line(key, value):
    return b'"' + key + b'"="' + value + b'"'


def timestamp_lines(section, value, newline, now):
    timestamp = int(time.time() if now is None else now)
    filetime = int((timestamp + 11644473600) * 10_000_000)
    return [
        b"[" + section + b"] " + str(timestamp).encode("ascii") + newline,
        b"#time=" + format(filetime, "x").encode("ascii") + newline,
        value + newline,
        newline,
    ]


def enable_value(data, section, key, desired, now=None):
    lines = data.splitlines(keepends=True)
    newline = b"\r\n" if b"\r\n" in data else b"\n"
    target = find_section(lines, section)
    pattern = value_pattern(key)
    if target:
        _name, start, end = target
        matches = [index for index in range(start + 1, end) if pattern.fullmatch(lines[index].rstrip(b"\r\n"))]
        if len(matches) > 1:
            raise RuntimeError(f"duplicate Wine registry value: {key.decode()}")
        if matches:
            index = matches[0]
            if lines[index].rstrip(b"\r\n") == desired:
                return data, False
            lines[index] = desired + newline
            return b"".join(lines), True
        insertion = end
        while insertion > start + 1 and not lines[insertion - 1].rstrip(b"\r\n"):
            insertion -= 1
        lines.insert(insertion, desired + newline)
        return b"".join(lines), True

    insertion = len(lines)
    section_lower = section.lower()
    for name, start, _end in registry_sections(lines):
        if name.lower() > section_lower:
            insertion = start
            break
    block = timestamp_lines(section, desired, newline, now)
    if insertion > 0 and lines[insertion - 1].rstrip(b"\r\n"):
        block.insert(0, newline)
    return b"".join(lines[:insertion] + block + lines[insertion:]), True


def disable_value(data, section, key, expected):
    lines = data.splitlines(keepends=True)
    target = find_section(lines, section)
    if not target:
        return data, False
    _name, start, end = target
    pattern = value_pattern(key)
    matches = [index for index in range(start + 1, end) if pattern.fullmatch(lines[index].rstrip(b"\r\n"))]
    if len(matches) > 1:
        raise RuntimeError(f"duplicate Wine registry value: {key.decode()}")
    if not matches:
        return data, False
    index = matches[0]
    actual = lines[index].rstrip(b"\r\n")
    if actual != expected:
        raise RuntimeError(
            f"refusing to remove unexpected Wine registry value for {key.decode()}: "
            f"{actual.decode('utf-8', 'replace')}"
        )
    del lines[index]

    target = find_section(lines, section)
    _name, start, end = target
    meaningful = []
    for line in lines[start + 1 : end]:
        stripped = line.rstrip(b"\r\n")
        if not stripped or stripped.startswith((b"#", b";")):
            continue
        meaningful.append(stripped)
    if not meaningful:
        del lines[start:end]
    return b"".join(lines), True


def render_registry(original, size="1920x1080", enable=True, now=None):
    if not original.startswith(b"WINE REGISTRY Version 2\n"):
        raise RuntimeError("user.reg does not have the expected Wine registry header")
    normalized = parse_size(size).encode("ascii")
    desktop = value_line(DESKTOP_KEY, DEFAULT_KEY)
    dimensions = value_line(DEFAULT_KEY, normalized)
    rendered = original
    changes = []
    if enable:
        rendered, changed = enable_value(
            rendered, EXPLORER_SECTION, DESKTOP_KEY, desktop, now=now
        )
        if changed:
            changes.append("HKCU\\Software\\Wine\\Explorer Desktop=Default")
        rendered, changed = enable_value(
            rendered, DESKTOPS_SECTION, DEFAULT_KEY, dimensions, now=now
        )
        if changed:
            changes.append(f"HKCU\\Software\\Wine\\Explorer\\Desktops Default={size}")
    else:
        rendered, changed = disable_value(
            rendered, DESKTOPS_SECTION, DEFAULT_KEY, dimensions
        )
        if changed:
            changes.append(f"removed virtual desktop size {size}")
        rendered, changed = disable_value(
            rendered, EXPLORER_SECTION, DESKTOP_KEY, desktop
        )
        if changed:
            changes.append("removed virtual desktop selection")
    return rendered, changes


def find_running_prefix_processes(proc_root=Path("/proc")):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").lower()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm.lower() in RUNNING_COMMS or any(marker in cmdline for marker in RUNNING_CMDLINE_MARKERS):
            matches.append((int(entry.name), comm, cmdline.decode("utf-8", "replace")))
    return sorted(matches)


def write_all(descriptor, data):
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written == 0:
            raise OSError("zero-byte registry write")
        offset += written


def fsync_directory(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def apply_registry(registry, backups_dir, size="1920x1080", enable=True, now=None):
    metadata = inspect_regular(registry, "user.reg")
    original = registry.read_bytes()
    rendered, changes = render_registry(original, size=size, enable=enable, now=now)
    if not changes:
        return None, changes, sha256_bytes(original)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"gtaiv-virtual-desktop-{stamp}-", dir=backups_dir))
    backup_registry = backup / "user.reg"
    shutil.copy2(registry, backup_registry, follow_symlinks=False)
    if backup_registry.read_bytes() != original:
        raise RuntimeError(f"registry backup verification failed: {backup_registry}")

    descriptor, temporary_name = tempfile.mkstemp(prefix=".user.reg.gtaiv-vd-", dir=registry.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        write_all(descriptor, rendered)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError(f"staged registry verification failed: {temporary}")
        os.replace(temporary, registry)
        fsync_directory(registry.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    if registry.read_bytes() != rendered:
        raise RuntimeError(f"installed registry verification failed: {registry}")
    return backup, changes, sha256_bytes(rendered)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--registry")
    parser.add_argument("--backups-dir")
    parser.add_argument("--size", default="1920x1080")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", action="store_true")
    action.add_argument("--disable", action="store_true")
    action.add_argument("--check", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    registry = (
        Path(args.registry)
        if args.registry
        else base / "removable-library-compatdata/12210/pfx/user.reg"
    )
    backups_dir = Path(args.backups_dir) if args.backups_dir else base / "backups"
    try:
        size = parse_size(args.size)
        inspect_regular(registry, "user.reg")
        original = registry.read_bytes()
        _rendered, pending = render_registry(original, size=size, enable=True)
        if args.check:
            if pending:
                for change in pending:
                    print(f"pending: {change}")
                return 1
            print(f"GTA IV virtual desktop: current ({size}, {sha256_bytes(original)})")
            return 0

        running = find_running_prefix_processes()
        if running:
            details = ", ".join(f"{pid}:{comm}" for pid, comm, _cmdline in running)
            raise RuntimeError(f"refusing while Wine/Proton/container processes are active: {details}")
        backup, changes, digest = apply_registry(
            registry, backups_dir, size=size, enable=args.enable
        )
        if not changes:
            state = "enabled" if args.enable else "disabled"
            print(f"GTA IV virtual desktop already {state} ({digest})")
            return 0
        for change in changes:
            print(f"changed: {change}")
        print(f"Backup: {backup}")
        print(f"Installed user.reg SHA-256: {digest}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-gtaiv-virtual-desktop: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
