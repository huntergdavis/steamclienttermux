#!/usr/bin/env python3
"""Verify, download, and safely extract Valve's locked ARM64 Steam seed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import tempfile
import urllib.request
from urllib.parse import urlsplit
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO_ROOT / "config/steam-arm64-bootstrap-lock.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ALLOWED_DOWNLOAD_HOST_SUFFIX = ".steamstatic.com"


class BootstrapError(RuntimeError):
    pass


def require_int(value: object, name: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise BootstrapError(f"{name} must be an integer >= {minimum}")
    return value


def require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise BootstrapError(f"{name} must be a lowercase SHA-256")
    return value


def validate_url(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise BootstrapError(f"{name} must be a URL")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "steamstatic.com" or host.endswith(ALLOWED_DOWNLOAD_HOST_SUFFIX)
    ):
        raise BootstrapError(f"{name} must use HTTPS on steamstatic.com")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BootstrapError(f"{name} contains unsupported URL components")
    return value


def load_lock(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"could not load lock {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise BootstrapError("unsupported bootstrap lock schema")
    if payload.get("platform") != "linuxarm64":
        raise BootstrapError("bootstrap lock is not for linuxarm64")
    require_int(payload.get("build_id"), "build_id", 1)
    for section_name in ("manifest", "seed_archive"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            raise BootstrapError(f"missing {section_name} section")
        validate_url(section.get("url"), f"{section_name}.url")
        require_int(section.get("size"), f"{section_name}.size", 1)
        require_sha256(section.get("sha256"), f"{section_name}.sha256")
    archive = payload["seed_archive"]
    assert isinstance(archive, dict)
    require_int(archive.get("member_count"), "seed_archive.member_count", 1)
    require_int(
        archive.get("max_uncompressed_bytes"),
        "seed_archive.max_uncompressed_bytes",
        1,
    )
    seed = payload.get("seed_executable")
    if not isinstance(seed, dict):
        raise BootstrapError("missing seed_executable section")
    normalized_member(seed.get("member"), "seed_executable.member")
    require_int(seed.get("size"), "seed_executable.size", 1)
    require_sha256(seed.get("sha256"), "seed_executable.sha256")
    require_int(seed.get("elf_machine"), "seed_executable.elf_machine", 1)
    if payload.get("redistribution") is not False:
        raise BootstrapError("lock must explicitly forbid Valve binary redistribution")
    return payload


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_locked_file(path: Path, section: dict[str, object], label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise BootstrapError(f"{label} is not a regular non-symlink file: {path}")
    actual_size, actual_sha = hash_file(path)
    expected_size = require_int(section.get("size"), f"{label}.size", 1)
    expected_sha = require_sha256(section.get("sha256"), f"{label}.sha256")
    if actual_size != expected_size or actual_sha != expected_sha:
        raise BootstrapError(
            f"{label} identity mismatch: got {actual_size}/{actual_sha}, "
            f"expected {expected_size}/{expected_sha}"
        )


def normalized_member(value: object, name: str = "archive member") -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise BootstrapError(f"unsafe {name}")
    candidate = value.replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise BootstrapError(f"absolute {name}: {value!r}")
    is_directory = candidate.endswith("/")
    components = candidate[:-1].split("/") if is_directory else candidate.split("/")
    if not components or any(part in ("", ".", "..") for part in components):
        raise BootstrapError(f"non-canonical {name}: {value!r}")
    normalized = "/".join(components)
    if normalized == "" or str(PurePosixPath(normalized)) != normalized:
        raise BootstrapError(f"non-canonical {name}: {value!r}")
    return normalized


def safe_symlink_target(member: str, data: bytes) -> str:
    if len(data) > 4096 or b"\x00" in data:
        raise BootstrapError(f"unsafe symlink payload for {member}")
    try:
        target = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BootstrapError(f"non-UTF-8 symlink target for {member}") from error
    target = target.replace("\\", "/")
    if not target or target.startswith("/") or re.match(r"^[A-Za-z]:", target):
        raise BootstrapError(f"unsafe symlink target for {member}: {target!r}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member), target))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise BootstrapError(f"symlink escapes archive root: {member} -> {target}")
    return target


def zip_entry_type(info: zipfile.ZipInfo) -> int:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if kind == 0:
        return stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    return kind


def inspect_archive(
    path: Path, lock: dict[str, object]
) -> tuple[list[tuple[zipfile.ZipInfo, str, int]], dict[str, str]]:
    archive = lock["seed_archive"]
    assert isinstance(archive, dict)
    verify_locked_file(path, archive, "seed archive")
    expected_count = require_int(archive["member_count"], "member_count", 1)
    max_uncompressed = require_int(
        archive["max_uncompressed_bytes"], "max_uncompressed_bytes", 1
    )
    entries: list[tuple[zipfile.ZipInfo, str, int]] = []
    names: set[str] = set()
    symlink_targets: dict[str, str] = {}
    total = 0
    try:
        with zipfile.ZipFile(path) as source:
            infos = source.infolist()
            if len(infos) != expected_count:
                raise BootstrapError(
                    f"archive has {len(infos)} members, expected {expected_count}"
                )
            for info in infos:
                member = normalized_member(info.filename)
                if member in names:
                    raise BootstrapError(f"normalized archive collision: {member}")
                names.add(member)
                kind = zip_entry_type(info)
                if kind not in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
                    raise BootstrapError(f"unsupported archive entry type: {member}")
                total += info.file_size
                if total > max_uncompressed:
                    raise BootstrapError("archive exceeds uncompressed-size limit")
                entries.append((info, member, kind))
                if kind == stat.S_IFLNK:
                    symlink_targets[member] = safe_symlink_target(
                        member, source.read(info)
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, BootstrapError):
            raise
        raise BootstrapError(f"invalid seed archive: {error}") from error
    for _info, member, _kind in entries:
        parts = member.split("/")
        for index in range(1, len(parts)):
            if "/".join(parts[:index]) in symlink_targets:
                raise BootstrapError(f"archive member descends through symlink: {member}")
    return entries, symlink_targets


def verify_seed_executable(root: Path, lock: dict[str, object]) -> None:
    seed = lock["seed_executable"]
    assert isinstance(seed, dict)
    member = normalized_member(seed["member"], "seed executable member")
    path = root.joinpath(*member.split("/"))
    verify_locked_file(path, seed, "seed executable")
    header = path.read_bytes()[:20]
    if len(header) < 20 or header[:6] != b"\x7fELF\x02\x01":
        raise BootstrapError("seed executable is not little-endian ELF64")
    machine = struct.unpack_from("<H", header, 18)[0]
    expected_machine = require_int(seed["elf_machine"], "elf_machine", 1)
    if machine != expected_machine:
        raise BootstrapError(
            f"seed executable machine is {machine}, expected {expected_machine}"
        )


def extract_archive(path: Path, destination: Path, lock: dict[str, object]) -> None:
    entries, symlink_targets = inspect_archive(path, lock)
    if destination.exists() or destination.is_symlink():
        raise BootstrapError(f"destination already exists: {destination}")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise BootstrapError(f"destination parent is not a safe directory: {parent}")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.bootstrap-", dir=parent)
    )
    try:
        with zipfile.ZipFile(path) as source:
            directory_entries = sorted(
                (entry for entry in entries if entry[2] == stat.S_IFDIR),
                key=lambda entry: (entry[1].count("/"), entry[1]),
            )
            for info, member, kind in directory_entries:
                output = staging.joinpath(*member.split("/"))
                mode = ((info.external_attr >> 16) & 0o777) or (
                    0o755 if kind == stat.S_IFDIR else 0o644
                )
                output.mkdir(parents=True, exist_ok=False)
                output.chmod(mode)
            for info, member, kind in entries:
                if kind != stat.S_IFREG:
                    continue
                output = staging.joinpath(*member.split("/"))
                mode = ((info.external_attr >> 16) & 0o777) or 0o644
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() or output.is_symlink():
                    raise BootstrapError(f"refusing archive overwrite: {member}")
                with source.open(info) as reader, output.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                if output.stat().st_size != info.file_size:
                    raise BootstrapError(f"short extraction for {member}")
                output.chmod(mode)
            for _info, member, kind in entries:
                if kind != stat.S_IFLNK:
                    continue
                output = staging.joinpath(*member.split("/"))
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists() or output.is_symlink():
                    raise BootstrapError(f"refusing archive overwrite: {member}")
                os.symlink(symlink_targets[member], output)
        verify_seed_executable(staging, lock)
        os.replace(staging, destination)
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def download_locked(section: dict[str, object], destination: Path, label: str) -> None:
    if destination.exists() or destination.is_symlink():
        verify_locked_file(destination, section, label)
        return
    url = validate_url(section["url"], f"{label}.url")
    expected_size = require_int(section["size"], f"{label}.size", 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists() or partial.is_symlink():
        raise BootstrapError(f"partial download already exists: {partial}")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "steamclienttermux-bootstrap/1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response, partial.open(
            "xb"
        ) as writer:
            validate_url(response.geturl(), f"final {label} URL")
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > expected_size:
                    raise BootstrapError(f"{label} exceeds locked size")
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        verify_locked_file(partial, section, label)
        os.replace(partial, destination)
    except BaseException:
        if partial.exists() and not partial.is_symlink():
            partial.unlink()
        raise


def command_install(args: argparse.Namespace, lock: dict[str, object]) -> None:
    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / "steam_client_linuxarm64.locked"
    archive_path = cache / "bins_linuxarm64_linuxarm64.seed.zip"
    manifest = lock["manifest"]
    archive = lock["seed_archive"]
    assert isinstance(manifest, dict) and isinstance(archive, dict)
    download_locked(manifest, manifest_path, "Valve manifest")
    download_locked(archive, archive_path, "seed archive")
    extract_archive(archive_path, args.destination.resolve(), lock)
    print(f"Steam ARM64 seed extracted: {args.destination.resolve()}")
    print("Run the seed through the project's native glibc loader to self-update.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="verify an existing seed ZIP")
    verify.add_argument("--archive", type=Path, required=True)
    extract = subparsers.add_parser("extract", help="verify and extract a seed ZIP")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--destination", type=Path, required=True)
    install = subparsers.add_parser("install", help="download, verify, and extract")
    install.add_argument("--cache", type=Path, required=True)
    install.add_argument("--destination", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        lock = load_lock(args.lock.resolve())
        if args.command == "verify":
            inspect_archive(args.archive.resolve(), lock)
            print(f"Steam ARM64 seed verified: {args.archive.resolve()}")
        elif args.command == "extract":
            extract_archive(args.archive.resolve(), args.destination.resolve(), lock)
            print(f"Steam ARM64 seed extracted: {args.destination.resolve()}")
        else:
            command_install(args, lock)
    except BootstrapError as error:
        raise SystemExit(f"bootstrap-steam-arm64-client: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
