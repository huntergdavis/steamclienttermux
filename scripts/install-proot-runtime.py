#!/usr/bin/env python3
"""Build, verify, and atomically install the locked patched PRoot runtime."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
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
DEFAULT_LOCK = REPO_ROOT / "config/proot-runtime-lock.json"
DEFAULT_BUILDER = REPO_ROOT / "scripts/build-proot.sh"
HEX = frozenset("0123456789abcdef")


class ProotError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and set(value) <= HEX


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
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def read_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ProotError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProotError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise ProotError(f"{label} is not a JSON object")
    return value


def safe_relative(value: object) -> bool:
    if not isinstance(value, str):
        return False
    path = PurePosixPath(value)
    return (
        value == path.as_posix()
        and not path.is_absolute()
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def load_lock(path: Path) -> dict[str, object]:
    lock = read_object(path, "PRoot runtime lock")
    try:
        build = lock["build"]
        runtime = lock["runtime"]
        source = lock["source"]
        patches = lock["patches"]
        filenames = [record["filename"] for record in patches]
        valid = (
            lock["schema_version"] == 1
            and isinstance(lock["profile_id"], str)
            and lock["platform"]["architectures"] == ["aarch64"]
            and lock["platform"]["environment"] == "official-termux"
            and lock["platform"]["storage"] == "private-internal"
            and source["repository"] == "https://github.com/termux/proot.git"
            and is_hex(source["commit"], 40)
            and build["profile"] == "native"
            and build["enable_noderef_fastpath"] is False
            and build["script"] == "scripts/build-proot.sh"
            and is_hex(build["script_sha256"], 64)
            and isinstance(patches, list)
            and len(patches) == 11
            and len(filenames) == len(set(filenames))
            and all(
                PurePosixPath(record["filename"]).name == record["filename"]
                and record["filename"].startswith("proot-")
                and record["filename"].endswith(".patch")
                and is_hex(record["sha256"], 64)
                for record in patches
            )
            and runtime["destination"] == "src/proot-production"
            and runtime["binary"] == "src/proot"
            and runtime["stamp"] == ".steamclienttermux-patchset"
            and runtime["receipt"] == ".steamclienttermux-proot-receipt.json"
            and all(safe_relative(runtime[name]) for name in ("destination", "binary"))
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ProotError("PRoot runtime lock is malformed")
    return lock


def require_private_path(path: Path, home: Path, label: str) -> None:
    if not path.is_absolute() or path in (Path("/"), home) or not path.is_relative_to(home):
        raise ProotError(f"{label} must be below the private Termux HOME: {path}")


def clean_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PROOT_BUILD_PROFILE",
        "PROOT_BUILD_JOBS",
        "PROOT_ENABLE_NODEREF_FASTPATH",
    ):
        environment.pop(name, None)
    environment["LC_ALL"] = "C"
    if extra:
        environment.update(extra)
    return environment


def run_output(arguments: list[str], cwd: Path) -> str:
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=clean_environment(),
    ).stdout.strip()


def verify_inputs(lock: dict[str, object], builder: Path, repo_root: Path) -> str:
    if not builder.is_file() or builder.is_symlink() or not os.access(builder, os.X_OK):
        raise ProotError(f"PRoot builder is missing or unsafe: {builder}")
    builder_sha = sha256_file(builder)
    if builder_sha != lock["build"]["script_sha256"]:
        raise ProotError("PRoot builder does not match the runtime lock")
    for record in lock["patches"]:
        patch = repo_root / "patches" / record["filename"]
        if not patch.is_file() or patch.is_symlink() or sha256_file(patch) != record["sha256"]:
            raise ProotError(f"PRoot patch does not match the runtime lock: {record['filename']}")
    return builder_sha


def parse_stamp(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink():
        raise ProotError(f"PRoot patch stamp is missing or unsafe: {path}")
    records: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in records:
            raise ProotError("PRoot patch stamp is malformed")
        records[key] = value
    required = {
        "commit",
        "patchset_sha256",
        "diff_sha256",
        "patches",
        "build_profile",
        "build_options_sha256",
        "proot_sha256",
    }
    if set(records) != required or any("\x00" in value for value in records.values()):
        raise ProotError("PRoot patch stamp is malformed")
    return records


def installation_identity(root: Path, lock: dict[str, object]) -> dict[str, object]:
    runtime = lock["runtime"]
    binary = root / runtime["binary"]
    stamp_path = root / runtime["stamp"]
    if root.is_symlink() or not root.is_dir():
        raise ProotError(f"PRoot installation is missing or unsafe: {root}")
    if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
        raise ProotError(f"PRoot binary is missing or unsafe: {binary}")
    stamp = parse_stamp(stamp_path)
    commit = run_output(["git", "-C", str(root), "rev-parse", "HEAD"], root)
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--binary"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        env=clean_environment(),
    ).stdout
    binary_sha = sha256_file(binary)
    expected_patches = " ".join(record["filename"] for record in lock["patches"])
    valid = (
        commit == lock["source"]["commit"]
        and stamp["commit"] == commit
        and stamp["patches"] == expected_patches
        and stamp["build_profile"] == lock["build"]["profile"]
        and is_hex(stamp["patchset_sha256"], 64)
        and is_hex(stamp["build_options_sha256"], 64)
        and stamp["diff_sha256"] == hashlib.sha256(diff).hexdigest()
        and stamp["proot_sha256"] == binary_sha
    )
    if not valid:
        raise ProotError("installed PRoot does not match its source and patch stamp")
    subprocess.run(
        [str(binary), "--version"],
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=clean_environment(),
        timeout=10,
    )
    return {
        "source_commit": commit,
        "source_diff_sha256": stamp["diff_sha256"],
        "patchset_sha256": stamp["patchset_sha256"],
        "build_options_sha256": stamp["build_options_sha256"],
        "binary_sha256": binary_sha,
        "binary_size": binary.stat().st_size,
    }


def validate_install(root: Path, lock: dict[str, object], lock_sha: str, builder_sha: str) -> dict[str, object]:
    identity = installation_identity(root, lock)
    receipt = read_object(root / lock["runtime"]["receipt"], "PRoot runtime receipt")
    expected = {
        "schema_version": 1,
        "kind": "steam-arm64-patched-proot",
        "profile_id": lock["profile_id"],
        "lock_sha256": lock_sha,
        "builder_sha256": builder_sha,
        **identity,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ProotError("installed PRoot does not match its receipt")
    return receipt


def install(
    base: Path,
    prefix: Path,
    lock_path: Path,
    builder: Path,
    lock: dict[str, object],
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
    jobs: int | None = None,
) -> tuple[str, dict[str, object]]:
    home = (home or Path.home()).resolve(strict=True)
    base = base.resolve()
    prefix = prefix.resolve(strict=True)
    lock_path = lock_path.resolve(strict=True)
    builder = builder.resolve(strict=True)
    require_private_path(base, home, "--base")
    if prefix == Path("/") or not prefix.is_dir() or prefix.is_symlink():
        raise ProotError(f"unsafe Termux prefix: {prefix}")
    if jobs is None:
        jobs = max(1, min(8, os.cpu_count() or 1))
    if jobs < 1 or jobs > 64:
        raise ProotError("--jobs must be between 1 and 64")
    lock_sha = sha256_file(lock_path)
    builder_sha = verify_inputs(lock, builder, repo_root)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_root = base / "src"
    source_root.mkdir(mode=0o700, exist_ok=True)
    if source_root.is_symlink() or not source_root.is_dir():
        raise ProotError(f"unsafe PRoot source directory: {source_root}")
    destination = base / lock["runtime"]["destination"]
    with (source_root / ".proot-install.lock").open("a+b") as lock_stream:
        os.fchmod(lock_stream.fileno(), 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if destination.exists() or destination.is_symlink():
            receipt = validate_install(destination, lock, lock_sha, builder_sha)
            return "already-ready", receipt
        started = time.monotonic()
        temporary = Path(tempfile.mkdtemp(prefix=".proot-stage.", dir=source_root))
        staged = temporary / "runtime"
        try:
            subprocess.run(
                [str(prefix / "bin/bash"), str(builder), str(staged)],
                cwd=repo_root,
                check=True,
                env=clean_environment(
                    {
                        "PREFIX": str(prefix),
                        "PROOT_BUILD_PROFILE": "native",
                        "PROOT_BUILD_JOBS": str(jobs),
                        "PROOT_ENABLE_NODEREF_FASTPATH": "0",
                    }
                ),
            )
            identity = installation_identity(staged, lock)
            receipt = {
                "schema_version": 1,
                "kind": "steam-arm64-patched-proot",
                "profile_id": lock["profile_id"],
                "lock_sha256": lock_sha,
                "builder_sha256": builder_sha,
                **identity,
                "install_seconds": round(time.monotonic() - started, 3),
            }
            write_json(staged / lock["runtime"]["receipt"], receipt)
            if staged.stat().st_dev != source_root.stat().st_dev:
                raise ProotError("staged PRoot and destination are on different filesystems")
            os.replace(staged, destination)
            fsync_directory(source_root)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        receipt = validate_install(destination, lock, lock_sha, builder_sha)
        return "installed", receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--builder", type=Path, default=DEFAULT_BUILDER)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("PREFIX", "")))
    parser.add_argument("--jobs", type=int)
    arguments = parser.parse_args()
    try:
        lock_path = arguments.lock.resolve()
        lock = load_lock(lock_path)
        result, receipt = install(
            arguments.base,
            arguments.prefix,
            lock_path,
            arguments.builder,
            lock,
            jobs=arguments.jobs,
        )
        print(f"PROOT_RUNTIME={result}")
        print(f"PROOT_BINARY_SHA256={receipt['binary_sha256']}")
        print(f"PROOT_INSTALL_SECONDS={receipt['install_seconds']}")
        return 0
    except (ProotError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"install-proot-runtime: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
