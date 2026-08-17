#!/usr/bin/env python3

"""Prepare Proton ARM64 Wine for Wine's syscall-only preloader on Android."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


ORIGINAL_INTERPRETER = "/lib/ld-linux-aarch64.so.1"
TARGET_RELATIVES = (
    Path("client/steamapps/common/Proton 11.0 (ARM64)/files/bin-arm64/wine"),
    Path("client/steamapps/common/Proton 11.0 (ARM64)/files/bin-arm64/wineserver"),
    Path(
        "client/steamapps/common/Proton 11.0 (ARM64)"
        "/files/lib/wine/aarch64-unix/wine"
    ),
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


def resolved_owned_executable(path: Path, description: str) -> None:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise PrepareError(f"{description} is unavailable: {path}") from error
    regular_owned_file(resolved, description, executable=True)


def run_command(command: list[str], description: str) -> str:
    result = subprocess.run(
        command,
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
        raise PrepareError(f"{description} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def read_interpreter(readelf: Path, target: Path) -> str:
    output = run_command([str(readelf), "-l", str(target)], "readelf")
    matches = re.findall(r"Requesting program interpreter: ([^]]+)", output)
    if len(matches) != 1:
        raise PrepareError(f"cannot identify one ELF interpreter in: {target}")
    return matches[0]


def run_patchelf(command: list[str], loader: Path, target: Path) -> None:
    for path in (loader, target):
        if not re.fullmatch(r"/[A-Za-z0-9._/-]+", str(path)):
            raise PrepareError(f"patchelf runner path is not shell-safe: {path}")
    run_command(
        [*command, "--set-interpreter", str(loader), str(target)], "patchelf"
    )


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
        os.replace(temporary, destination)
    finally:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()


def read_state(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists() and not path.is_symlink():
        return {}
    regular_owned_file(path, "Proton direct Wine state")
    value = json.loads(path.read_text(encoding="utf-8"))
    records = value.get("targets")
    if records is None:
        records = [value]
    if not isinstance(records, list):
        raise PrepareError("Proton direct Wine state has invalid targets")
    result: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise PrepareError("Proton direct Wine state has an invalid record")
        target = record.get("target")
        if not isinstance(target, str) or not target.startswith("/"):
            raise PrepareError("Proton direct Wine state has an invalid target")
        if target in result:
            raise PrepareError("Proton direct Wine state has duplicate targets")
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in record.items()):
            raise PrepareError("Proton direct Wine state has invalid values")
        result[target] = record
    return result


def write_state(
    path: Path, loader: Path, records: dict[str, dict[str, str]]
) -> None:
    write_json_atomic(
        path,
        {
            "interpreter": str(loader),
            "schema_version": "2",
            "targets": [records[target] for target in sorted(records)],
        },
    )


def validate_existing_record(
    record: dict[str, str], target: Path, loader: Path
) -> None:
    if record.get("interpreter") != str(loader):
        raise PrepareError(f"prepared target loader mismatch: {target}")
    if sha256(target) != record.get("patched_sha256"):
        raise PrepareError(f"prepared target hash mismatch: {target}")
    backup = Path(record.get("backup", ""))
    regular_owned_file(backup, "Proton ARM64 executable backup")
    if sha256(backup) != record.get("original_sha256"):
        raise PrepareError(f"Proton ARM64 executable backup hash mismatch: {backup}")


def backup_name(relative: Path, original_hash: str) -> str:
    identity = hashlib.sha256(str(relative).encode("utf-8")).hexdigest()[:12]
    return f"{relative.name}-{identity}-{original_hash}.original"


def patch_target(
    target: Path,
    relative: Path,
    loader: Path,
    patchelf: list[str],
    readelf: Path,
    backup_root: Path,
) -> dict[str, str]:
    original_hash = sha256(target)
    backup = backup_root / backup_name(relative, original_hash)
    install_backup(target, backup, original_hash)

    if backup_root.stat().st_dev != target.parent.stat().st_dev:
        raise PrepareError("Proton executable backup and target are on different filesystems")
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{target.name}.direct.", dir=backup_root
    )
    os.close(descriptor)
    staged = Path(staged_name)
    try:
        shutil.copy2(target, staged)
        original_mode = stat.S_IMODE(target.stat().st_mode)
        os.chmod(staged, original_mode | stat.S_IWUSR)
        run_patchelf(patchelf, loader, staged)
        if read_interpreter(readelf, staged) != str(loader):
            raise PrepareError(
                f"staged Proton executable interpreter verification failed: {target}"
            )
        os.chmod(staged, original_mode)
        patched_hash = sha256(staged)
        os.replace(staged, target)
    finally:
        if staged.exists() and not staged.is_symlink():
            staged.unlink()

    if sha256(target) != patched_hash:
        raise PrepareError(f"installed Proton executable hash verification failed: {target}")
    return {
        "backup": str(backup),
        "interpreter": str(loader),
        "original_sha256": original_hash,
        "patched_sha256": patched_hash,
        "target": str(target),
    }


def prepare(
    base: Path,
    loader: Path,
    patchelf: list[str],
    readelf: Path,
) -> None:
    regular_owned_file(loader, "tgcompat glibc loader", executable=True)
    resolved_owned_executable(readelf, "readelf")
    backup_root = base / "backups/proton-direct-wine"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if backup_root.is_symlink() or backup_root.stat().st_uid != os.geteuid():
        raise PrepareError(f"unsafe Proton Wine backup directory: {backup_root}")
    state_path = backup_root / "state.json"
    records = read_state(state_path)
    for relative in TARGET_RELATIVES:
        target = base / relative
        regular_owned_file(target, "Proton ARM64 executable", executable=True)
        interpreter = read_interpreter(readelf, target)
        if interpreter == str(loader):
            record = records.get(str(target))
            if record is None:
                raise PrepareError(f"prepared target has no restore record: {target}")
            validate_existing_record(record, target, loader)
            print(f"Proton direct executable already prepared: {target}")
            continue
        if interpreter != ORIGINAL_INTERPRETER:
            raise PrepareError(
                f"refusing unexpected Proton executable interpreter: {target}: {interpreter}"
            )
        record = patch_target(
            target, relative, loader, patchelf, readelf, backup_root
        )
        records[str(target)] = record
        write_state(state_path, loader, records)
        print(f"Prepared Proton direct executable: {target}")
        print(f"Original backup: {record['backup']}")

    write_state(state_path, loader, records)


def check(base: Path, loader: Path, readelf: Path) -> None:
    regular_owned_file(loader, "tgcompat glibc loader", executable=True)
    resolved_owned_executable(readelf, "readelf")
    records = read_state(base / "backups/proton-direct-wine/state.json")
    for relative in TARGET_RELATIVES:
        target = base / relative
        regular_owned_file(target, "Proton ARM64 executable", executable=True)
        interpreter = read_interpreter(readelf, target)
        if interpreter != str(loader):
            raise PrepareError(
                f"Proton direct executable is not prepared: {target}: {interpreter}"
            )
        record = records.get(str(target))
        if record is None:
            raise PrepareError(f"prepared target has no restore record: {target}")
        validate_existing_record(record, target, loader)
        print(f"Proton direct executable check: PASS target={target}")


def restore(base: Path, readelf: Path) -> None:
    state_path = base / "backups/proton-direct-wine/state.json"
    records = read_state(state_path)
    for relative in TARGET_RELATIVES:
        target = base / relative
        regular_owned_file(target, "Proton ARM64 executable", executable=True)
        record = records.get(str(target))
        if record is None:
            if read_interpreter(readelf, target) == ORIGINAL_INTERPRETER:
                print(f"Proton ARM64 executable already original: {target}")
                continue
            raise PrepareError(f"prepared target has no restore record: {target}")
        current_hash = sha256(target)
        if current_hash == record.get("original_sha256"):
            if read_interpreter(readelf, target) != ORIGINAL_INTERPRETER:
                raise PrepareError(f"original target interpreter mismatch: {target}")
            print(f"Proton ARM64 executable already restored: {target}")
            continue
        if current_hash != record.get("patched_sha256"):
            raise PrepareError(f"refusing to restore over changed executable: {target}")
        backup = Path(record.get("backup", ""))
        regular_owned_file(backup, "Proton ARM64 executable backup")
        if sha256(backup) != record.get("original_sha256"):
            raise PrepareError(f"Proton ARM64 executable backup hash mismatch: {backup}")
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f".{target.name}.restore.", dir=target.parent
        )
        os.close(descriptor)
        staged = Path(staged_name)
        try:
            shutil.copy2(backup, staged)
            os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
            os.replace(staged, target)
        finally:
            if staged.exists() and not staged.is_symlink():
                staged.unlink()
        if read_interpreter(readelf, target) != ORIGINAL_INTERPRETER:
            raise PrepareError(
                f"restored Proton executable interpreter verification failed: {target}"
            )
        print(f"Restored Proton ARM64 executable: {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("prepare", "check", "restore"), default="prepare")
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument(
        "--loader",
        default=str(Path.home() / ".local/share/tgcompat/glibc/current/lib/ld-linux-aarch64.so.1"),
    )
    parser.add_argument("--patchelf")
    parser.add_argument("--readelf")
    arguments = parser.parse_args()
    try:
        base = Path(arguments.base).resolve(strict=True)
        loader = Path(os.path.abspath(os.path.expanduser(arguments.loader)))
        loader.resolve(strict=True)
        prefix = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
        readelf = Path(
            os.path.abspath(
                os.path.expanduser(str(arguments.readelf or prefix / "bin/readelf"))
            )
        )
        resolved_owned_executable(readelf, "readelf")
        if arguments.patchelf:
            patchelf_path = Path(arguments.patchelf).resolve(strict=True)
            regular_owned_file(patchelf_path, "patchelf", executable=True)
            patchelf = [str(patchelf_path)]
        else:
            runner = (prefix / "bin/grun").resolve(strict=True)
            regular_owned_file(runner, "glibc-runner", executable=True)
            patchelf = [str(runner), "-s", "patchelf"]
        if arguments.action == "prepare":
            prepare(base, loader, patchelf, readelf)
        elif arguments.action == "check":
            check(base, loader, readelf)
        else:
            restore(base, readelf)
    except (PrepareError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"prepare-proton-direct-wine: {error}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
