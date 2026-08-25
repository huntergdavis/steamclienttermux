#!/usr/bin/env python3
"""Contract tests for the locked minimal Debian runtime installer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).with_name("install-debian-runtime.py")
SPEC = importlib.util.spec_from_file_location("install_debian_runtime", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expect_failure(callback, message: str) -> None:
    try:
        callback()
    except MODULE.DebianError:
        return
    raise AssertionError(message)


def main() -> int:
    production = MODULE.load_lock(SCRIPT.parents[1] / "config/debian-runtime-lock.json")
    assert production["container"]["name"] == "steam-arm64-runtime"
    assert "chromium" not in production["packages"]

    with tempfile.TemporaryDirectory(prefix="debian-runtime-test.") as name:
        root = Path(name)
        home = root / "home"
        base = home / "steam-arm64"
        prefix = root / "prefix"
        containers = prefix / "var/lib/proot-distro/containers"
        (prefix / "bin").mkdir(parents=True)
        containers.mkdir(parents=True)
        home.mkdir()
        patched_proot = base / "src/proot-production/src/proot"
        patched_proot.parent.mkdir(parents=True)
        patched_proot.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        patched_proot.chmod(0o755)

        archive = root / "debian.tar.xz"
        archive.write_bytes(b"locked Debian fixture\n")
        lock = json.loads(json.dumps(production))
        lock["profile_id"] = "test-debian-runtime-v1"
        lock["archive"].update(
            {
                "filename": "debian-fixture.tar.xz",
                "size": archive.stat().st_size,
                "sha256": sha256(archive),
            }
        )
        lock_path = root / "debian-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        lock = MODULE.load_lock(lock_path)

        fake = prefix / "bin/proot-distro"
        fake.write_text(
            """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

prefix=Path(os.environ['PREFIX'])
args=sys.argv[1:]
if args[0] == 'install':
    assert '--quiet' in args
    alias=args[args.index('--name')+1]
    root=prefix/'var/lib/proot-distro/containers'/alias/'rootfs'
    required=os.environ['FAKE_REQUIRED'].split(':')
    for relative in required:
        path=root/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('fixture\\n')
    raise SystemExit(0)
if args[0] == 'login':
    if '/usr/bin/apt-get' in args:
        command=args[args.index('/usr/bin/apt-get')+1]
        if command in ('update','install'):
            assert '-qq' in args
    if '/usr/bin/dpkg-query' in args:
        marker=next(i for i,v in enumerate(args) if v.startswith('-f='))
        for package in args[marker+1:]:
            print(f'{package}\\t1.test')
    raise SystemExit(0)
raise SystemExit(2)
""",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        old_prefix = MODULE.os.environ.get("PREFIX")
        old_required = MODULE.os.environ.get("FAKE_REQUIRED")
        MODULE.os.environ["PREFIX"] = str(prefix)
        MODULE.os.environ["FAKE_REQUIRED"] = ":".join(lock["acceptance"]["required_files"])
        try:
            status, receipt = MODULE.install(
                base,
                prefix,
                lock_path,
                lock,
                archive_input=archive,
                home=home,
            )
            assert status == "installed"
            assert receipt["acceptance"] == "pass"
            assert set(receipt["packages"]) == set(lock["packages"])
            destination = containers / "steam-arm64-runtime"
            assert destination.is_dir() and not destination.is_symlink()

            linked_relative = lock["acceptance"]["required_files"][1]
            linked = destination / "rootfs" / linked_relative
            linked_target = linked.with_name(f"{linked.name}.fixture")
            linked.rename(linked_target)
            linked.symlink_to(linked_target.name)

            status, repeated = MODULE.install(
                base,
                prefix,
                lock_path,
                lock,
                archive_input=archive,
                home=home,
            )
            assert status == "already-ready" and repeated == receipt

            linked.unlink()
            linked.symlink_to(archive)
            expect_failure(
                lambda: MODULE.install(
                    base,
                    prefix,
                    lock_path,
                    lock,
                    archive_input=archive,
                    home=home,
                ),
                "required-file symlink escaping the rootfs was accepted",
            )
            linked.unlink()
            linked.symlink_to(linked_target.name)

            required = destination / "rootfs" / lock["acceptance"]["required_files"][0]
            required.unlink()
            expect_failure(
                lambda: MODULE.install(
                    base,
                    prefix,
                    lock_path,
                    lock,
                    archive_input=archive,
                    home=home,
                ),
                "missing accepted runtime file was ignored",
            )
        finally:
            if old_prefix is None:
                MODULE.os.environ.pop("PREFIX", None)
            else:
                MODULE.os.environ["PREFIX"] = old_prefix
            if old_required is None:
                MODULE.os.environ.pop("FAKE_REQUIRED", None)
            else:
                MODULE.os.environ["FAKE_REQUIRED"] = old_required

    print("install-debian-runtime contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
