#!/usr/bin/env python3
"""Fetch, verify, safely extract, and receipt the locked Turnip runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import tarfile
import tempfile
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/turnip-runtime-lock.json"
RECEIPT = ".steamclienttermux-turnip-receipt.json"


class TurnipError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise TurnipError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TurnipError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise TurnipError(f"{label} is not a JSON object")
    return value


def load_lock(path: Path) -> dict[str, object]:
    lock = read_object(path, "Turnip lock")
    try:
        archive = lock["archive"]
        driver = lock["driver"]
        platform = lock["platform"]
        source = lock["source"]
        valid = (
            lock["schema_version"] == 1
            and isinstance(lock["profile_id"], str)
            and platform["architectures"] == ["aarch64"]
            and platform["gpu_family"] == "qualcomm-adreno"
            and platform["kernel_interface"] == "kgsl"
            and isinstance(source["repository"], str)
            and len(source["commit"]) == 40
            and archive["url"].startswith("https://github.com/")
            and archive["size"] > 0
            and len(archive["sha256"]) == 64
            and 0 < archive["member_count"] <= 1024
            and 0 < archive["uncompressed_bytes"] <= 256 * 1024 * 1024
            and driver["relative_path"]
            == "usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so"
            and driver["size"] > 0
            and len(driver["sha256"]) == 64
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise TurnipError("Turnip lock is malformed")
    return lock


def verify_archive(path: Path, lock: dict[str, object]) -> None:
    archive = lock["archive"]
    assert isinstance(archive, dict)
    if not path.is_file() or path.is_symlink():
        raise TurnipError(f"Turnip archive is missing or unsafe: {path}")
    if path.stat().st_size != archive["size"]:
        raise TurnipError("Turnip archive size does not match the lock")
    if sha256_file(path) != archive["sha256"]:
        raise TurnipError("Turnip archive SHA-256 does not match the lock")


def download_archive(cache: Path, lock: dict[str, object]) -> Path:
    archive = lock["archive"]
    assert isinstance(archive, dict)
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache.is_symlink():
        raise TurnipError(f"Turnip cache is a symlink: {cache}")
    destination = cache / str(archive["name"])
    if destination.exists() or destination.is_symlink():
        verify_archive(destination, lock)
        return destination
    temporary = cache / f".{archive['name']}.{secrets.token_hex(8)}.part"
    try:
        with urllib.request.urlopen(str(archive["url"]), timeout=120) as response:
            with temporary.open("xb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        verify_archive(temporary, lock)
        os.replace(temporary, destination)
        fsync_directory(cache)
    except BaseException:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise
    return destination


def normalized_member(name: str) -> PurePosixPath:
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\x00" in name
        or "\\" in name
        or any(part in ("", ".", "..") for part in path.parts)
        or path.as_posix() != name
    ):
        raise TurnipError(f"unsafe archive member: {name!r}")
    return path


def resolved_link(member: PurePosixPath, target: str) -> PurePosixPath:
    if not target or target.startswith("/") or "\x00" in target:
        raise TurnipError(f"unsafe archive symlink target: {target!r}")
    parts: list[str] = list(member.parent.parts)
    for part in PurePosixPath(target).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise TurnipError(f"archive symlink escapes staging: {member}")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise TurnipError(f"archive symlink has an empty target: {member}")
    return PurePosixPath(*parts)


def safe_extract(archive_path: Path, destination: Path, lock: dict[str, object]) -> None:
    archive_lock = lock["archive"]
    assert isinstance(archive_lock, dict)
    if destination.exists() or destination.is_symlink():
        raise TurnipError(f"extraction destination already exists: {destination}")
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) != archive_lock["member_count"]:
            raise TurnipError("Turnip archive member count does not match the lock")
        if sum(member.size for member in members) != archive_lock["uncompressed_bytes"]:
            raise TurnipError("Turnip archive expanded size does not match the lock")
        records: list[tuple[tarfile.TarInfo, PurePosixPath]] = []
        seen: set[PurePosixPath] = set()
        symlinks: set[PurePosixPath] = set()
        for member in members:
            path = normalized_member(member.name)
            if path in seen:
                raise TurnipError(f"duplicate archive member: {path}")
            seen.add(path)
            if member.issym():
                resolved_link(path, member.linkname)
                symlinks.add(path)
            elif not member.isdir() and not member.isfile():
                raise TurnipError(f"unsupported archive member type: {path}")
            records.append((member, path))
        for _member, path in records:
            if any(PurePosixPath(*path.parts[:index]) in symlinks for index in range(1, len(path.parts))):
                raise TurnipError(f"archive member descends through a symlink: {path}")

        for member, path in records:
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise TurnipError(f"cannot read archive member: {path}")
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o700 if member.mode & 0o111 else 0o600,
                )
                with source, os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if target.stat().st_size != member.size:
                    raise TurnipError(f"short extracted archive member: {path}")
        for member, path in records:
            if member.issym():
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.symlink(member.linkname, target)
        for directory in sorted(
            (path for path in destination.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            fsync_directory(directory)
        fsync_directory(destination)


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


def validate_install(destination: Path, lock: dict[str, object]) -> None:
    driver = lock["driver"]
    assert isinstance(driver, dict)
    receipt = read_object(destination / RECEIPT, "Turnip receipt")
    driver_path = destination / str(driver["relative_path"])
    if (
        receipt.get("schema_version") != 1
        or receipt.get("profile_id") != lock["profile_id"]
        or receipt.get("archive_sha256") != lock["archive"]["sha256"]
        or receipt.get("driver_sha256") != driver["sha256"]
        or not driver_path.is_file()
        or driver_path.is_symlink()
        or driver_path.stat().st_size != driver["size"]
        or sha256_file(driver_path) != driver["sha256"]
    ):
        raise TurnipError("installed Turnip runtime does not match its receipt")


def install(base: Path, archive_path: Path, lock: dict[str, object]) -> str:
    if not base.is_absolute():
        raise TurnipError("--base must be absolute")
    if base.exists():
        if not base.is_dir() or base.is_symlink():
            raise TurnipError(f"unsafe base directory: {base}")
    else:
        base.mkdir(mode=0o700)
    destination = base / "mesa-kgsl"
    if destination.is_symlink():
        raise TurnipError(f"Turnip destination is a symlink: {destination}")
    if destination.exists():
        validate_install(destination, lock)
        return "already-ready"
    verify_archive(archive_path, lock)
    staging = base / f".mesa-kgsl.staging.{secrets.token_hex(8)}"
    safe_extract(archive_path, staging, lock)
    driver = lock["driver"]
    assert isinstance(driver, dict)
    driver_path = staging / str(driver["relative_path"])
    if (
        not driver_path.is_file()
        or driver_path.is_symlink()
        or driver_path.stat().st_size != driver["size"]
        or sha256_file(driver_path) != driver["sha256"]
    ):
        raise TurnipError("extracted Turnip driver does not match the lock")
    icd_directory = staging / "icd.d"
    icd_directory.mkdir(mode=0o700)
    write_json(
        icd_directory / "freedreno-private.json",
        {
            "file_format_version": "1.0.0",
            "ICD": {
                "library_path": str(destination / str(driver["relative_path"])),
                "api_version": driver["vulkan_api_version"],
            },
        },
    )
    write_json(
        staging / RECEIPT,
        {
            "schema_version": 1,
            "kind": "turnip-runtime",
            "profile_id": lock["profile_id"],
            "source_commit": lock["source"]["commit"],
            "archive_sha256": lock["archive"]["sha256"],
            "driver_sha256": driver["sha256"],
        },
    )
    os.replace(staging, destination)
    fsync_directory(base)
    validate_install(destination, lock)
    return "installed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--archive", type=Path, required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--base", type=Path, required=True)
    install_parser.add_argument("--archive", type=Path)
    arguments = parser.parse_args()
    try:
        lock = load_lock(arguments.lock.resolve())
        if arguments.command == "verify":
            verify_archive(arguments.archive.resolve(), lock)
            print("TURNIP_ARCHIVE=verified")
        else:
            archive = arguments.archive
            if archive is None:
                archive = download_archive(arguments.base.resolve() / "download-cache", lock)
            result = install(arguments.base.resolve(), archive.resolve(), lock)
            print(f"TURNIP_RUNTIME={result}")
            print(f"TURNIP_PROFILE={lock['profile_id']}")
        return 0
    except (OSError, TurnipError, tarfile.TarError) as error:
        print(f"install-turnip-runtime: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
