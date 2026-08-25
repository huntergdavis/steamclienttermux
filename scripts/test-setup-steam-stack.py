#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile


SCRIPT = Path(__file__).with_name("setup-steam-stack.py")
SPEC = importlib.util.spec_from_file_location("steam_stack_setup", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BOOTSTRAP = MODULE.load_bootstrap()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_entry(archive: zipfile.ZipFile, name: str, data: bytes, mode: int) -> None:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    archive.writestr(info, data)


def fixture(root: Path) -> tuple[Path, Path, bytes]:
    seed = bytearray(20)
    seed[:6] = b"\x7fELF\x02\x01"
    seed[18:20] = (183).to_bytes(2, "little")
    seed.extend(b"setup-seed")
    archive_path = root / "seed.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        write_entry(archive, "steamrtarm64/", b"", stat.S_IFDIR | 0o755)
        write_entry(
            archive,
            "steamrtarm64\\steam",
            bytes(seed),
            stat.S_IFREG | 0o755,
        )
        write_entry(
            archive,
            "steamrtarm64/libs/libcurl.so",
            b"libcurl.so.4",
            stat.S_IFLNK | 0o777,
        )
    lock_path = root / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": "test",
                "platform": "linuxarm64",
                "build_id": 7,
                "manifest": {
                    "url": "https://client-update.steamstatic.com/test-manifest",
                    "size": 1,
                    "sha256": "0" * 64,
                },
                "seed_archive": {
                    "url": "https://client-update.steamstatic.com/test.zip",
                    "size": archive_path.stat().st_size,
                    "sha256": sha256(archive_path),
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
        ),
        encoding="utf-8",
    )
    return archive_path, lock_path, bytes(seed)


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.SetupError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    phases = MODULE.INSTALL_SHAPE["phases"]
    assert MODULE.INSTALL_SHAPE["shape_id"] == "two-apks-one-termux-command"
    assert MODULE.INSTALL_SHAPE["recommendation"] == "option-a-now-option-b-long-term"
    assert MODULE.INSTALL_SHAPE["delivery"] == {
        "current": "signed-checksummed-release-archive",
        "long_term": "signed-termux-package-repository",
        "package_format": "deb",
        "invariant": "the archive and package invoke the same setup engine and locks",
    }
    assert "thin Android control-panel APK using RUN_COMMAND" in MODULE.INSTALL_SHAPE["out_of_scope"]
    assert "ADB-assisted installation as the consumer product path" in MODULE.INSTALL_SHAPE["out_of_scope"]
    assert [phase["owner"] for phase in phases[:2]] == ["user-or-adb"] * 2
    assert [phase["state"] for phase in phases] == [
        "manual-prerequisite",
        "manual-prerequisite",
        "implemented",
        "implemented",
        "planned",
        "manual-required",
    ]
    assert "INSTALL_SHAPE=two-apks-one-termux-command" in MODULE.render_install_plan()
    planned = subprocess.run(
        [str(SCRIPT), "plan", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(planned.stdout) == MODULE.INSTALL_SHAPE

    with tempfile.TemporaryDirectory(prefix="steam-stack-setup-test.") as directory:
        root = Path(directory)
        archive, lock, seed = fixture(root)

        base = root / "stack"
        assert MODULE.status(base, lock) == "not-prepared"
        assert MODULE.prepare(base, lock, archive) == "prepared"
        assert MODULE.status(base, lock) == "ready"
        assert MODULE.prepare(base, lock, archive) == "already-ready"
        receipt_path, transaction_path = MODULE.state_paths(base)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["build_id"] == 7
        assert receipt["redistributes_valve_binaries"] is False
        assert not transaction_path.exists()

        executable = base / "client-seed/steamrtarm64/steam"
        executable.write_bytes(seed + b"modified")
        expect_failure(lambda: MODULE.status(base, lock), "identity mismatch")
        expect_failure(lambda: MODULE.rollback(base, lock, "changed"), "identity mismatch")
        executable.write_bytes(seed)
        quarantine = MODULE.rollback(base, lock, "verified")
        assert not (base / "client-seed").exists()
        assert (quarantine / "payload/steamrtarm64/steam").read_bytes() == seed
        assert (quarantine / "receipt.json").is_file()
        assert (quarantine / "ROLLBACK-COMPLETE.json").is_file()
        assert MODULE.status(base, lock) == "not-prepared"

        recovered_base = root / "recovered"
        MODULE.ensure_base(recovered_base)
        recovered_receipt, recovered_transaction = MODULE.state_paths(recovered_base)
        MODULE.atomic_json(
            recovered_transaction,
            {
                "schema_version": 1,
                "kind": "prepare",
                "destination_relative": "client-seed",
                "lock_sha256": sha256(lock),
            },
        )
        BOOTSTRAP.extract_archive(
            archive,
            recovered_base / "client-seed",
            BOOTSTRAP.load_lock(lock),
        )
        assert MODULE.status(recovered_base, lock) == "recovery-required"
        assert MODULE.prepare(recovered_base, lock, archive) == "recovered"
        assert recovered_receipt.is_file() and not recovered_transaction.exists()

        rollback_receipt = json.loads(recovered_receipt.read_text(encoding="utf-8"))
        rollback_root = recovered_base / "rollback/steam-seed-interrupted"
        rollback_root.mkdir(parents=True)
        MODULE.atomic_json(rollback_root / "receipt.json", rollback_receipt)
        MODULE.atomic_json(
            recovered_transaction,
            {
                "schema_version": 1,
                "kind": "rollback",
                "destination_relative": "client-seed",
                "quarantine_relative": "rollback/steam-seed-interrupted",
                "lock_sha256": sha256(lock),
            },
        )
        (recovered_base / "client-seed").replace(rollback_root / "payload")
        resumed = MODULE.rollback(recovered_base, lock)
        assert resumed == rollback_root
        assert not recovered_receipt.exists() and not recovered_transaction.exists()
        assert (rollback_root / "ROLLBACK-COMPLETE.json").is_file()

        unsafe_base = root / "unsafe"
        unsafe_base.mkdir()
        (unsafe_base / "client-seed").mkdir()
        expect_failure(
            lambda: MODULE.prepare(unsafe_base, lock, archive),
            "unreceipted seed destination",
        )

    source = SCRIPT.read_text(encoding="utf-8")
    assert "run_doctor(arguments.base.resolve()" in source
    assert "--skip-doctor" not in source
    print("Steam stack restartable setup tests: PASS")


if __name__ == "__main__":
    main()
