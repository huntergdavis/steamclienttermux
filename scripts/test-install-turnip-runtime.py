#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile


SCRIPT = Path(__file__).with_name("install-turnip-runtime.py")
SPEC = importlib.util.spec_from_file_location("turnip_installer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.TurnipError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def add_directory(archive: tarfile.TarFile, name: str) -> None:
    record = tarfile.TarInfo(name)
    record.type = tarfile.DIRTYPE
    record.mode = 0o755
    archive.addfile(record)


def add_file(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    record = tarfile.TarInfo(name)
    record.size = len(payload)
    record.mode = 0o755
    archive.addfile(record, io.BytesIO(payload))


def make_archive(path: Path, driver: bytes, *, malicious: str | None = None) -> tuple[int, int]:
    with tarfile.open(path, "w:gz") as archive:
        if malicious is not None:
            add_file(archive, malicious, b"bad")
            return 1, 3
        add_directory(archive, "./usr")
        add_directory(archive, "./usr/lib")
        add_directory(archive, "./usr/lib/aarch64-linux-gnu")
        add_file(
            archive,
            "./usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so",
            driver,
        )
        link = tarfile.TarInfo("./usr/lib/aarch64-linux-gnu/libvulkan_alias.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "libvulkan_freedreno.so"
        archive.addfile(link)
    return 5, len(driver)


def write_lock(path: Path, archive: Path, driver: bytes, count: int, expanded: int) -> dict[str, object]:
    lock = {
        "schema_version": 1,
        "profile_id": "test-turnip",
        "platform": {
            "architectures": ["aarch64"],
            "gpu_family": "qualcomm-adreno",
            "kernel_interface": "kgsl",
        },
        "source": {
            "repository": "https://github.com/example/mesa.git",
            "tag": "test",
            "commit": "1" * 40,
            "release": "https://github.com/example/mesa/releases/tag/test",
        },
        "archive": {
            "name": archive.name,
            "url": "https://github.com/example/mesa/releases/download/test/test.tar.gz",
            "size": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "member_count": count,
            "uncompressed_bytes": expanded,
        },
        "driver": {
            "relative_path": "usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so",
            "size": len(driver),
            "sha256": hashlib.sha256(driver).hexdigest(),
            "mesa_version": "test",
            "vulkan_api_version": "1.3.0",
        },
        "distribution": {
            "project_redistributes_archive": False,
            "retrieval": "test",
            "license": "test",
        },
    }
    path.write_text(json.dumps(lock), encoding="utf-8")
    return lock


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="turnip-runtime-test.") as directory:
        root = Path(directory)
        driver = b"locked-turnip-driver\n"
        archive = root / "turnip.tar.gz"
        count, expanded = make_archive(archive, driver)
        lock_path = root / "lock.json"
        write_lock(lock_path, archive, driver, count, expanded)
        lock = MODULE.load_lock(lock_path)
        MODULE.verify_archive(archive, lock)

        base = root / "steam-arm64"
        assert MODULE.install(base, archive, lock) == "installed"
        destination = base / "mesa-kgsl"
        installed = destination / "usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so"
        assert installed.read_bytes() == driver
        alias = destination / "usr/lib/aarch64-linux-gnu/libvulkan_alias.so"
        assert alias.is_symlink() and alias.readlink().as_posix() == "libvulkan_freedreno.so"
        icd = json.loads((destination / "icd.d/freedreno-private.json").read_text())
        assert icd["ICD"]["library_path"] == str(installed)
        assert MODULE.install(base, archive, lock) == "already-ready"

        corrupt = root / "corrupt.tar.gz"
        corrupt.write_bytes(archive.read_bytes() + b"x")
        expect_failure(lambda: MODULE.verify_archive(corrupt, lock), "size")

        malicious = root / "malicious.tar.gz"
        bad_count, bad_expanded = make_archive(malicious, driver, malicious="../../escape")
        bad_lock_path = root / "bad-lock.json"
        bad_lock = write_lock(
            bad_lock_path, malicious, driver, bad_count, bad_expanded
        )
        expect_failure(
            lambda: MODULE.safe_extract(malicious, root / "bad-stage", bad_lock),
            "unsafe archive member",
        )

    print("locked Turnip runtime installer tests: PASS")


if __name__ == "__main__":
    main()
