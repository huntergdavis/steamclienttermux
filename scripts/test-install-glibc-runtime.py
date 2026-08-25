#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("install-glibc-runtime.py")
SPEC = importlib.util.spec_from_file_location("glibc_installer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def tgcompat_repo(root: Path) -> str:
    root.mkdir()
    git(root, "init", "-q")
    for relative in ("build/tgcompatd", "scripts/tgcompat-session.sh"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    stage = root / "integration/termux-glibc/stage-extracted-package.sh"
    stage.parent.mkdir(parents=True)
    stage.write_text(
        r'''#!/bin/bash
set -euo pipefail
package=$1
deploy=$2
sha=$(sha256sum "$package" | awk '{print $1}')
test -n "${TGCOMPAT_SOCKET:-}"
test "${#TGCOMPAT_SOCKET}" -lt 108
case "$TGCOMPAT_SOCKET" in "$PREFIX"/tmp/.tgc.*/s) ;; *) exit 41;; esac
mkdir -p "$deploy" "$TMPDIR/extracted"
dpkg-deb -x "$package" "$TMPDIR/extracted"
candidate=$TMPDIR/extracted$PREFIX/glibc
test -x "$candidate/lib/ld-linux-aarch64.so.1"
test -f "$candidate/lib/libc.so.6"
printf '%s\n' "$sha" >"$candidate/.tgcompat-package-sha256"
mv "$candidate" "$deploy/$sha"
ln -s "$sha" "$deploy/current"
''',
        encoding="utf-8",
    )
    stage.chmod(0o755)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return git(root, "rev-parse", "HEAD")


def fake_prefix(root: Path) -> Path:
    prefix = root / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "tmp").mkdir()
    bash = prefix / "bin/bash"
    bash.write_text("#!/bin/sh\nexec /bin/bash \"$@\"\n", encoding="utf-8")
    bash.chmod(0o755)
    return prefix


def package(root: Path, prefix: Path) -> Path:
    tree = root / "package-tree"
    (tree / "DEBIAN").mkdir(parents=True)
    payload = tree / prefix.relative_to("/") / "glibc/lib"
    payload.mkdir(parents=True)
    (tree / "DEBIAN/control").write_text(
        "Package: glibc\n"
        "Version: 2.44\n"
        "Architecture: aarch64\n"
        "Maintainer: Test <test@example.invalid>\n"
        "Description: fixture\n",
        encoding="utf-8",
    )
    loader = payload / "ld-linux-aarch64.so.1"
    loader.write_text("fixture-loader\n", encoding="utf-8")
    loader.chmod(0o755)
    (payload / "libc.so.6").write_text("fixture-libc\n", encoding="utf-8")
    output = root / "glibc_2.44_aarch64.deb"
    subprocess.run(
        ["dpkg-deb", "--build", str(tree), str(output)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return output


def fixture_lock(source: Path, commit: str, artifact: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile_id": "fixture-glibc",
        "platform": {
            "architectures": ["aarch64"],
            "environment": "test",
            "storage": "private-internal",
        },
        "sources": {
            "tgcompat": {"repository": f"file://{source}", "commit": commit},
            "glibc_packages": {
                "repository": "https://github.com/termux/glibc-packages.git",
                "commit": "1" * 40,
            },
            "termux_packages": {
                "repository": "https://github.com/termux/termux-packages.git",
                "commit": "2" * 40,
            },
        },
        "source_build": {
            "package": "glibc",
            "version": "2.44",
            "source_sha256": hashlib.sha256(b"fixture-source").hexdigest(),
        },
        "artifact": {
            "filename": "glibc_2.44_aarch64.deb",
            "package": "glibc",
            "version": "2.44",
            "architecture": "aarch64",
            "size": artifact.stat().st_size,
            "sha256": MODULE.sha256_file(artifact),
        },
        "distribution": {
            "project_redistributes_binary": True,
            "source_offer": "exact public commits in this lock",
            "licenses": ["LGPL-2.1-or-later"],
        },
    }


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.GlibcError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    if not shutil.which("dpkg-deb"):
        raise AssertionError("fixture requires dpkg-deb")
    with tempfile.TemporaryDirectory(prefix="glibc-runtime-test.") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        prefix = fake_prefix(root)
        artifact = package(root, prefix)
        source = root / "tgcompat-source"
        commit = tgcompat_repo(source)
        lock = fixture_lock(source, commit, artifact)
        base = home / "steam-arm64"
        installed = base / "tgcompat" / commit
        installed.parent.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "-q", f"file://{source}", str(installed)],
            check=True,
        )
        os.symlink(commit, installed.parent / "current")
        deploy = home / ".local/share/tgcompat/glibc"

        result, receipt = MODULE.install(
            base, deploy, prefix, artifact, lock, home=home
        )
        assert result == "installed"
        package_sha = receipt["package_sha256"]
        destination = deploy / package_sha
        cache = base / "glibc/packages/glibc_2.44_aarch64.deb"
        assert package_sha == lock["artifact"]["sha256"]
        assert deploy.joinpath("current").is_symlink()
        assert os.readlink(deploy / "current") == package_sha
        assert cache.read_bytes() == artifact.read_bytes()
        assert not any((base / "glibc/work").iterdir())
        assert MODULE.install(
            base, deploy, prefix, artifact, lock, home=home
        )[0] == "already-ready"

        (destination / "lib/libc.so.6").write_text("tampered\n", encoding="utf-8")
        expect_failure(
            lambda: MODULE.validate_install(destination, cache, lock), "receipt"
        )

        bad_package = root / "bad.deb"
        bad_package.write_bytes(artifact.read_bytes() + b"tamper")
        empty_home = root / "empty-home"
        empty_home.mkdir()
        expect_failure(
            lambda: MODULE.install(
                empty_home / "base",
                empty_home / "deploy",
                prefix,
                bad_package,
                lock,
                home=empty_home,
            ),
            "release lock",
        )
        assert not (empty_home / "base").exists()
        expect_failure(
            lambda: MODULE.install(
                root / "outside",
                deploy,
                prefix,
                artifact,
                lock,
                home=home,
            ),
            "private Termux HOME",
        )

        product = MODULE.load_lock(
            SCRIPT.parents[1] / "config/glibc-runtime-lock.json"
        )
        assert product["sources"]["termux_packages"]["commit"] == (
            "17acce9ca7978bb80923b5d481cce80822e0b85a"
        )
        assert product["artifact"]["sha256"] == (
            "52f5ce13b66fc3307f48285d32b72951472493e91b96fc3e08c0c42772d999f3"
        )

    print("locked patched-glibc artifact installer tests: PASS")


if __name__ == "__main__":
    main()
