#!/usr/bin/env python3
"""Seed a game's DXVK state cache into fast internal storage."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


CACHE_NAME = re.compile(r"^[0-9a-f]{16}\.dxvk\.(?:bin|lut)$")


def fail(message: str) -> None:
    raise SystemExit(f"prepare-dxvk-state-cache: {message}")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def directory(path: Path, label: str, *, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        fail(f"{label} is unsafe: {path}")
    return path


def cache_file(path: Path, label: str) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not 1 <= metadata.st_size <= 256 * 1024 * 1024
    ):
        fail(f"{label} is unsafe: {path}")
    return metadata


def write_json(path: Path, document: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".seed.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = -1
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def validate_live(destination: Path) -> list[Path]:
    files = sorted(
        path for path in destination.iterdir() if path.name not in {"seed.json", ".lock"}
    )
    if not 1 <= len(files) <= 64:
        fail("internal DXVK cache must contain 1 through 64 cache files")
    for path in files:
        if CACHE_NAME.fullmatch(path.name) is None:
            fail(f"internal DXVK cache has an unexpected entry: {path.name}")
        cache_file(path, "internal DXVK cache")
    return files


def prepare(base: Path, appid: int) -> Path:
    source_text = (
        base
        / f"removable-library/steamapps/compatdata/{appid}/pfx/drive_c/users/steamuser/AppData/Local/dxvk"
    )
    destination = base / f"cache/dxvk-state/{appid}"
    directory(base, "Steam base")
    directory(base / "cache", "Steam cache directory", create=True)
    directory(base / "cache/dxvk-state", "DXVK cache root", create=True)
    directory(destination, "internal DXVK cache", create=True)
    lock_path = destination / ".lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        seed = destination / "seed.json"
        payloads = [
            path
            for path in destination.iterdir()
            if path.name not in {"seed.json", ".lock"}
        ]
        if seed.exists() or seed.is_symlink() or payloads:
            if not seed.exists() or seed.is_symlink():
                fail("internal DXVK cache is partially seeded")
            cache_file(seed, "DXVK cache seed manifest")
            files = validate_live(destination)
            print(
                f"DXVK_STATE_CACHE_REUSED={destination} appid={appid} files={len(files)}"
            )
            return destination

        try:
            source = source_text.resolve(strict=True)
        except FileNotFoundError:
            fail(f"source DXVK cache is unavailable: {source_text}")
        directory(source, "source DXVK cache")
        sources = sorted(source.iterdir())
        if not 1 <= len(sources) <= 64:
            fail("source DXVK cache must contain 1 through 64 files")
        records = []
        for path in sources:
            if CACHE_NAME.fullmatch(path.name) is None:
                fail(f"source DXVK cache has an unexpected entry: {path.name}")
            metadata = cache_file(path, "source DXVK cache")
            target = destination / path.name
            if target.exists() or target.is_symlink():
                fail(f"internal DXVK cache target already exists: {target}")
            temporary = destination / f".{path.name}.seed-{os.getpid()}"
            try:
                with path.open("rb") as input_stream, temporary.open("xb") as output:
                    shutil.copyfileobj(input_stream, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.chmod(0o600)
                if temporary.stat().st_size != metadata.st_size:
                    fail(f"seeded DXVK cache size changed: {path.name}")
                observed_hash = digest(temporary)
                os.replace(temporary, target)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    temporary.unlink()
            records.append(
                {
                    "name": path.name,
                    "size_bytes": metadata.st_size,
                    "sha256": observed_hash,
                }
            )
        write_json(
            seed,
            {
                "schema_version": 1,
                "appid": appid,
                "source": str(source),
                "destination": str(destination),
                "files": records,
            },
        )
        validate_live(destination)
        print(f"DXVK_STATE_CACHE_SEEDED={destination} appid={appid} files={len(records)}")
        return destination
    except BlockingIOError:
        fail("another DXVK cache preparation is active")
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare",))
    parser.add_argument("--appid", type=int, required=True)
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    arguments = parser.parse_args()
    if arguments.appid <= 0:
        parser.error("--appid must be positive")
    prepare(Path(arguments.base), arguments.appid)


if __name__ == "__main__":
    main()
