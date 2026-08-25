#!/usr/bin/env python3
"""Install a locked, minimal, project-owned Debian runtime for Steam."""

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
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/debian-runtime-lock.json"
HEX = frozenset("0123456789abcdef")


class DebianError(RuntimeError):
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
        raise DebianError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DebianError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise DebianError(f"{label} is not a JSON object")
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
    lock = read_object(path, "Debian runtime lock")
    try:
        archive = lock["archive"]
        container = lock["container"]
        packages = lock["packages"]
        required = lock["acceptance"]["required_files"]
        valid = (
            lock["schema_version"] == 1
            and isinstance(lock["profile_id"], str)
            and lock["platform"]["architectures"] == ["aarch64"]
            and lock["platform"]["environment"] == "official-termux"
            and lock["platform"]["storage"] == "private-internal"
            and archive["publisher"] == "termux/proot-distro"
            and archive["url"].startswith(
                "https://github.com/termux/proot-distro/releases/download/"
            )
            and PurePosixPath(archive["filename"]).name == archive["filename"]
            and archive["size"] > 0
            and is_hex(archive["sha256"], 64)
            and container["name"] == "steam-arm64-runtime"
            and container["architecture"] == "aarch64"
            and container["receipt"] == ".steamclienttermux-debian-receipt.json"
            and isinstance(packages, list)
            and packages == sorted(set(packages))
            and len(packages) >= 20
            and all(
                isinstance(package, str)
                and package
                and set(package) <= set("abcdefghijklmnopqrstuvwxyz0123456789+.-")
                for package in packages
            )
            and isinstance(required, list)
            and len(required) >= 5
            and len(required) == len(set(required))
            and all(safe_relative(item) for item in required)
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise DebianError("Debian runtime lock is malformed")
    return lock


def require_private_path(path: Path, home: Path, label: str) -> None:
    if not path.is_absolute() or path in (Path("/"), home) or not path.is_relative_to(home):
        raise DebianError(f"{label} must be below the private Termux HOME: {path}")


def clean_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PD_PROOT_BIN"):
        environment.pop(name, None)
    environment["LC_ALL"] = "C"
    environment["PD_FORCE_NO_COLORS"] = "true"
    if extra:
        environment.update(extra)
    return environment


def verify_archive(path: Path, lock: dict[str, object]) -> tuple[str, int]:
    if not path.is_file() or path.is_symlink():
        raise DebianError(f"Debian archive is missing or unsafe: {path}")
    size = path.stat().st_size
    digest = sha256_file(path)
    if size != lock["archive"]["size"] or digest != lock["archive"]["sha256"]:
        raise DebianError("Debian archive does not match the runtime lock")
    return digest, size


def fetch_archive(destination: Path, lock: dict[str, object]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".debian-download.", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(
            lock["archive"]["url"], timeout=60
        ) as response:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        verify_archive(temporary, lock)
        os.replace(temporary, destination)
        fsync_directory(destination.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def run(
    arguments: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    capture: bool = False,
) -> str:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        env=clean_environment(environment),
    )
    return result.stdout.strip() if capture else ""


def installed_packages(
    proot_distro: Path,
    alias: str,
    packages: list[str],
    patched_proot: Path,
    cwd: Path,
) -> dict[str, str]:
    output = run(
        [
            str(proot_distro),
            "login",
            alias,
            "--",
            "/usr/bin/dpkg-query",
            "-W",
            "-f=${Package}\t${Version}\\n",
            *packages,
        ],
        cwd=cwd,
        environment={"PD_PROOT_BIN": str(patched_proot)},
        capture=True,
    )
    result: dict[str, str] = {}
    for line in output.splitlines():
        package, separator, version = line.partition("\t")
        if not separator or package in result or package not in packages or not version:
            raise DebianError("Debian package inventory is malformed")
        result[package] = version
    if set(result) != set(packages):
        raise DebianError("Debian package inventory is incomplete")
    return result


def validate_rootfs(rootfs: Path, lock: dict[str, object]) -> None:
    if rootfs.is_symlink() or not rootfs.is_dir():
        raise DebianError(f"Debian rootfs is missing or unsafe: {rootfs}")
    rootfs_resolved = rootfs.resolve(strict=True)
    for relative in lock["acceptance"]["required_files"]:
        path = rootfs / relative
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            resolved = None
        if (
            resolved is None
            or not resolved.is_relative_to(rootfs_resolved)
            or not resolved.is_file()
        ):
            raise DebianError(f"Debian runtime file is missing or unsafe: {relative}")


def validate_install(
    container: Path,
    lock: dict[str, object],
    lock_sha: str,
    archive_sha: str,
    package_versions: dict[str, str],
) -> dict[str, object]:
    validate_rootfs(container / "rootfs", lock)
    receipt = read_object(container / lock["container"]["receipt"], "Debian runtime receipt")
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("kind") == "steam-arm64-minimal-debian"
        and receipt.get("profile_id") == lock["profile_id"]
        and receipt.get("lock_sha256") == lock_sha
        and receipt.get("archive_sha256") == archive_sha
        and receipt.get("packages") == package_versions
        and receipt.get("acceptance") == "pass"
    )
    if not valid:
        raise DebianError("installed Debian runtime does not match its receipt")
    return receipt


def install(
    base: Path,
    prefix: Path,
    lock_path: Path,
    lock: dict[str, object],
    *,
    archive_input: Path | None = None,
    home: Path | None = None,
) -> tuple[str, dict[str, object]]:
    home = (home or Path.home()).resolve(strict=True)
    base = base.resolve()
    prefix = prefix.resolve(strict=True)
    lock_path = lock_path.resolve(strict=True)
    require_private_path(base, home, "--base")
    if prefix == Path("/") or prefix.is_symlink() or not prefix.is_dir():
        raise DebianError(f"unsafe Termux prefix: {prefix}")
    proot_distro = prefix / "bin/proot-distro"
    patched_proot = base / "src/proot-production/src/proot"
    if not proot_distro.is_file() or proot_distro.is_symlink() or not os.access(proot_distro, os.X_OK):
        raise DebianError(f"proot-distro is missing or unsafe: {proot_distro}")
    if not patched_proot.is_file() or patched_proot.is_symlink() or not os.access(patched_proot, os.X_OK):
        raise DebianError("locked patched PRoot must be installed first")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    product_root = base / "debian-runtime"
    cache_root = product_root / "cache"
    for path in (product_root, cache_root):
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise DebianError(f"unsafe Debian product directory: {path}")
    containers = prefix / "var/lib/proot-distro/containers"
    if containers.is_symlink() or not containers.is_dir():
        raise DebianError(f"unsafe proot-distro container directory: {containers}")
    alias = lock["container"]["name"]
    destination = containers / alias
    archive = cache_root / lock["archive"]["filename"]
    lock_sha = sha256_file(lock_path)

    with (product_root / ".install.lock").open("a+b") as lock_stream:
        os.fchmod(lock_stream.fileno(), 0o600)
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if archive.exists() or archive.is_symlink():
            archive_sha, archive_size = verify_archive(archive, lock)
        elif archive_input is not None:
            source = archive_input.resolve(strict=True)
            verify_archive(source, lock)
            descriptor, name = tempfile.mkstemp(prefix=".debian-copy.", dir=cache_root)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, archive)
                fsync_directory(cache_root)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    temporary.unlink()
            archive_sha, archive_size = verify_archive(archive, lock)
        else:
            fetch_archive(archive, lock)
            archive_sha, archive_size = verify_archive(archive, lock)

        if destination.exists() or destination.is_symlink():
            versions = installed_packages(
                proot_distro, alias, lock["packages"], patched_proot, base
            )
            receipt = validate_install(destination, lock, lock_sha, archive_sha, versions)
            return "already-ready", receipt

        stage_alias = f"{alias}-stage-{secrets.token_hex(6)}"
        stage = containers / stage_alias
        if stage.exists() or stage.is_symlink():
            raise DebianError("generated Debian staging name already exists")
        started = time.monotonic()
        try:
            run(
                [
                    str(proot_distro),
                    "install",
                    "--quiet",
                    "--name",
                    stage_alias,
                    "--architecture",
                    lock["container"]["architecture"],
                    str(archive),
                ],
                cwd=base,
                environment={"PD_PROOT_BIN": str(patched_proot)},
            )
            validate_rootfs(stage / "rootfs", {**lock, "acceptance": {"required_files": ["usr/bin/bash"]}})
            run(
                [
                    str(proot_distro),
                    "login",
                    stage_alias,
                    "--",
                    "/usr/bin/env",
                    "DEBIAN_FRONTEND=noninteractive",
                    "/usr/bin/apt-get",
                    "update",
                    "-qq",
                ],
                cwd=base,
                environment={"PD_PROOT_BIN": str(patched_proot)},
            )
            run(
                [
                    str(proot_distro),
                    "login",
                    stage_alias,
                    "--",
                    "/usr/bin/env",
                    "DEBIAN_FRONTEND=noninteractive",
                    "/usr/bin/apt-get",
                    "install",
                    "-y",
                    "-qq",
                    "--no-install-recommends",
                    *lock["packages"],
                ],
                cwd=base,
                environment={"PD_PROOT_BIN": str(patched_proot)},
            )
            run(
                [
                    str(proot_distro),
                    "login",
                    stage_alias,
                    "--",
                    "/usr/bin/apt-get",
                    "clean",
                ],
                cwd=base,
                environment={"PD_PROOT_BIN": str(patched_proot)},
            )
            validate_rootfs(stage / "rootfs", lock)
            versions = installed_packages(
                proot_distro, stage_alias, lock["packages"], patched_proot, base
            )
            receipt = {
                "schema_version": 1,
                "kind": "steam-arm64-minimal-debian",
                "profile_id": lock["profile_id"],
                "lock_sha256": lock_sha,
                "archive_sha256": archive_sha,
                "archive_size": archive_size,
                "packages": versions,
                "acceptance": "pass",
                "install_seconds": round(time.monotonic() - started, 3),
            }
            write_json(stage / lock["container"]["receipt"], receipt)
            if stage.stat().st_dev != containers.stat().st_dev:
                raise DebianError("staged and final Debian containers are on different filesystems")
            os.replace(stage, destination)
            fsync_directory(containers)
        finally:
            if stage.exists() and not stage.is_symlink() and stage.is_dir():
                shutil.rmtree(stage)
        versions = installed_packages(
            proot_distro, alias, lock["packages"], patched_proot, base
        )
        receipt = validate_install(destination, lock, lock_sha, archive_sha, versions)
        return "installed", receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, default=Path(os.environ.get("PREFIX", "")))
    parser.add_argument("--archive", type=Path)
    arguments = parser.parse_args()
    try:
        lock_path = arguments.lock.resolve()
        lock = load_lock(lock_path)
        result, receipt = install(
            arguments.base,
            arguments.prefix,
            lock_path,
            lock,
            archive_input=arguments.archive,
        )
        print(f"DEBIAN_RUNTIME={result}")
        print(f"DEBIAN_ARCHIVE_SHA256={receipt['archive_sha256']}")
        print(f"DEBIAN_INSTALL_SECONDS={receipt['install_seconds']}")
        return 0
    except (DebianError, OSError, subprocess.CalledProcessError) as error:
        print(f"install-debian-runtime: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
