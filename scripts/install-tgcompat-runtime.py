#!/usr/bin/env python3
"""Build, verify, and receipt the locked native tgcompat runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/tgcompat-runtime-lock.json"
RECEIPT = ".steamclienttermux-tgcompat-receipt.json"


class TgcompatError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(path: Path, payload: dict[str, object]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    except BaseException:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def read_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise TgcompatError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TgcompatError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise TgcompatError(f"{label} is not a JSON object")
    return value


def safe_relative_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\x00" in value
        or "\\" in value
        or any(part in ("", ".", "..") for part in path.parts)
        or path.as_posix() != value
    ):
        return None
    return value


def load_lock(path: Path) -> dict[str, object]:
    lock = read_object(path, "tgcompat lock")
    try:
        source = lock["source"]
        build = lock["build"]
        artifacts = build["artifacts"]
        required_files = build["required_files"]
        valid = (
            lock["schema_version"] == 1
            and isinstance(lock["profile_id"], str)
            and lock["platform"]["architectures"] == ["aarch64"]
            and source["repository"].startswith("https://github.com/")
            and source["repository"].endswith(".git")
            and len(source["commit"]) == 40
            and all(character in "0123456789abcdef" for character in source["commit"])
            and build["script"] == "scripts/build-release.sh"
            and build["profile"] == "native"
            and build["checks"] is True
            and 1 <= build["maximum_jobs"] <= 32
            and isinstance(artifacts, list)
            and len(artifacts) == 6
            and len(set(artifacts)) == len(artifacts)
            and all(safe_relative_path(value) is not None for value in artifacts)
            and isinstance(required_files, list)
            and required_files == ["scripts/tgcompat-session.sh"]
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise TgcompatError("tgcompat lock is malformed")
    return lock


def run(arguments: list[str], cwd: Path, *, capture: bool = False) -> str:
    environment = os.environ.copy()
    for name in (
        "AR",
        "CC",
        "CDPATH",
        "CFLAGS",
        "CPPFLAGS",
        "GLIBC_LD_LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "LDFLAGS",
        "MAKEFLAGS",
        "MFLAGS",
        "STRIP",
        "TGCOMPAT_BUILD_JOBS",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        env=environment,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def verify_git_source(destination: Path, lock: dict[str, object]) -> None:
    source = lock["source"]
    assert isinstance(source, dict)
    if not destination.is_dir() or destination.is_symlink():
        raise TgcompatError(f"tgcompat source is missing or unsafe: {destination}")
    if (destination / ".git").is_symlink() or not (destination / ".git").is_dir():
        raise TgcompatError("tgcompat Git metadata is missing or unsafe")
    if run(["git", "rev-parse", "HEAD"], destination, capture=True) != source["commit"]:
        raise TgcompatError("tgcompat source commit does not match the lock")
    if run(["git", "remote", "get-url", "origin"], destination, capture=True) != source["repository"]:
        raise TgcompatError("tgcompat source origin does not match the lock")
    tracked = run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        destination,
        capture=True,
    )
    if tracked:
        raise TgcompatError("tgcompat tracked source is dirty")
    modes = run(["git", "ls-files", "-s"], destination, capture=True)
    if any(line.startswith("120000 ") for line in modes.splitlines()):
        raise TgcompatError("tgcompat source contains a tracked symlink")


def artifact_records(destination: Path, lock: dict[str, object]) -> dict[str, object]:
    build = lock["build"]
    assert isinstance(build, dict)
    records: dict[str, object] = {}
    for relative in [*build["artifacts"], *build["required_files"]]:
        path = destination / str(relative)
        if not path.is_file() or path.is_symlink():
            raise TgcompatError(f"tgcompat output is missing or unsafe: {relative}")
        size = path.stat().st_size
        if size <= 0 or size > 16 * 1024 * 1024:
            raise TgcompatError(f"tgcompat output has an invalid size: {relative}")
        if relative in build["artifacts"] and not os.access(path, os.X_OK):
            raise TgcompatError(f"tgcompat output is not executable: {relative}")
        records[str(relative)] = {"size": size, "sha256": sha256_file(path)}
    return records


def validate_install(destination: Path, lock: dict[str, object]) -> dict[str, object]:
    verify_git_source(destination, lock)
    receipt = read_object(destination / RECEIPT, "tgcompat receipt")
    actual = artifact_records(destination, lock)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "tgcompat-native-runtime"
        or receipt.get("profile_id") != lock["profile_id"]
        or receipt.get("source_commit") != lock["source"]["commit"]
        or receipt.get("artifacts") != actual
        or not isinstance(receipt.get("build_seconds"), (int, float))
        or receipt["build_seconds"] < 0
    ):
        raise TgcompatError("installed tgcompat runtime does not match its receipt")
    return receipt


def clone_source(staging: Path, lock: dict[str, object]) -> None:
    source = lock["source"]
    assert isinstance(source, dict)
    staging.mkdir(mode=0o700)
    run(["git", "init", "-q"], staging)
    run(["git", "remote", "add", "origin", str(source["repository"])], staging)
    run(
        ["git", "fetch", "--depth", "1", "origin", str(source["commit"])],
        staging,
    )
    run(["git", "checkout", "-q", "--detach", str(source["commit"])], staging)
    verify_git_source(staging, lock)


def update_selector(runtime_root: Path, commit: str) -> None:
    selector = runtime_root / "current"
    if selector.exists() and not selector.is_symlink():
        raise TgcompatError(f"tgcompat selector is not a symlink: {selector}")
    if selector.is_symlink():
        existing = os.readlink(selector)
        if (
            PurePosixPath(existing).name != existing
            or len(existing) != 40
            or not (runtime_root / existing).is_dir()
        ):
            raise TgcompatError(f"tgcompat selector is unsafe: {selector}")
    temporary = runtime_root / f".current.{secrets.token_hex(8)}"
    os.symlink(commit, temporary)
    os.replace(temporary, selector)
    fsync_directory(runtime_root)


def install(base: Path, lock: dict[str, object], jobs: int | None = None) -> tuple[str, dict[str, object]]:
    if not base.is_absolute():
        raise TgcompatError("--base must be absolute")
    if base.exists():
        if not base.is_dir() or base.is_symlink():
            raise TgcompatError(f"unsafe base directory: {base}")
    else:
        base.mkdir(mode=0o700)
    runtime_root = base / "tgcompat"
    if runtime_root.exists():
        if not runtime_root.is_dir() or runtime_root.is_symlink():
            raise TgcompatError(f"unsafe tgcompat runtime directory: {runtime_root}")
    else:
        runtime_root.mkdir(mode=0o700)
    commit = str(lock["source"]["commit"])
    destination = runtime_root / commit
    if destination.exists() or destination.is_symlink():
        receipt = validate_install(destination, lock)
        update_selector(runtime_root, commit)
        return "already-ready", receipt

    maximum_jobs = int(lock["build"]["maximum_jobs"])
    selected_jobs = min(jobs or (os.cpu_count() or 1), maximum_jobs)
    if selected_jobs < 1:
        raise TgcompatError("build jobs must be positive")
    staging = runtime_root / f".{commit}.staging.{secrets.token_hex(8)}"
    started = time.monotonic()
    try:
        clone_source(staging, lock)
        run(
            [
                str(staging / str(lock["build"]["script"])),
                "--native",
                "--check",
                "--jobs",
                str(selected_jobs),
            ],
            staging,
        )
        verify_git_source(staging, lock)
        artifacts = artifact_records(staging, lock)
        receipt = {
            "schema_version": 1,
            "kind": "tgcompat-native-runtime",
            "profile_id": lock["profile_id"],
            "source_repository": lock["source"]["repository"],
            "source_commit": commit,
            "build_profile": "native",
            "build_checks": True,
            "build_jobs": selected_jobs,
            "build_seconds": round(time.monotonic() - started, 3),
            "artifacts": artifacts,
        }
        write_json(staging / RECEIPT, receipt)
        os.replace(staging, destination)
        fsync_directory(runtime_root)
    except BaseException:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    receipt = validate_install(destination, lock)
    update_selector(runtime_root, commit)
    return "installed", receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--jobs", type=int)
    arguments = parser.parse_args()
    try:
        lock = load_lock(arguments.lock.resolve())
        result, receipt = install(arguments.base.resolve(), lock, arguments.jobs)
        print(f"TGCOMPAT_RUNTIME={result}")
        print(f"TGCOMPAT_COMMIT={lock['source']['commit']}")
        print(f"TGCOMPAT_BUILD_SECONDS={receipt['build_seconds']}")
        return 0
    except (OSError, subprocess.CalledProcessError, TgcompatError) as error:
        print(f"install-tgcompat-runtime: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
