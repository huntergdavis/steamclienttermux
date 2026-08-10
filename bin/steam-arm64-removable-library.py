#!/usr/bin/env python3

"""Prepare and validate an optional removable Steam game-data library."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys
import tempfile


CONFIG_NAME = "removable-library.json"
LIBRARY_NAME = "steam-arm64-library"
UUID_PATTERN = re.compile(r"^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")
RUNNING_COMMS = {"steam", "steamwebhelper", "wineserver"}


def inspect_directory(path, label, *, require_empty=False):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{label} is not a real directory: {path}")
    if require_empty and next(path.iterdir(), None) is not None:
        raise RuntimeError(f"{label} must be empty: {path}")
    return metadata


def inspect_directory_skeleton(path, label):
    metadata = inspect_directory(path, label)
    pending = [path]
    while pending:
        current = pending.pop()
        for entry in current.iterdir():
            entry_metadata = entry.lstat()
            if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISDIR(
                entry_metadata.st_mode
            ):
                raise RuntimeError(
                    f"{label} contains non-directory data: {entry}"
                )
            pending.append(entry)
    return metadata


def inspect_config(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"configuration is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"configuration has an unexpected link count: {path}")
    if metadata.st_uid != os.getuid():
        raise RuntimeError(f"configuration has an unexpected owner: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError(f"configuration permissions are too broad: {path}")
    return metadata


def inspect_regular_file(path, label):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"{label} has an unexpected link count: {path}")
    return metadata


def validate_external_parent(parent, storage_root=Path("/storage")):
    try:
        resolved = parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"removable storage is unavailable: {parent}") from error
    inspect_directory(resolved, "removable app storage")
    try:
        relative = resolved.relative_to(storage_root.resolve())
    except ValueError as error:
        raise RuntimeError(f"removable storage is outside {storage_root}: {resolved}") from error
    parts = relative.parts
    if (
        len(parts) != 5
        or not UUID_PATTERN.fullmatch(parts[0])
        or parts[1:] != ("Android", "data", "com.termux", "files")
    ):
        raise RuntimeError(f"unexpected removable app-storage path: {resolved}")
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"removable app storage is not readable and writable: {resolved}")
    return resolved


def layout_paths(base, source):
    return {
        "source": source,
        "target": base / "removable-library",
        "steamapps_control": base / "removable-library-steamapps",
        "external_steamapps": source / "steamapps",
        "external_common": source / "steamapps" / "common",
        "compatdata": base / "removable-library-compatdata",
        "download_state": base / "removable-library-downloads",
        "config": base / "config" / CONFIG_NAME,
    }


def validate_layout(base, source, storage_root=Path("/storage")):
    parent = validate_external_parent(source.parent, storage_root)
    try:
        resolved_source = source.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"removable library is unavailable: {source}") from error
    if source.name != LIBRARY_NAME or resolved_source != parent / LIBRARY_NAME:
        raise RuntimeError(f"unexpected removable library path: {source}")
    paths = layout_paths(base, resolved_source)
    inspect_directory(paths["source"], "removable library")
    inspect_directory(paths["target"], "internal library mount point", require_empty=True)
    inspect_directory(paths["steamapps_control"], "internal Steam control root")
    inspect_directory(paths["external_steamapps"], "external steamapps root")
    unexpected_external = sorted(
        entry.name
        for entry in paths["external_steamapps"].iterdir()
        if entry.name != "common"
    )
    if unexpected_external:
        raise RuntimeError(
            "external Steam control data would be hidden: "
            + ", ".join(unexpected_external)
        )
    inspect_directory(paths["external_common"], "external common payload")
    inspect_directory(paths["compatdata"], "internal removable-library compatdata")
    inspect_directory(paths["download_state"], "internal removable-library downloads")
    inspect_directory_skeleton(
        paths["steamapps_control"] / "common",
        "internal common mount point",
    )
    inspect_directory_skeleton(
        paths["steamapps_control"] / "compatdata",
        "internal compatdata mount point",
    )
    inspect_directory_skeleton(
        paths["steamapps_control"] / "downloading",
        "internal downloads mount point",
    )
    if not os.access(paths["source"], os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"removable library is not readable and writable: {resolved_source}")
    free_bytes = os.statvfs(resolved_source).f_bavail * os.statvfs(resolved_source).f_frsize
    if free_bytes < 1024 * 1024 * 1024:
        raise RuntimeError(
            f"removable library has less than 1 GiB free: {resolved_source}"
        )
    return paths


def config_bytes(source):
    payload = {"version": 1, "source": str(source)}
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def fsync_directory(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace(path, rendered, mode):
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(rendered):
            written = os.write(descriptor, rendered[offset:])
            if written == 0:
                raise OSError("zero-byte atomic write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError(f"staged file verification failed: {temporary}")
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if path.read_bytes() != rendered:
        raise RuntimeError(f"installed file verification failed: {path}")


def write_config(path, rendered, backups_dir):
    existing = inspect_config(path)
    if existing is not None and path.read_bytes() == rendered:
        return None

    backup = None
    if existing is not None:
        backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = Path(
            tempfile.mkdtemp(prefix=f"removable-library-{stamp}-", dir=backups_dir)
        )
        backup_config = backup / CONFIG_NAME
        shutil.copy2(path, backup_config, follow_symlinks=False)
        if backup_config.read_bytes() != path.read_bytes():
            raise RuntimeError(f"configuration backup verification failed: {backup_config}")

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_replace(path, rendered, 0o600)
    return backup


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
            or b"/wineserver" in cmdline
        ):
            matches.append((int(entry.name), comm))
    return sorted(matches)


def render_libraryfolders(original, target, content_id):
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("libraryfolders.vdf is not valid UTF-8") from error
    target_text = str(target)
    if any(character in target_text for character in '"\r\n\t\0'):
        raise RuntimeError(f"invalid guest library path: {target}")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", content_id):
        raise RuntimeError(f"invalid library content ID: {content_id}")
    if not re.search(r'^"libraryfolders"\s*$', text, re.MULTILINE):
        raise RuntimeError("libraryfolders.vdf has no libraryfolders root")

    paths = re.findall(r'^\t\t"path"\s+"([^"\r\n]+)"\s*$', text, re.MULTILINE)
    target_count = paths.count(target_text)
    if target_count == 1:
        return original, None
    if target_count != 0:
        raise RuntimeError(f"guest library path appears {target_count} times")

    indexes = [
        int(value)
        for value in re.findall(r'^\t"([0-9]+)"\s*$', text, re.MULTILINE)
    ]
    if not indexes:
        raise RuntimeError("libraryfolders.vdf has no numeric library entries")
    index = max(indexes) + 1
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise RuntimeError("libraryfolders.vdf has no final root closure")
    closing = text.rfind("}", 0, len(stripped))
    newline = "\r\n" if "\r\n" in text else "\n"
    entry = newline.join(
        (
            f'\t"{index}"',
            "\t{",
            f'\t\t"path"\t\t"{target_text}"',
            '\t\t"label"\t\t"microSD Windows games"',
            f'\t\t"contentid"\t\t"{content_id}"',
            '\t\t"totalsize"\t\t"0"',
            '\t\t"update_clean_bytes_tally"\t\t"0"',
            '\t\t"time_last_update_verified"\t\t"0"',
            '\t\t"apps"',
            "\t\t{",
            "\t\t}",
            "\t}",
            "",
        )
    )
    rendered = text[:closing] + entry + text[closing:]
    return rendered.encode(), index


def register_library(base, paths):
    libraryfolders = base / "client" / "steamapps" / "libraryfolders.vdf"
    metadata = inspect_regular_file(libraryfolders, "Steam library configuration")
    original = libraryfolders.read_bytes()
    content_id = str(secrets.randbelow((1 << 62) - 1) + 1)
    rendered, index = render_libraryfolders(original, paths["target"], content_id)
    if index is None:
        return None, None

    backups_dir = base / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(
        tempfile.mkdtemp(prefix=f"removable-library-registration-{stamp}-", dir=backups_dir)
    )
    backup_file = backup / libraryfolders.name
    shutil.copy2(libraryfolders, backup_file, follow_symlinks=False)
    if backup_file.read_bytes() != original:
        raise RuntimeError(f"library configuration backup failed: {backup_file}")
    current = inspect_regular_file(libraryfolders, "Steam library configuration")
    if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise RuntimeError("Steam library configuration changed during registration")
    if libraryfolders.read_bytes() != original:
        raise RuntimeError("Steam library configuration changed during registration")
    atomic_replace(libraryfolders, rendered, stat.S_IMODE(metadata.st_mode))
    return backup, index


def prepare_layout(base, external_parent, storage_root=Path("/storage")):
    inspect_directory(base, "Steam ARM64 base")
    parent = validate_external_parent(external_parent, storage_root)
    source = parent / LIBRARY_NAME
    source.mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps").mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps" / "common").mkdir(mode=0o700, exist_ok=True)
    target = base / "removable-library"
    steamapps_control = base / "removable-library-steamapps"
    compatdata = base / "removable-library-compatdata"
    download_state = base / "removable-library-downloads"
    target.mkdir(mode=0o700, exist_ok=True)
    steamapps_control.mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "common").mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "compatdata").mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "downloading").mkdir(mode=0o700, exist_ok=True)
    compatdata.mkdir(mode=0o700, exist_ok=True)
    download_state.mkdir(mode=0o700, exist_ok=True)
    paths = validate_layout(base, source, storage_root)
    backup = write_config(
        paths["config"], config_bytes(paths["source"]), base / "backups"
    )
    return paths, backup


def load_layout(base, storage_root=Path("/storage")):
    config = base / "config" / CONFIG_NAME
    if inspect_config(config) is None:
        return None
    try:
        payload = json.loads(config.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid removable-library configuration: {config}") from error
    if set(payload) != {"version", "source"} or payload["version"] != 1:
        raise RuntimeError(f"unsupported removable-library configuration: {config}")
    if not isinstance(payload["source"], str) or any(
        character in payload["source"] for character in "\r\n\t\0"
    ):
        raise RuntimeError(f"invalid removable-library source: {config}")
    source = Path(payload["source"])
    if not source.is_absolute():
        raise RuntimeError(f"removable-library source is not absolute: {source}")
    return validate_layout(base, source, storage_root)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--storage-root", default="/storage", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument(
        "--external-parent", default=str(Path.home() / "storage" / "external-1")
    )
    subparsers.add_parser("check")
    subparsers.add_parser("mount-info")
    subparsers.add_parser("register")
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    storage_root = Path(args.storage_root)
    try:
        if args.action == "prepare":
            paths, backup = prepare_layout(
                base, Path(args.external_parent), storage_root
            )
            print(f"Removable Steam library prepared: {paths['source']}")
            print(f"Guest library path: {paths['target']}")
            print(f"Internal Steam control root: {paths['steamapps_control']}")
            print(f"Internal compatdata: {paths['compatdata']}")
            print(f"Internal download state: {paths['download_state']}")
            if backup is not None:
                print(f"Previous configuration backup: {backup}")
            print("With Steam stopped, run register and deploy the launcher before starting Steam.")
            return 0

        paths = load_layout(base, storage_root)
        if args.action == "mount-info":
            if paths is None:
                print("disabled")
            else:
                print(
                    f"{paths['source']}\t{paths['target']}\t"
                    f"{paths['steamapps_control']}\t{paths['external_common']}\t"
                    f"{paths['compatdata']}\t{paths['download_state']}"
                )
            return 0
        if args.action == "register":
            if paths is None:
                raise RuntimeError("prepare the removable library before registration")
            running = find_running_processes()
            if running:
                details = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise RuntimeError(
                    f"refusing to edit Steam libraries while processes are active: {details}"
                )
            backup, index = register_library(base, paths)
            if index is None:
                print(f"Removable Steam library already registered: {paths['target']}")
            else:
                print(f"Registered removable Steam library as entry {index}: {paths['target']}")
                print(f"Previous library configuration backup: {backup}")
            return 0
        if paths is None:
            print("Removable Steam library: disabled")
            return 1
        print(f"Removable Steam library: ready ({paths['source']})")
        print(f"Guest library path: {paths['target']}")
        print(f"Internal Steam control root: {paths['steamapps_control']}")
        print(f"Internal compatdata: {paths['compatdata']}")
        print(f"Internal download state: {paths['download_state']}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"steam-arm64-removable-library: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
