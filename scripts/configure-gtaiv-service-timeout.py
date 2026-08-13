#!/usr/bin/env python3

"""Set Wine's SCM startup timeout for GTA IV with an atomic registry edit."""

import argparse
import datetime
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time


COMMON_PATH = Path(__file__).with_name("configure-gtaiv-virtual-desktop.py")
SPEC = importlib.util.spec_from_file_location("gtaiv_registry_common", COMMON_PATH)
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)

SECTION = br"System\\ControlSet001\\Control"
VALUE = br'"ServicesPipeTimeout"="60000"'
HEADER = re.compile(rb"^\[([^]]+)\](?: [0-9]+)?$")
VALUE_RE = re.compile(br'^"ServicesPipeTimeout"=.*$', re.IGNORECASE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(path):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"registry is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"registry has an unexpected link count: {path}")
    return metadata


def sections(lines):
    found = []
    for index, line in enumerate(lines):
        match = HEADER.fullmatch(line.rstrip(b"\r\n"))
        if match:
            found.append((match.group(1), index))
    return [
        (name, start, found[offset + 1][1] if offset + 1 < len(found) else len(lines))
        for offset, (name, start) in enumerate(found)
    ]


def render(original, now=None):
    if not original.startswith(b"WINE REGISTRY Version 2\n"):
        raise RuntimeError("system.reg does not have the expected Wine registry header")
    lines = original.splitlines(keepends=True)
    ranges = sections(lines)
    target = [item for item in ranges if item[0].lower() == SECTION.lower()]
    all_values = [
        line.rstrip(b"\r\n") for line in lines
        if VALUE_RE.fullmatch(line.rstrip(b"\r\n"))
    ]
    if len(target) > 1 or len(all_values) > 1:
        raise RuntimeError("duplicate ServicesPipeTimeout registry state")
    if target:
        _name, start, end = target[0]
        values = [
            line.rstrip(b"\r\n") for line in lines[start + 1:end]
            if VALUE_RE.fullmatch(line.rstrip(b"\r\n"))
        ]
        if values == [VALUE]:
            return original, False
        if values:
            raise RuntimeError(f"unexpected ServicesPipeTimeout value: {values!r}")
        insertion = end
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        return b"".join(lines[:insertion] + [VALUE + newline] + lines[insertion:]), True
    if all_values:
        raise RuntimeError("ServicesPipeTimeout exists outside the expected control section")

    insertion = len(lines)
    for name, start, _end in ranges:
        if name.lower() > SECTION.lower():
            insertion = start
            break
    timestamp = int(time.time() if now is None else now)
    filetime = int((timestamp + 11644473600) * 10_000_000)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    block = [
        b"[" + SECTION + b"] " + str(timestamp).encode() + newline,
        b"#time=" + format(filetime, "x").encode() + newline,
        VALUE + newline,
        newline,
    ]
    if insertion > 0 and lines[insertion - 1].rstrip(b"\r\n"):
        block.insert(0, newline)
    return b"".join(lines[:insertion] + block + lines[insertion:]), True


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_all(descriptor, data):
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written == 0:
            raise OSError("zero-byte registry write")
        offset += written


def apply(registry, backups_dir, expected_sha):
    metadata = inspect(registry)
    original = registry.read_bytes()
    if digest(original) != expected_sha:
        raise RuntimeError("registry changed after validation; refusing to edit")
    rendered, changed = render(original)
    if not changed:
        return None, digest(original)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(prefix=f"gtaiv-service-timeout-{stamp}-", dir=backups_dir))
    backup = backup_dir / "system.reg"
    shutil.copy2(registry, backup, follow_symlinks=False)
    if backup.read_bytes() != original:
        raise RuntimeError("registry backup verification failed")

    descriptor, temporary_name = tempfile.mkstemp(prefix=".system.reg.gtaiv-service-", dir=registry.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        write_all(descriptor, rendered)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError("staged registry verification failed")
        os.replace(temporary, registry)
        fsync_directory(registry.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    if registry.read_bytes() != rendered:
        raise RuntimeError("installed registry verification failed")
    return backup, digest(rendered)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--backups-dir", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    try:
        running = COMMON.find_running_prefix_processes()
        if running:
            details = ", ".join(
                f"{pid}:{comm}" for pid, comm, _cmdline in running
            )
            raise RuntimeError(
                "refusing while Wine/Proton/container processes are active: "
                f"{details}"
            )
        backup, installed = apply(args.registry, args.backups_dir, args.expected_sha)
        print(f"Backup: {backup}")
        print(f"Installed system.reg SHA-256: {installed}")
        print('Installed REG_SZ: HKLM\\System\\CurrentControlSet\\Control\\ServicesPipeTimeout="60000"')
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-gtaiv-service-timeout: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
