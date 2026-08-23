#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct


FEX_COMMIT = "a04b0241c2fe3911729842205cd8643981108aad"
COMPILER_SHA256 = "fff9bd81049d250eb26554887b3b3df7db9d934e3969023101c887b655bc7644"
CANDIDATE_NAME = "tombraider-203160-offline-fff9bd81"
MAP_NAME = re.compile(r"tombraider\.exe-[0-9a-f]{16}\.[0-9]+\.bin")


def fail(message: str) -> None:
    raise SystemExit(f"prepare-tombraider-fex-offline-cache: {message}")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def private_directory(path: Path, description: str) -> Path:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        fail(f"{description} is unsafe: {path}")
    return path


def regular_file(path: Path, description: str, maximum: int) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or metadata.st_size <= 0
        or metadata.st_size > maximum
    ):
        fail(f"{description} is unsafe: {path}")
    return metadata


def compiler_path(base: Path, expected_sha256: str) -> Path:
    compiler = base / "compat-bin/fex-2605-offline-compiler/FEXOfflineCompiler.exe"
    regular_file(compiler, "FEX offline compiler", 16 * 1024 * 1024)
    if digest(compiler) != expected_sha256:
        fail("FEX offline compiler SHA-256 does not match")
    return compiler


def write_exclusive(source: Path, destination: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb", closefd=False
        ) as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(base: Path, expected_sha256: str) -> None:
    compiler = compiler_path(base, expected_sha256)
    source = private_directory(
        base / "cache/fex-code-cache/tombraider-203160/codemap/new",
        "recorded Tomb Raider code-map directory",
    )
    maps = sorted(path for path in source.iterdir() if MAP_NAME.fullmatch(path.name))
    if not 1 <= len(maps) <= 128:
        fail(f"expected 1 through 128 Tomb Raider code maps, found {len(maps)}")
    for path in maps:
        regular_file(path, "recorded Tomb Raider code map", 16 * 1024 * 1024)

    root = base / "cache/fex-code-cache" / CANDIDATE_NAME
    if root.exists() or root.is_symlink():
        fail(f"candidate already exists: {root}")
    root.mkdir(mode=0o700)
    (root / "codemap/new").mkdir(mode=0o700, parents=True)
    (root / "codemap/ready").mkdir(mode=0o700)
    (root / "cache").mkdir(mode=0o700)
    copied = []
    for path in maps:
        destination = root / "codemap/new" / path.name
        write_exclusive(path, destination)
        if digest(destination) != digest(path):
            fail(f"copied code map failed SHA-256 validation: {path.name}")
        copied.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        )
    manifest = {
        "schema": 1,
        "status": "prepared",
        "fex_commit": FEX_COMMIT,
        "compiler": str(compiler),
        "compiler_sha256": expected_sha256,
        "source": str(source),
        "candidate": str(root),
        "maps": copied,
    }
    manifest_path = root / "prepare.json"
    descriptor = os.open(
        manifest_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(f"FEX_OFFLINE_CACHE_PREPARED={root} maps={len(copied)}")


def verify(base: Path, expected_sha256: str) -> None:
    compiler_path(base, expected_sha256)
    root = private_directory(
        base / "cache/fex-code-cache" / CANDIDATE_NAME,
        "compiled FEX cache candidate",
    )
    pending = private_directory(root / "codemap/new", "pending code-map directory")
    ready = private_directory(root / "codemap/ready", "ready code-map directory")
    cache = private_directory(root / "cache", "compiled cache directory")
    pending_files = list(pending.iterdir())
    ready_files = sorted(ready.iterdir())
    cache_files = sorted(cache.iterdir())
    if pending_files or not 1 <= len(ready_files) <= 128 or not 1 <= len(cache_files) <= 128:
        fail("offline compiler did not produce a complete candidate")
    for path in ready_files:
        regular_file(path, "aggregated FEX code map", 64 * 1024 * 1024)

    expected_hash = bytes.fromhex(FEX_COMMIT)
    compiled = []
    for path in cache_files:
        metadata = regular_file(path, "compiled FEX cache", 256 * 1024 * 1024)
        with path.open("rb") as stream:
            header = stream.read(32)
        if len(header) != 32:
            fail(f"compiled cache has a truncated header: {path.name}")
        magic, version, fex_hash, blocks = struct.unpack("<4sI20sI", header)
        if magic != b"FXCC" or version != 1 or fex_hash != expected_hash or blocks == 0:
            fail(f"compiled cache header is incompatible with FEX-2605: {path.name}")
        compiled.append(
            {
                "name": path.name,
                "size_bytes": metadata.st_size,
                "sha256": digest(path),
                "format_version": version,
                "fex_commit": fex_hash.hex(),
                "blocks": blocks,
            }
        )
    result = {
        "schema": 1,
        "status": "verified",
        "fex_commit": FEX_COMMIT,
        "compiler_sha256": expected_sha256,
        "candidate": str(root),
        "ready_code_maps": len(ready_files),
        "compiled_caches": compiled,
    }
    result_path = root / "result.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    descriptor = os.open(result_path, flags, 0o600)
    try:
        payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(f"FEX_OFFLINE_CACHE_VERIFIED={root} caches={len(compiled)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--expected-compiler-sha256", default=COMPILER_SHA256)
    arguments = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", arguments.expected_compiler_sha256):
        fail("expected compiler SHA-256 must be 64 lowercase hex characters")
    base = Path(arguments.base)
    private_directory(base, "Steam ARM64 base")
    if arguments.action == "prepare":
        prepare(base, arguments.expected_compiler_sha256)
    else:
        verify(base, arguments.expected_compiler_sha256)


if __name__ == "__main__":
    main()
