#!/usr/bin/env python3

"""Prepare Proton ARM64 Wine for Wine's syscall-only preloader on Android."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


ORIGINAL_INTERPRETER = "/lib/ld-linux-aarch64.so.1"
TARGET_RELATIVE = Path(
    "client/steamapps/common/Proton 11.0 (ARM64)/files/lib/wine/aarch64-unix/wine"
)


class PrepareError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_owned_file(path: Path, description: str, executable: bool = False) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise PrepareError(f"{description} is unavailable: {path}") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise PrepareError(f"{description} is not a regular file: {path}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        raise PrepareError(f"{description} has unsafe ownership or mode: {path}")
    if executable and not os.access(path, os.X_OK):
        raise PrepareError(f"{description} is not executable: {path}")


def run_patchelf(patchelf: Path, *arguments: str) -> str:
    result = subprocess.run(
        [str(patchelf), *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"LD_PRELOAD", "LD_LIBRARY_PATH", "GLIBC_LD_LIBRARY_PATH"}
        },
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PrepareError(f"patchelf failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def write_json_atomic(path: Path, value: dict[str, str]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".state.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def install_backup(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists() or destination.is_symlink():
        regular_owned_file(destination, "existing Proton Wine backup")
        if sha256(destination) != expected_hash:
            raise PrepareError(f"existing backup hash mismatch: {destination}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=".backup.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        os.chmod(temporary, 0o600)
        if sha256(temporary) != expected_hash:
            raise PrepareError("staged Proton Wine backup hash mismatch")
        os.link(temporary, destination)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def prepare(base: Path, loader: Path, patchelf: Path) -> None:
    target = base / TARGET_RELATIVE
    regular_owned_file(target, "Proton ARM64 Wine", executable=True)
    regular_owned_file(loader, "tgcompat glibc loader", executable=True)
    regular_owned_file(patchelf, "patchelf", executable=True)
    interpreter = run_patchelf(patchelf, "--print-interpreter", str(target))
    if interpreter == str(loader):
        print(f"Proton direct Wine already prepared: {target}")
        return
    if interpreter != ORIGINAL_INTERPRETER:
        raise PrepareError(f"refusing unexpected Wine interpreter: {interpreter}")

    original_hash = sha256(target)
    backup_root = base / "backups/proton-direct-wine"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_root.is_symlink() or backup_root.stat().st_uid != os.geteuid():
        raise PrepareError(f"unsafe Proton Wine backup directory: {backup_root}")
    backup = backup_root / f"wine-{original_hash}.original"
    install_backup(target, backup, original_hash)

    descriptor, staged_name = tempfile.mkstemp(prefix=".wine.direct.", dir=target.parent)
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        shutil.copy2(target, staged)
        run_patchelf(patchelf, "--set-interpreter", str(loader), str(staged))
        if run_patchelf(patchelf, "--print-interpreter", str(staged)) != str(loader):
            raise PrepareError("staged Proton Wine interpreter verification failed")
        os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
        patched_hash = sha256(staged)
        os.replace(staged, target)
    finally:
        if staged.exists() and not staged.is_symlink():
            staged.unlink()

    if sha256(target) != patched_hash:
        raise PrepareError("installed Proton Wine hash verification failed")
    write_json_atomic(
        backup_root / "state.json",
        {
            "backup": str(backup),
            "interpreter": str(loader),
            "original_sha256": original_hash,
            "patched_sha256": patched_hash,
            "target": str(target),
        },
    )
    print(f"Prepared Proton direct Wine: {target}")
    print(f"Original backup: {backup}")


def check(base: Path, loader: Path, patchelf: Path) -> None:
    target = base / TARGET_RELATIVE
    regular_owned_file(target, "Proton ARM64 Wine", executable=True)
    regular_owned_file(loader, "tgcompat glibc loader", executable=True)
    regular_owned_file(patchelf, "patchelf", executable=True)
    interpreter = run_patchelf(patchelf, "--print-interpreter", str(target))
    if interpreter != str(loader):
        raise PrepareError(f"Proton direct Wine is not prepared: {interpreter}")
    print(f"Proton direct Wine check: PASS interpreter={interpreter}")


def restore(base: Path, patchelf: Path) -> None:
    target = base / TARGET_RELATIVE
    state_path = base / "backups/proton-direct-wine/state.json"
    regular_owned_file(target, "Proton ARM64 Wine", executable=True)
    regular_owned_file(state_path, "Proton direct Wine state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("target") != str(target):
        raise PrepareError("Proton direct Wine state target mismatch")
    patched_hash = state.get("patched_sha256", "")
    if sha256(target) != patched_hash:
        raise PrepareError("refusing to restore over changed Proton Wine")
    backup = Path(state.get("backup", ""))
    regular_owned_file(backup, "Proton ARM64 Wine backup")
    if sha256(backup) != state.get("original_sha256"):
        raise PrepareError("Proton ARM64 Wine backup hash mismatch")
    descriptor, staged_name = tempfile.mkstemp(prefix=".wine.restore.", dir=target.parent)
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        shutil.copy2(backup, staged)
        os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
        os.replace(staged, target)
    finally:
        if staged.exists() and not staged.is_symlink():
            staged.unlink()
    if run_patchelf(patchelf, "--print-interpreter", str(target)) != ORIGINAL_INTERPRETER:
        raise PrepareError("restored Proton Wine interpreter verification failed")
    print(f"Restored Proton ARM64 Wine: {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("prepare", "check", "restore"), default="prepare")
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument(
        "--loader",
        default=str(Path.home() / ".local/share/tgcompat/glibc/current/lib/ld-linux-aarch64.so.1"),
    )
    parser.add_argument(
        "--patchelf",
        default=os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        + "/glibc/bin/patchelf",
    )
    arguments = parser.parse_args()
    try:
        base = Path(arguments.base).resolve(strict=True)
        loader = Path(os.path.abspath(os.path.expanduser(arguments.loader)))
        loader.resolve(strict=True)
        patchelf = Path(arguments.patchelf).resolve(strict=True)
        if arguments.action == "prepare":
            prepare(base, loader, patchelf)
        elif arguments.action == "check":
            check(base, loader, patchelf)
        else:
            restore(base, patchelf)
    except (PrepareError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"prepare-proton-direct-wine: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
