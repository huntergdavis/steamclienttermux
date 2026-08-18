#!/usr/bin/env python3

"""Apply the guarded Tomb Raider process-affinity topology fix."""

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


SOURCE_SHA256 = "f36b8dd2bd74d48c14bf910ad9bd4ac9f4024433523ffc7e46d5c85c3dd618f5"
PATCHED_SHA256 = "4f311ecb46d6eb8f781d0c6a5e2fac6ee6a6224d19f23a79e7173b8f260807ad"
PATCH_OFFSET = 0x186CAF
SOURCE_BYTES = bytes.fromhex("3b45e87407")
PATCHED_BYTES = bytes.fromhex("8945e8eb07")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_game(path):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"game is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"game has an unexpected link count: {path}")
    return metadata


def classify(data, source_sha=SOURCE_SHA256, patched_sha=PATCHED_SHA256):
    actual = digest(data)
    signature = data[PATCH_OFFSET : PATCH_OFFSET + len(SOURCE_BYTES)]
    if actual == source_sha and signature == SOURCE_BYTES:
        return "disabled"
    if actual == patched_sha and signature == PATCHED_BYTES:
        return "enabled"
    raise RuntimeError(
        "unsupported Tomb Raider executable state: "
        f"sha256={actual}, patch-bytes={signature.hex()}"
    )


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
            raise OSError("zero-byte game write")
        offset += written


def private_backups_directory(path):
    if path.exists():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"backup root is unsafe: {path}")
    else:
        path.mkdir(parents=True, mode=0o700)


def backup_game(game, backups_dir, original, state):
    private_backups_directory(backups_dir)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(
        tempfile.mkdtemp(
            prefix=f"tombraider-cpu-topology-{state}-{stamp}-",
            dir=backups_dir,
        )
    )
    os.chmod(backup_dir, 0o700)
    backup = backup_dir / game.name
    shutil.copy2(game, backup, follow_symlinks=False)
    if backup.read_bytes() != original:
        raise RuntimeError("game backup verification failed")
    return backup


def install_bytes(game, metadata, rendered):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{game.name}.cpu-topology-", dir=game.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        write_all(descriptor, rendered)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError("staged game verification failed")
        os.replace(temporary, game)
        fsync_directory(game.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    if game.read_bytes() != rendered:
        raise RuntimeError("installed game verification failed")


def apply(
    game,
    backups_dir,
    enable,
    source_sha=SOURCE_SHA256,
    patched_sha=PATCHED_SHA256,
):
    metadata = inspect_game(game)
    original = game.read_bytes()
    current = classify(original, source_sha, patched_sha)
    target = "enabled" if enable else "disabled"
    if current == target:
        return None, current, digest(original)

    expected = SOURCE_BYTES if enable else PATCHED_BYTES
    replacement = PATCHED_BYTES if enable else SOURCE_BYTES
    if original[PATCH_OFFSET : PATCH_OFFSET + len(expected)] != expected:
        raise RuntimeError("game changed after validation; refusing to edit")
    backup = backup_game(game, backups_dir, original, current)
    current_metadata = inspect_game(game)
    if (
        current_metadata.st_dev != metadata.st_dev
        or current_metadata.st_ino != metadata.st_ino
        or game.read_bytes() != original
    ):
        raise RuntimeError("game changed during backup; refusing to replace it")
    rendered = bytearray(original)
    rendered[PATCH_OFFSET : PATCH_OFFSET + len(expected)] = replacement
    expected_sha = patched_sha if enable else source_sha
    if digest(rendered) != expected_sha:
        raise RuntimeError("rendered game SHA-256 does not match the guarded target")
    install_bytes(game, metadata, rendered)
    installed = game.read_bytes()
    installed_state = classify(installed, source_sha, patched_sha)
    if installed_state != target:
        raise RuntimeError("installed game state does not match the requested target")
    return backup, installed_state, digest(installed)


def find_running_game(game, proc_root=Path("/proc")):
    target = os.fsencode(str(game))
    matches = []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            arguments = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        if target in arguments:
            matches.append(int(process.name))
    return sorted(matches)


def main():
    home = Path.home()
    parser = argparse.ArgumentParser(
        description="Apply or restore Tomb Raider's guarded CPU-topology fix"
    )
    parser.add_argument("--base", default=str(home / "steam-arm64"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", action="store_true")
    action.add_argument("--disable", action="store_true")
    action.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    base = Path(arguments.base).resolve()
    game = base / "removable-library/steamapps/common/Tomb Raider/TombRaider.exe"
    backups = base / "backups"
    try:
        metadata = inspect_game(game)
        del metadata
        data = game.read_bytes()
        current = classify(data)
        if arguments.check:
            print(
                f"Tomb Raider CPU topology fix: {current}; "
                f"SHA-256 {digest(data)}"
            )
            return 0
        running = find_running_game(game)
        if running:
            raise RuntimeError(
                "refusing while Tomb Raider is active: "
                + ", ".join(str(pid) for pid in running)
            )
        backup, installed, installed_sha = apply(
            game, backups, arguments.enable
        )
        print(f"Tomb Raider CPU topology fix: {installed}")
        print(f"Backup: {backup}")
        print(f"Installed SHA-256: {installed_sha}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-tombraider-cpu-topology: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
