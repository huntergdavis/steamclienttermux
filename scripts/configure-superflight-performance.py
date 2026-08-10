#!/usr/bin/env python3

"""Apply the confirmed Superflight performance profile without touching Wine."""

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


SECTION = b"[Software\\\\Grizzly Games\\\\SUPERFLIGHT]"
SECTION_HEADER = re.compile(rb"^" + re.escape(SECTION) + rb"(?: [0-9]+)?$")
TARGET_DWORDS = {
    b"Screenmanager Is Fullscreen mode_h3981298716": b"00000001",
    b"Screenmanager Resolution Height_h2627697771": b"000002d0",
    b"Screenmanager Resolution Width_h182942802": b"00000500",
    b"UnityGraphicsQuality_h1669003810": b"00000000",
    b"video_antialiasing_h2457061775": b"00000000",
    b"video_motionblur_h3717583676": b"00000000",
    b"video_postprocessing_h645834456": b"00000000",
    b"video_shadowdistance_h911383566": b"00000000",
    b"video_shadowquality_h1126408960": b"00000000",
}
RUNNING_COMMS = {
    "steam",
    "steamwebhelper",
    "superflight.exe",
    "wineserver",
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def inspect_registry(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"registry is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"registry is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"registry has an unexpected link count: {path}")
    return metadata


def render_profile(original):
    lines = original.splitlines(keepends=True)
    section_indexes = [
        index
        for index, line in enumerate(lines)
        if SECTION_HEADER.fullmatch(line.rstrip(b"\r\n"))
    ]
    if len(section_indexes) != 1:
        raise RuntimeError(
            f"expected exactly one Superflight registry section, found "
            f"{len(section_indexes)}"
        )
    section_start = section_indexes[0] + 1
    section_end = len(lines)
    for index in range(section_start, len(lines)):
        if lines[index].startswith(b"["):
            section_end = index
            break

    changed = []
    for key, target in TARGET_DWORDS.items():
        pattern = re.compile(
            rb'^"' + re.escape(key) + rb'"=dword:([0-9a-fA-F]{8})(\r?\n)?$'
        )
        matches = []
        for index in range(section_start, section_end):
            match = pattern.match(lines[index])
            if match:
                matches.append((index, match))
        if len(matches) != 1:
            decoded = key.decode("ascii")
            raise RuntimeError(
                f"expected exactly one {decoded!r} DWORD in Superflight section, "
                f"found {len(matches)}"
            )
        index, match = matches[0]
        previous = match.group(1).lower()
        if previous == target:
            continue
        ending = match.group(2) or b""
        lines[index] = b'"' + key + b'"=dword:' + target + ending
        changed.append((key.decode("ascii"), previous.decode("ascii"), target.decode("ascii")))

    return b"".join(lines), changed


def find_running_processes(proc_root=Path("/proc")):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            comm in RUNNING_COMMS
            or b"steamrtarm64/steam" in cmdline
            or b"superflight.exe" in cmdline.lower()
            or b"/wineserver" in cmdline
        ):
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


def apply_profile(registry, backups_dir):
    metadata = inspect_registry(registry)
    original = registry.read_bytes()
    rendered, changed = render_profile(original)
    if not changed:
        return None, changed, sha256_bytes(original)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"superflight-performance-{stamp}-", dir=backups_dir))
    backup_registry = backup / "user.reg"
    shutil.copy2(registry, backup_registry, follow_symlinks=False)
    if backup_registry.read_bytes() != original:
        raise RuntimeError(f"registry backup verification failed: {backup_registry}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{registry.name}.superflight-", dir=registry.parent
    )
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
    parser.add_argument("--registry")
    parser.add_argument("--backups-dir")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the profile without changing or backing up the registry",
    )
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    registry = Path(args.registry) if args.registry else (
        base / "client/steamapps/compatdata/732430/pfx/user.reg"
    )
    backups_dir = Path(args.backups_dir) if args.backups_dir else base / "backups"
    try:
        metadata = inspect_registry(registry)
        original = registry.read_bytes()
        _rendered, pending = render_profile(original)
        if args.check:
            if pending:
                for key, previous, target in pending:
                    print(f"pending: {key}: {previous} -> {target}")
                return 1
            print(f"Superflight performance profile: current ({sha256_bytes(original)})")
            return 0

        running = find_running_processes()
        if running:
            details = ", ".join(f"{pid}:{comm}" for pid, comm, _cmdline in running)
            raise RuntimeError(
                "refusing to edit the Wine registry while Steam/Wine/game processes "
                f"are active: {details}"
            )
        del metadata
        backup, changed, digest = apply_profile(registry, backups_dir)
        if not changed:
            print(f"Superflight performance profile already current ({digest})")
            return 0
        for key, previous, target in changed:
            print(f"changed: {key}: {previous} -> {target}")
        print(f"Backup: {backup}")
        print(f"Installed SHA-256: {digest}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-superflight-performance: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
