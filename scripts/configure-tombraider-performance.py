#!/usr/bin/env python3

"""Apply a measured Tomb Raider benchmark profile safely."""

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


SECTION = b"[Software\\\\Crystal Dynamics\\\\Tomb Raider\\\\Graphics]"
SECTION_HEADER = re.compile(rb"^" + re.escape(SECTION) + rb"(?: [0-9]+)?$")
TARGET_DWORDS = {
    b"AntiAliasingMode": b"00000000",
    b"DOFQuality": b"00000000",
    b"EnableMotionBlur": b"00000000",
    b"EnablePostProcess": b"00000000",
    b"EnableScreenEffects": b"00000000",
    b"EnableTessellation": b"00000000",
    b"ExclusiveFullscreen": b"00000001",
    b"Fullscreen": b"00000001",
    b"FullscreenHeight": b"000006d8",
    b"FullscreenRefreshRate": b"0000003c",
    b"FullscreenWidth": b"00000af0",
    b"HairQuality": b"00000000",
    b"LODScale": b"00000000",
    b"PrecreateShaders": b"00000001",
    b"ReflectionQuality": b"00000000",
    b"RenderAPI": b"00000000",
    b"ShadowMode": b"00000000",
    b"ShadowResolution": b"00000000",
    b"SSAOMode": b"00000000",
    b"TextureQuality": b"00000002",
    b"VSyncMode": b"00000000",
}
NORMAL_720P_DWORDS = {
    **TARGET_DWORDS,
    b"AntiAliasingMode": b"00000001",
    b"DOFQuality": b"00000001",
    b"EnablePostProcess": b"00000001",
    b"FullscreenHeight": b"000002d0",
    b"FullscreenWidth": b"00000500",
    b"LODScale": b"00000002",
    b"ReflectionQuality": b"00000001",
    b"ShadowMode": b"00000001",
    b"ShadowResolution": b"00000001",
    b"SSAOMode": b"00000001",
}
PROFILES = {
    "native-low": TARGET_DWORDS,
    "720p-normal": NORMAL_720P_DWORDS,
}
RUNNING_COMMS = {
    "fexinterpreter",
    "fexloader",
    "tombraider.exe",
    "wine",
    "wine64",
    "wineserver",
}
RUNNING_CMDLINE_MARKERS = (
    b"/_v2-entry-point ",
    b"/fexinterpreter ",
    b"/fexloader ",
    b"/proton ",
    b"/tombraider.exe",
    b"/wine64 ",
    b"/wineserver ",
)


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


def render_profile(original, targets=TARGET_DWORDS):
    if not original.startswith(b"WINE REGISTRY Version 2"):
        raise RuntimeError("user.reg does not have the expected Wine registry header")
    lines = original.splitlines(keepends=True)
    section_indexes = [
        index
        for index, line in enumerate(lines)
        if SECTION_HEADER.fullmatch(line.rstrip(b"\r\n"))
    ]
    if len(section_indexes) != 1:
        raise RuntimeError(
            "expected exactly one Tomb Raider graphics registry section, found "
            f"{len(section_indexes)}"
        )
    section_start = section_indexes[0] + 1
    section_end = len(lines)
    for index in range(section_start, len(lines)):
        if lines[index].startswith(b"["):
            section_end = index
            break

    changed = []
    for key, target in targets.items():
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
                f"expected exactly one {decoded!r} DWORD in Tomb Raider graphics "
                f"section, found {len(matches)}"
            )
        index, match = matches[0]
        previous = match.group(1).lower()
        if previous == target:
            continue
        ending = match.group(2) or b""
        lines[index] = b'"' + key + b'"=dword:' + target + ending
        changed.append(
            (key.decode("ascii"), previous.decode("ascii"), target.decode("ascii"))
        )

    return b"".join(lines), changed


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
        if comm.lower() in RUNNING_COMMS or any(
            marker in cmdline for marker in RUNNING_CMDLINE_MARKERS
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


def apply_profile(registry, backups_dir, targets=TARGET_DWORDS, profile="native-low"):
    metadata = inspect_registry(registry)
    original = registry.read_bytes()
    rendered, changed = render_profile(original, targets)
    if not changed:
        return None, changed, sha256_bytes(original)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(
        tempfile.mkdtemp(
            prefix=f"tombraider-{profile}-{stamp}-", dir=backups_dir
        )
    )
    backup_registry = backup / "user.reg"
    shutil.copy2(registry, backup_registry, follow_symlinks=False)
    if backup_registry.read_bytes() != original:
        raise RuntimeError(f"registry backup verification failed: {backup_registry}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{registry.name}.tombraider-", dir=registry.parent
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
    parser.add_argument("--profile", choices=tuple(PROFILES), default="native-low")
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
        base / "removable-library-compatdata/203160/pfx/user.reg"
    )
    backups_dir = Path(args.backups_dir) if args.backups_dir else base / "backups"
    try:
        inspect_registry(registry)
        original = registry.read_bytes()
        targets = PROFILES[args.profile]
        _rendered, pending = render_profile(original, targets)
        if args.check:
            if pending:
                for key, previous, target in pending:
                    print(f"pending: {key}: {previous} -> {target}")
                return 1
            print(
                f"Tomb Raider performance profile {args.profile}: current "
                f"({sha256_bytes(original)})"
            )
            return 0

        running = find_running_prefix_processes()
        if running:
            details = ", ".join(f"{pid}:{comm}" for pid, comm, _cmdline in running)
            raise RuntimeError(
                "refusing to edit the Wine registry while Wine/game translation "
                f"processes are active: {details}"
            )
        backup, changed, digest = apply_profile(
            registry, backups_dir, targets, args.profile
        )
        if not changed:
            print(f"Tomb Raider performance profile already current ({digest})")
            return 0
        for key, previous, target in changed:
            print(f"changed: {key}: {previous} -> {target}")
        print(f"Backup: {backup}")
        print(f"Installed SHA-256: {digest}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-tombraider-performance: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
