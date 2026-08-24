#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile


SCRIPT = Path(__file__).with_name("build-release-archive.py")
SPEC = importlib.util.spec_from_file_location("release_archive", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(root: Path, *arguments: str, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def write(root: Path, name: str, payload: bytes, mode: int = 0o644) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(mode)


def fixture_repo(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Release Test")
    git(root, "config", "user.email", "release@example.invalid")
    files = {
        "README.md": b"# fixture\n",
        ".gitignore": b"dist/\n",
        "config/steam-arm64-bootstrap-lock.json": b"{}\n",
        "scripts/bootstrap-steam-arm64-client.py": b"#!/usr/bin/env python3\n",
        "scripts/build-release-archive.py": SCRIPT.read_bytes(),
        "scripts/check-project.sh": b"#!/bin/sh\nexit 0\n",
        "docs/PRODUCTIZATION_RESEARCH.md": b"# research\n",
        "docs/evidence/gtaiv-main-menu-2026-08-13.png": b"png-fixture",
        "docs/evidence/excluded.png": b"must-not-ship",
        "docs/benchmark-series/excluded.json": b"{}\n",
        "client/proprietary-steam": b"must-not-ship",
    }
    for name, payload in files.items():
        mode = 0o755 if name.startswith("scripts/") else 0o644
        write(root, name, payload, mode)
    git(root, "add", ".")
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
    )
    git(root, "commit", "-q", "-m", "fixture", environment=environment)
    return git(root, "rev-parse", "HEAD")


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.ReleaseError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="release-archive-test.") as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        commit = fixture_repo(root)
        original_root = MODULE.REPO_ROOT
        MODULE.REPO_ROOT = root
        try:
            assert MODULE.resolve_commit("HEAD") == commit
            first, first_manifest = MODULE.build_archive(commit)
            second, second_manifest = MODULE.build_archive(commit)
            assert first == second
            assert first_manifest == second_manifest
            assert first_manifest["license_present"] is False
            archive = first_manifest["archive"]
            assert archive["sha256"] == hashlib.sha256(first).hexdigest()
            assert archive["size"] == len(first)
            destination = Path(directory) / "release"
            MODULE.write_release(destination, first, first_manifest)
            assert json.loads((destination / "release-manifest.json").read_text()) == (
                first_manifest
            )
            archive_path = destination / archive["filename"]
            assert archive_path.read_bytes() == first
            expect_failure(
                lambda: MODULE.write_release(destination, first, first_manifest),
                "destination already exists",
            )
            with zipfile.ZipFile(archive_path) as package:
                infos = package.infolist()
                names = [info.filename for info in infos]
                prefix = first_manifest["prefix"]
                assert f"{prefix}/README.md" in names
                assert f"{prefix}/scripts/build-release-archive.py" in names
                assert f"{prefix}/RELEASE-MANIFEST.json" in names
                assert not any("excluded" in name for name in names)
                assert not any("proprietary-steam" in name for name in names)
                assert all(info.date_time == MODULE.FIXED_ZIP_TIME for info in infos)
                assert all(info.compress_type == zipfile.ZIP_STORED for info in infos)
                executable = package.getinfo(f"{prefix}/scripts/check-project.sh")
                assert stat.S_IMODE(executable.external_attr >> 16) == 0o755
                embedded = json.loads(
                    package.read(f"{prefix}/RELEASE-MANIFEST.json")
                )
                assert embedded["source_commit"] == commit
                assert embedded["redistributes_valve_binaries"] is False
            expect_failure(lambda: MODULE.resolve_commit("missing"), "git rev-parse")
        finally:
            MODULE.REPO_ROOT = original_root
    print("deterministic release archive tests: PASS")


if __name__ == "__main__":
    main()
