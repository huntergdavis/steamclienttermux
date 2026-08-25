#!/usr/bin/env python3
"""Verify, test, and stage the locked patched glibc release artifact."""

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
import stat
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/glibc-runtime-lock.json"
DEFAULT_PACKAGE = REPO_ROOT / "artifacts/glibc_2.44_aarch64.deb"
RECEIPT = ".steamclienttermux-glibc-receipt.json"
PACKAGE_MARKER = ".tgcompat-package-sha256"
HEX = frozenset("0123456789abcdef")


class GlibcError(RuntimeError):
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
        raise GlibcError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GlibcError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise GlibcError(f"{label} is not a JSON object")
    return value


def load_lock(path: Path) -> dict[str, object]:
    lock = read_object(path, "glibc runtime lock")
    try:
        sources = lock["sources"]
        artifact = lock["artifact"]
        source_records = [
            sources[name] for name in ("tgcompat", "glibc_packages", "termux_packages")
        ]
        valid = (
            lock["schema_version"] == 1
            and isinstance(lock["profile_id"], str)
            and lock["platform"]["architectures"] == ["aarch64"]
            and lock["platform"]["environment"] == "official-termux"
            and lock["platform"]["storage"] == "private-internal"
            and all(
                source["repository"].startswith("https://github.com/")
                and source["repository"].endswith(".git")
                and is_hex(source["commit"], 40)
                for source in source_records
            )
            and lock["source_build"]["package"] == "glibc"
            and lock["source_build"]["version"] == "2.44"
            and is_hex(lock["source_build"]["source_sha256"], 64)
            and artifact["filename"] == "glibc_2.44_aarch64.deb"
            and artifact["package"] == "glibc"
            and artifact["version"] == "2.44"
            and artifact["architecture"] == "aarch64"
            and artifact["size"] > 0
            and is_hex(artifact["sha256"], 64)
            and lock["distribution"]["project_redistributes_binary"] is True
            and lock["distribution"]["source_offer"] == "exact public commits in this lock"
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise GlibcError("glibc runtime lock is malformed")
    return lock


def clean_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "GLIBC_LD_LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "TMPDIR",
    ):
        environment.pop(name, None)
    environment["LC_ALL"] = "C"
    if extra:
        environment.update(extra)
    return environment


def run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> None:
    subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        env=clean_environment(environment),
    )


def require_private_path(path: Path, home: Path, label: str) -> None:
    if not path.is_absolute() or path in (Path("/"), home) or not path.is_relative_to(home):
        raise GlibcError(f"{label} must be below the private Termux HOME: {path}")


def verify_package(path: Path, lock: dict[str, object]) -> tuple[str, int]:
    artifact = lock["artifact"]
    if not path.is_file() or path.is_symlink():
        raise GlibcError(f"patched glibc package is missing or unsafe: {path}")
    size = path.stat().st_size
    digest = sha256_file(path)
    if size != artifact["size"] or digest != artifact["sha256"]:
        raise GlibcError("patched glibc package does not match the release lock")
    return digest, size


def require_tgcompat(base: Path, lock: dict[str, object]) -> Path:
    selector = base / "tgcompat/current"
    if not selector.is_symlink():
        raise GlibcError("locked tgcompat runtime must be installed first")
    root = selector.resolve(strict=True)
    expected = lock["sources"]["tgcompat"]["commit"]
    git = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
        env=clean_environment(),
    ).stdout.strip()
    required = (
        root / "build/tgcompatd",
        root / "scripts/tgcompat-session.sh",
        root / "integration/termux-glibc/stage-extracted-package.sh",
    )
    if git != expected or any(
        not path.is_file() or path.is_symlink() for path in required
    ):
        raise GlibcError("installed tgcompat runtime does not match the glibc lock")
    return root


def tree_identity(root: Path) -> tuple[str, int]:
    if not root.is_dir() or root.is_symlink():
        raise GlibcError(f"runtime tree is missing or unsafe: {root}")
    digest = hashlib.sha256()
    entries = 0
    paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative in (RECEIPT, PACKAGE_MARKER):
            continue
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            record = f"D\0{relative}\0{mode:o}\0"
        elif stat.S_ISREG(metadata.st_mode):
            record = f"F\0{relative}\0{mode:o}\0{metadata.st_size}\0{sha256_file(path)}\0"
        elif stat.S_ISLNK(metadata.st_mode):
            record = f"L\0{relative}\0{os.readlink(path)}\0"
        else:
            raise GlibcError(f"runtime tree contains a special file: {relative}")
        digest.update(record.encode("utf-8"))
        entries += 1
    return digest.hexdigest(), entries


def update_selector(deploy_root: Path, package_sha: str) -> None:
    selector = deploy_root / "current"
    if selector.exists() and not selector.is_symlink():
        raise GlibcError(f"glibc selector is not a symlink: {selector}")
    if selector.is_symlink():
        old = os.readlink(selector)
        if PurePosixPath(old).name != old or not is_hex(old, 64) or not (deploy_root / old).is_dir():
            raise GlibcError(f"glibc selector is unsafe: {selector}")
    temporary = deploy_root / f".current.{secrets.token_hex(8)}"
    os.symlink(package_sha, temporary)
    os.replace(temporary, selector)
    fsync_directory(deploy_root)


def validate_install(
    destination: Path, package_cache: Path, lock: dict[str, object]
) -> dict[str, object]:
    receipt = read_object(destination / RECEIPT, "glibc runtime receipt")
    package_sha = receipt.get("package_sha256")
    tree_sha, tree_entries = tree_identity(destination)
    marker = destination / PACKAGE_MARKER
    marker_value = (
        marker.read_text(encoding="ascii").strip()
        if marker.is_file() and not marker.is_symlink()
        else ""
    )
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("kind") == "tgcompat-patched-glibc"
        and receipt.get("profile_id") == lock["profile_id"]
        and package_sha == lock["artifact"]["sha256"]
        and destination.name == package_sha
        and marker_value == package_sha
        and package_cache.name == lock["artifact"]["filename"]
        and verify_package(package_cache, lock)[0] == package_sha
        and receipt.get("source_commits")
        == {name: source["commit"] for name, source in lock["sources"].items()}
        and receipt.get("payload_tree_sha256") == tree_sha
        and receipt.get("payload_tree_entries") == tree_entries
        and (destination / "lib/ld-linux-aarch64.so.1").is_file()
        and not (destination / "lib/ld-linux-aarch64.so.1").is_symlink()
        and (destination / "lib/libc.so.6").is_file()
    )
    if not valid:
        raise GlibcError("installed glibc runtime does not match its receipt")
    return receipt


def install(
    base: Path,
    deploy_root: Path,
    prefix: Path,
    package: Path,
    lock: dict[str, object],
    *,
    home: Path | None = None,
) -> tuple[str, dict[str, object]]:
    home = (home or Path.home()).resolve(strict=True)
    base = base.resolve()
    deploy_root = deploy_root.resolve()
    prefix = prefix.resolve(strict=True)
    package = package.resolve(strict=True)
    require_private_path(base, home, "--base")
    require_private_path(deploy_root, home, "--deploy-root")
    if prefix == Path("/") or not prefix.is_dir() or prefix.is_symlink():
        raise GlibcError(f"unsafe Termux prefix: {prefix}")
    package_sha, package_size = verify_package(package, lock)
    for path in (base, deploy_root):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise GlibcError(f"unsafe product directory: {path}")
    runtime_root = base / "glibc"
    package_root = runtime_root / "packages"
    work_root = runtime_root / "work"
    for path in (runtime_root, package_root, work_root):
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise GlibcError(f"unsafe glibc product directory: {path}")

    with (runtime_root / ".install.lock").open("a+b") as lock_stream:
        os.fchmod(lock_stream.fileno(), 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        package_cache = package_root / str(lock["artifact"]["filename"])
        if package_cache.exists() or package_cache.is_symlink():
            verify_package(package_cache, lock)
        else:
            descriptor, name = tempfile.mkstemp(prefix=".package.", dir=package_root)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as output, package.open("rb") as source:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, package_cache)
                fsync_directory(package_root)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    temporary.unlink()

        destination = deploy_root / package_sha
        if destination.exists() or destination.is_symlink():
            receipt = validate_install(destination, package_cache, lock)
            update_selector(deploy_root, package_sha)
            return "already-ready", receipt

        tgcompat = require_tgcompat(base, lock)
        bash = prefix / "bin/bash"
        if not bash.is_file() or bash.is_symlink() or not os.access(bash, os.X_OK):
            raise GlibcError(f"Termux bash is missing or unsafe: {bash}")
        short_tmp = prefix / "tmp"
        if not short_tmp.is_dir() or short_tmp.is_symlink():
            raise GlibcError(f"Termux temporary directory is missing or unsafe: {short_tmp}")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=".glibc-stage.", dir=work_root) as name:
            temporary = Path(name)
            verification_root = temporary / "verified-runtime"
            stage = tgcompat / "integration/termux-glibc/stage-extracted-package.sh"
            with tempfile.TemporaryDirectory(prefix=".tgc.", dir=short_tmp) as runtime:
                runtime_root = Path(runtime)
                os.chmod(runtime_root, 0o700)
                socket = runtime_root / "s"
                if len(os.fsencode(socket)) >= 108:
                    raise GlibcError("tgcompat validation socket path is too long")
                run(
                    [str(bash), str(stage), str(package_cache), str(verification_root)],
                    temporary,
                    {
                        "PREFIX": str(prefix),
                        "TMPDIR": str(temporary),
                        "TGCOMPAT_SOCKET": str(socket),
                    },
                )
            verified = verification_root / package_sha
            payload_sha, payload_entries = tree_identity(verified)
            receipt = {
                "schema_version": 1,
                "kind": "tgcompat-patched-glibc",
                "profile_id": lock["profile_id"],
                "source_commits": {
                    name: source["commit"] for name, source in lock["sources"].items()
                },
                "source_sha256": lock["source_build"]["source_sha256"],
                "package_sha256": package_sha,
                "package_size": package_size,
                "payload_tree_sha256": payload_sha,
                "payload_tree_entries": payload_entries,
                "install_seconds": round(time.monotonic() - started, 3),
            }
            write_json(verified / RECEIPT, receipt)
            if verified.stat().st_dev != deploy_root.stat().st_dev:
                raise GlibcError("verified runtime and deployment root are on different filesystems")
            os.replace(verified, destination)
            fsync_directory(deploy_root)
        receipt = validate_install(destination, package_cache, lock)
        update_selector(deploy_root, package_sha)
        return "installed", receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=Path.home() / ".local/share/tgcompat/glibc",
    )
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("PREFIX", "")))
    arguments = parser.parse_args()
    try:
        lock = load_lock(arguments.lock.resolve())
        result, receipt = install(
            arguments.base,
            arguments.deploy_root,
            arguments.prefix,
            arguments.package,
            lock,
        )
        print(f"GLIBC_RUNTIME={result}")
        print(f"GLIBC_PACKAGE_SHA256={receipt['package_sha256']}")
        print(f"GLIBC_INSTALL_SECONDS={receipt['install_seconds']}")
        return 0
    except (GlibcError, OSError, subprocess.CalledProcessError) as error:
        print(f"install-glibc-runtime: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
