#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import zipfile


SCRIPT = Path(__file__).with_name("bootstrap-steam-arm64-client.py")
SPEC = importlib.util.spec_from_file_location("steam_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elf64_aarch64(payload: bytes = b"seed") -> bytes:
    header = bytearray(20)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    return bytes(header) + payload


def write_entry(
    archive: zipfile.ZipFile, name: str, data: bytes, mode: int
) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    archive.writestr(info, data)


def make_archive(path: Path, variant: str = "valid") -> bytes:
    seed = elf64_aarch64()
    with zipfile.ZipFile(path, "w") as archive:
        write_entry(archive, "steamrtarm64/", b"", stat.S_IFDIR | 0o755)
        write_entry(
            archive,
            "steamrtarm64\\steam",
            seed,
            stat.S_IFREG | 0o755,
        )
        if variant == "traversal":
            write_entry(archive, "../escape", b"bad", stat.S_IFREG | 0o644)
        elif variant == "collision":
            write_entry(archive, "steamrtarm64/steam", seed, stat.S_IFREG | 0o755)
        elif variant == "unsafe-link":
            write_entry(
                archive,
                "steamrtarm64/libs/link",
                b"../../../escape",
                stat.S_IFLNK | 0o777,
            )
        else:
            write_entry(
                archive,
                "steamrtarm64/libs/libcurl.so",
                b"libcurl.so.4",
                stat.S_IFLNK | 0o777,
            )
    return seed


def write_lock(path: Path, archive: Path, seed: bytes) -> None:
    payload = {
        "schema_version": 1,
        "channel": "test",
        "platform": "linuxarm64",
        "build_id": 1,
        "manifest": {
            "url": "https://client-update.steamstatic.com/test-manifest",
            "size": 1,
            "sha256": "0" * 64,
        },
        "seed_archive": {
            "url": "https://client-update.steamstatic.com/test.zip",
            "size": archive.stat().st_size,
            "sha256": sha256(archive),
            "member_count": 3,
            "max_uncompressed_bytes": 1024 * 1024,
        },
        "seed_executable": {
            "member": "steamrtarm64/steam",
            "size": len(seed),
            "sha256": hashlib.sha256(seed).hexdigest(),
            "elf_machine": 183,
        },
        "redistribution": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.BootstrapError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-bootstrap-test.") as directory:
        root = Path(directory)
        archive = root / "seed.zip"
        seed = make_archive(archive)
        lock_path = root / "lock.json"
        write_lock(lock_path, archive, seed)
        lock = MODULE.load_lock(lock_path)
        entries, links = MODULE.inspect_archive(archive, lock)
        assert [entry[1] for entry in entries] == [
            "steamrtarm64",
            "steamrtarm64/steam",
            "steamrtarm64/libs/libcurl.so",
        ]
        assert links == {"steamrtarm64/libs/libcurl.so": "libcurl.so.4"}
        destination = root / "client"
        MODULE.extract_archive(archive, destination, lock)
        executable = destination / "steamrtarm64/steam"
        assert executable.read_bytes() == seed
        assert executable.stat().st_mode & 0o777 == 0o755
        link = destination / "steamrtarm64/libs/libcurl.so"
        assert link.is_symlink() and link.readlink() == Path("libcurl.so.4")
        expect_failure(
            lambda: MODULE.extract_archive(archive, destination, lock),
            "destination already exists",
        )

        for variant, phrase in (
            ("traversal", "non-canonical archive member"),
            ("collision", "normalized archive collision"),
            ("unsafe-link", "symlink escapes archive root"),
        ):
            hostile = root / f"{variant}.zip"
            hostile_seed = make_archive(hostile, variant)
            hostile_lock_path = root / f"{variant}.json"
            write_lock(hostile_lock_path, hostile, hostile_seed)
            hostile_lock = MODULE.load_lock(hostile_lock_path)
            expect_failure(
                lambda h=hostile, l=hostile_lock: MODULE.inspect_archive(h, l),
                phrase,
            )

        mutated = root / "mutated.zip"
        mutated.write_bytes(archive.read_bytes() + b"x")
        expect_failure(
            lambda: MODULE.inspect_archive(mutated, lock), "identity mismatch"
        )

    official = MODULE.load_lock(
        SCRIPT.parents[1] / "config/steam-arm64-bootstrap-lock.json"
    )
    assert official["build_id"] == 1785799196
    assert official["redistribution"] is False
    print("Steam ARM64 locked bootstrap tests: PASS")


if __name__ == "__main__":
    main()
