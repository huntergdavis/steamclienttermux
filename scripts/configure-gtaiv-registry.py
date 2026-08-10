#!/usr/bin/env python3

"""Apply GTA IV's signed Steam installscript registry state safely."""

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


INSTALLSCRIPT_SHA256 = "58de41add79ba9753b4a73b00a1ad7e7e1e14770c959beb4c8b78155607ed498"
PARENT_SECTION = br"Software\\Rockstar Games\\Grand Theft Auto IV"
VERSION_SECTION = PARENT_SECTION + br"\\1.00.0000"
INSTALL_FOLDER_LINE = br'"InstallFolder"="S:\\common\\Grand Theft Auto IV\\GTAIV"'
HEADER = re.compile(rb"^\[([^]]+)\](?: [0-9]+)?$")
INSTALL_FOLDER = re.compile(rb'^"InstallFolder"=.*$', re.IGNORECASE)
RUNNING_COMMS = {
    "fexinterpreter",
    "fexloader",
    "playgtaiv.exe",
    "rockstar-games-launcher.exe",
    "wine",
    "wine64",
    "wineserver",
}
RUNNING_CMDLINE_MARKERS = (
    b"/_v2-entry-point ",
    b"/fexinterpreter ",
    b"/fexloader ",
    b"/iscriptevaluator.exe",
    b"/playgtaiv.exe",
    b"/proton ",
    b"/pv-adverb ",
    b"/rockstar-games-launcher.exe",
    b"/srt-bwrap ",
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


def validate_installscript(path, expected_digest=INSTALLSCRIPT_SHA256):
    inspect_regular(path, "signed installscript")
    digest = sha256_bytes(path.read_bytes())
    if digest != expected_digest:
        raise RuntimeError(
            f"signed installscript SHA-256 mismatch: expected {expected_digest}, got {digest}"
        )
    return digest


def validate_dosdevice(path, expected_target):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"S: dosdevice is missing: {path}") from error
    if not stat.S_ISLNK(metadata.st_mode):
        raise RuntimeError(f"S: dosdevice is not a symbolic link: {path}")
    target = os.readlink(path)
    if target != str(expected_target):
        raise RuntimeError(
            f"S: dosdevice target mismatch: expected {expected_target}, got {target}"
        )
    return target


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


def render_registry(original, now=None):
    if not original.startswith(b"WINE REGISTRY Version 2\n"):
        raise RuntimeError("system.reg does not have the expected Wine registry header")
    lines = original.splitlines(keepends=True)
    ranges = registry_sections(lines)

    def matches(target):
        target_lower = target.lower()
        return [(name, start, end) for name, start, end in ranges if name.lower() == target_lower]

    parents = matches(PARENT_SECTION)
    versions = matches(VERSION_SECTION)
    if len(parents) > 1 or len(versions) > 1:
        raise RuntimeError(
            f"duplicate GTA IV registry sections: parent={len(parents)}, version={len(versions)}"
        )
    if bool(parents) != bool(versions):
        raise RuntimeError("partial GTA IV registry state; refusing to guess the missing section")
    if parents:
        _name, start, end = parents[0]
        values = [
            line.rstrip(b"\r\n")
            for line in lines[start + 1 : end]
            if INSTALL_FOLDER.fullmatch(line.rstrip(b"\r\n"))
        ]
        if values != [INSTALL_FOLDER_LINE]:
            rendered = [value.decode("utf-8", "replace") for value in values]
            raise RuntimeError(f"unexpected GTA IV InstallFolder state: {rendered}")
        return original, []

    insertion = len(lines)
    parent_lower = PARENT_SECTION.lower()
    for name, start, _end in ranges:
        if name.lower() > parent_lower:
            insertion = start
            break

    timestamp = int(time.time() if now is None else now)
    filetime = int((timestamp + 11644473600) * 10_000_000)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    block = [
        b"[" + PARENT_SECTION + b"] " + str(timestamp).encode("ascii") + newline,
        b"#time=" + format(filetime, "x").encode("ascii") + newline,
        INSTALL_FOLDER_LINE + newline,
        newline,
        b"[" + VERSION_SECTION + b"] " + str(timestamp).encode("ascii") + newline,
        b"#time=" + format(filetime, "x").encode("ascii") + newline,
        newline,
    ]
    if insertion > 0 and lines[insertion - 1].rstrip(b"\r\n"):
        block.insert(0, newline)
    return b"".join(lines[:insertion] + block + lines[insertion:]), [
        "HKLM\\SOFTWARE\\Rockstar Games\\Grand Theft Auto IV InstallFolder",
        "HKLM\\SOFTWARE\\Rockstar Games\\Grand Theft Auto IV\\1.00.0000",
    ]


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


def apply_registry(registry, backups_dir, now=None):
    metadata = inspect_regular(registry, "system.reg")
    original = registry.read_bytes()
    rendered, changed = render_registry(original, now=now)
    if not changed:
        return None, changed, sha256_bytes(original)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"gtaiv-registry-{stamp}-", dir=backups_dir))
    backup_registry = backup / "system.reg"
    shutil.copy2(registry, backup_registry, follow_symlinks=False)
    if backup_registry.read_bytes() != original:
        raise RuntimeError(f"registry backup verification failed: {backup_registry}")

    descriptor, temporary_name = tempfile.mkstemp(prefix=".system.reg.gtaiv-", dir=registry.parent)
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
    return backup, changed, sha256_bytes(rendered)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--installscript", required=True)
    parser.add_argument("--registry")
    parser.add_argument("--backups-dir")
    parser.add_argument("--check", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    prefix = base / "removable-library-compatdata/12210/pfx"
    registry = Path(args.registry) if args.registry else prefix / "system.reg"
    backups_dir = Path(args.backups_dir) if args.backups_dir else base / "backups"
    try:
        installscript_digest = validate_installscript(Path(args.installscript))
        dosdevice_target = validate_dosdevice(
            prefix / "dosdevices/s:", base / "removable-library/steamapps"
        )
        inspect_regular(registry, "system.reg")
        original = registry.read_bytes()
        _rendered, pending = render_registry(original)
        if args.check:
            if pending:
                for change in pending:
                    print(f"pending: {change}")
                return 1
            print(f"GTA IV registry state: current ({sha256_bytes(original)})")
            return 0

        running = find_running_prefix_processes()
        if running:
            details = ", ".join(f"{pid}:{comm}" for pid, comm, _cmdline in running)
            raise RuntimeError(f"refusing while Wine/Proton/container processes are active: {details}")
        backup, changed, digest = apply_registry(registry, backups_dir)
        if not changed:
            print(f"GTA IV registry state already current ({digest})")
            return 0
        for change in changed:
            print(f"created: {change}")
        print(f"Signed installscript SHA-256: {installscript_digest}")
        print(f"S: target: {dosdevice_target}")
        print(f"Backup: {backup}")
        print(f"Installed system.reg SHA-256: {digest}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-gtaiv-registry: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
