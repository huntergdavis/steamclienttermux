#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("install-tgcompat-runtime.py")
SPEC = importlib.util.spec_from_file_location("tgcompat_installer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ARTIFACTS = [
    "build/tgcompatd",
    "build/libtgcompat-exec.so",
    "build/libtgcompat-android-root.so",
    "build/libtgcompat-robust.so",
    "build/libtgcompat-mprotect.so",
    "build/libtgcompat-raknet-recv.so",
]


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def fixture_repo(root: Path, *, fail: bool = False) -> str:
    root.mkdir()
    git(root, "init", "-q")
    build = root / "scripts/build-release.sh"
    build.parent.mkdir()
    if fail:
        payload = "#!/bin/sh\nexit 23\n"
    else:
        commands = [
            "#!/bin/sh",
            "set -eu",
            "test \"${CC-unset}\" = unset",
            "test \"${LD_PRELOAD-unset}\" = unset",
            "test \"${MAKEFLAGS-unset}\" = unset",
            "mkdir -p build",
        ]
        for index, artifact in enumerate(ARTIFACTS):
            commands.append(f"printf 'artifact-{index}\\n' > {artifact}")
            commands.append(f"chmod 700 {artifact}")
        payload = "\n".join(commands) + "\n"
    build.write_text(payload, encoding="utf-8")
    build.chmod(0o755)
    session = root / "scripts/tgcompat-session.sh"
    session.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    session.chmod(0o755)
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def lock_for(repository: Path, commit: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_id": "test-tgcompat",
        "platform": {"architectures": ["aarch64"], "environment": "test"},
        "source": {"repository": f"file://{repository}", "commit": commit},
        "build": {
            "script": "scripts/build-release.sh",
            "profile": "native",
            "checks": True,
            "maximum_jobs": 2,
            "artifacts": ARTIFACTS,
            "required_files": ["scripts/tgcompat-session.sh"],
        },
    }


def expect_tgcompat_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.TgcompatError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tgcompat-runtime-test.") as directory:
        root = Path(directory)
        source = root / "source"
        commit = fixture_repo(source)
        lock = lock_for(source, commit)
        base = root / "steam-arm64"
        previous = {
            name: os.environ.get(name) for name in ("CC", "LD_PRELOAD", "MAKEFLAGS")
        }
        os.environ.update({"CC": "false", "LD_PRELOAD": "/bad.so", "MAKEFLAGS": "-n"})
        try:
            result, receipt = MODULE.install(base, lock, jobs=2)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        assert result == "installed"
        destination = base / "tgcompat" / commit
        selector = base / "tgcompat/current"
        assert selector.is_symlink() and os.readlink(selector) == commit
        assert receipt["source_commit"] == commit
        assert receipt["build_jobs"] == 2
        assert set(receipt["artifacts"]) == set(ARTIFACTS + ["scripts/tgcompat-session.sh"])
        assert MODULE.install(base, lock, jobs=1)[0] == "already-ready"

        first = destination / ARTIFACTS[0]
        first.write_bytes(b"tampered\n")
        expect_tgcompat_failure(
            lambda: MODULE.validate_install(destination, lock), "receipt"
        )

        failed_source = root / "failed-source"
        failed_commit = fixture_repo(failed_source, fail=True)
        failed_lock = lock_for(failed_source, failed_commit)
        failed_base = root / "failed-base"
        try:
            MODULE.install(failed_base, failed_lock, jobs=1)
        except subprocess.CalledProcessError as error:
            assert error.returncode == 23
        else:
            raise AssertionError("failed build unexpectedly installed")
        failed_runtime = failed_base / "tgcompat"
        assert not (failed_runtime / failed_commit).exists()
        assert not (failed_runtime / "current").exists()
        assert not any(path.name.startswith(".") for path in failed_runtime.iterdir())

        lock_path = root / "lock.json"
        product_lock = json.loads(
            (SCRIPT.parents[1] / "config/tgcompat-runtime-lock.json").read_text(
                encoding="utf-8"
            )
        )
        lock_path.write_text(json.dumps(product_lock), encoding="utf-8")
        loaded = MODULE.load_lock(lock_path)
        assert loaded["source"]["commit"] == "9b0ccde357cbf238a16c51427771ec50af154e60"
        reference = loaded["tested_reference"]["artifact_sha256"]
        assert len(reference) == 6
        assert all(len(value) == 64 for value in reference.values())
        assert hashlib.sha256(b"").hexdigest() not in reference.values()

    print("locked tgcompat native runtime installer tests: PASS")


if __name__ == "__main__":
    main()
