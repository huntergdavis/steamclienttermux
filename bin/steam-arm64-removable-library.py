#!/usr/bin/env python3

"""Prepare and validate an optional removable Steam game-data library."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


CONFIG_NAME = "removable-library.json"
LIBRARY_NAME = "steam-arm64-library"
UUID_PATTERN = re.compile(r"^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")


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
        "compatdata": base / "removable-library-compatdata",
        "placeholder": source / "steamapps" / "compatdata",
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
    inspect_directory(paths["compatdata"], "internal removable-library compatdata")
    inspect_directory(
        paths["placeholder"], "external compatdata mount point", require_empty=True
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
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(rendered):
            written = os.write(descriptor, rendered[offset:])
            if written == 0:
                raise OSError("zero-byte configuration write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError(f"staged configuration verification failed: {temporary}")
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
        raise RuntimeError(f"installed configuration verification failed: {path}")
    return backup


def prepare_layout(base, external_parent, storage_root=Path("/storage")):
    inspect_directory(base, "Steam ARM64 base")
    parent = validate_external_parent(external_parent, storage_root)
    source = parent / LIBRARY_NAME
    source.mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps").mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps" / "compatdata").mkdir(mode=0o700, exist_ok=True)
    target = base / "removable-library"
    compatdata = base / "removable-library-compatdata"
    target.mkdir(mode=0o700, exist_ok=True)
    compatdata.mkdir(mode=0o700, exist_ok=True)
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
            print(f"Internal compatdata: {paths['compatdata']}")
            if backup is not None:
                print(f"Previous configuration backup: {backup}")
            print("Restart Steam, add the guest library path, and use it only for Windows games.")
            return 0

        paths = load_layout(base, storage_root)
        if args.action == "mount-info":
            if paths is None:
                print("disabled")
            else:
                print(
                    f"{paths['source']}\t{paths['target']}\t{paths['compatdata']}"
                )
            return 0
        if paths is None:
            print("Removable Steam library: disabled")
            return 1
        print(f"Removable Steam library: ready ({paths['source']})")
        print(f"Guest library path: {paths['target']}")
        print(f"Internal compatdata: {paths['compatdata']}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"steam-arm64-removable-library: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
