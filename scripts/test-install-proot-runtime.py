#!/usr/bin/env python3
"""Contract tests for the locked patched PRoot installer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("install-proot-runtime.py")
SPEC = importlib.util.spec_from_file_location("install_proot_runtime", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PATCH_NAMES = (
    "proot-steam-android.patch",
    "proot-link2symlink-getdents.patch",
    "proot-link2symlink-host-path.patch",
    "proot-link2symlink-force-exdev.patch",
    "proot-runtime-bind-exact-detranslate.patch",
    "proot-pivot-detached-root.patch",
    "proot-pivot-drop-stale-bindings.patch",
    "proot-mountinfo-escape-paths.patch",
    "proot-runtime-mount-stack.patch",
    "proot-runtime-directory-bind-target.patch",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*arguments: str, cwd: Path) -> str:
    return subprocess.check_output(arguments, cwd=cwd, text=True).strip()


def make_source(root: Path) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    run("git", "init", "-q", cwd=source)
    run("git", "config", "user.name", "Test", cwd=source)
    run("git", "config", "user.email", "test@example.invalid", cwd=source)
    (source / "tracked").write_text("base\n", encoding="utf-8")
    run("git", "add", "tracked", cwd=source)
    run("git", "commit", "-qm", "base", cwd=source)
    return source, run("git", "rev-parse", "HEAD", cwd=source)


def make_fixture(root: Path) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    repo = root / "release"
    patches = repo / "patches"
    patches.mkdir(parents=True)
    records = []
    for index, name in enumerate(PATCH_NAMES):
        patch = patches / name
        patch.write_text(f"patch {index}\n", encoding="utf-8")
        records.append({"filename": name, "sha256": sha256(patch)})

    source, commit = make_source(root)
    builder = repo / "scripts/build-proot.sh"
    builder.parent.mkdir()
    patch_names = " ".join(PATCH_NAMES)
    body = f"""#!/bin/bash
set -euo pipefail
dest=$1
git clone -q {shlex.quote(str(source))} "$dest"
git -C "$dest" checkout -q --detach {commit}
printf 'patched\n' >>"$dest/tracked"
mkdir -p "$dest/src"
cat >"$dest/src/proot" <<'EOF'
#!/bin/sh
printf 'proot test\n'
EOF
chmod 755 "$dest/src/proot"
diff_sha=$(git -C "$dest" diff --binary | sha256sum | awk '{{print $1}}')
proot_sha=$(sha256sum "$dest/src/proot" | awk '{{print $1}}')
cat >"$dest/.steamclienttermux-patchset" <<EOF
commit={commit}
patchset_sha256={'1' * 64}
diff_sha256=$diff_sha
patches={patch_names}
build_profile=portable
build_options_sha256={'2' * 64}
proot_sha256=$proot_sha
EOF
"""
    builder.write_text(body, encoding="utf-8")
    builder.chmod(0o755)

    prefix = root / "prefix"
    (prefix / "bin").mkdir(parents=True)
    bash = prefix / "bin/bash"
    bash.write_text("#!/bin/sh\nexec /bin/bash \"$@\"\n", encoding="utf-8")
    bash.chmod(0o755)

    lock = {
        "schema_version": 1,
        "profile_id": "test-proot-portable-v1",
        "platform": {
            "architectures": ["aarch64"],
            "environment": "official-termux",
            "storage": "private-internal",
        },
        "source": {
            "repository": "https://github.com/termux/proot.git",
            "commit": commit,
        },
        "build": {
            "profile": "portable",
            "enable_noderef_fastpath": False,
            "script": "scripts/build-proot.sh",
            "script_sha256": sha256(builder),
        },
        "patches": records,
        "runtime": {
            "destination": "src/proot-production",
            "binary": "src/proot",
            "stamp": ".steamclienttermux-patchset",
            "receipt": ".steamclienttermux-proot-receipt.json",
        },
    }
    lock_path = repo / "config/proot-runtime-lock.json"
    lock_path.parent.mkdir()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    home = root / "home"
    home.mkdir()
    return repo, prefix, home, lock_path, lock


def expect_failure(callable_object, message: str) -> None:
    try:
        callable_object()
    except (MODULE.ProotError, subprocess.CalledProcessError):
        return
    raise AssertionError(message)


def main() -> int:
    production_builder = SCRIPT.with_name("build-proot.sh")
    production_lock_path = SCRIPT.parents[1] / "config/proot-runtime-lock.json"
    production_lock = MODULE.load_lock(production_lock_path)
    MODULE.verify_inputs(production_lock, production_builder, SCRIPT.parents[1])

    with tempfile.TemporaryDirectory(prefix="proot-runtime-test.") as name:
        root = Path(name)
        repo, prefix, home, lock_path, raw_lock = make_fixture(root)
        lock = MODULE.load_lock(lock_path)
        builder = repo / "scripts/build-proot.sh"
        base = home / "steam-arm64"
        smoke_root = home / "glibc"
        (smoke_root / "lib").mkdir(parents=True)
        (smoke_root / "lib/ld-linux-aarch64.so.1").write_text("fixture\n")

        status, receipt = MODULE.install(
            base,
            prefix,
            lock_path,
            builder,
            lock,
            repo_root=repo,
            home=home,
            jobs=2,
            glibc_root=smoke_root,
        )
        assert status == "installed"
        assert receipt["source_commit"] == raw_lock["source"]["commit"]
        destination = base / "src/proot-production"
        assert (destination / "src/proot").is_file()

        status, repeated = MODULE.install(
            base,
            prefix,
            lock_path,
            builder,
            lock,
            repo_root=repo,
            home=home,
            glibc_root=smoke_root,
        )
        assert status == "already-ready" and repeated == receipt

        binary = destination / "src/proot"
        binary.write_text("tampered\n", encoding="utf-8")
        expect_failure(
            lambda: MODULE.install(
                base,
                prefix,
                lock_path,
                builder,
                lock,
                repo_root=repo,
                home=home,
                glibc_root=smoke_root,
            ),
            "tampered installed binary was accepted",
        )

        other_base = home / "other"
        builder.write_text(builder.read_text(encoding="utf-8") + "# tamper\n", encoding="utf-8")
        expect_failure(
            lambda: MODULE.install(
                other_base,
                prefix,
                lock_path,
                builder,
                lock,
                repo_root=repo,
                home=home,
                glibc_root=smoke_root,
            ),
            "tampered builder was accepted",
        )

        expect_failure(
            lambda: MODULE.install(
                Path("/tmp/outside-private-home"),
                prefix,
                lock_path,
                builder,
                lock,
                repo_root=repo,
                home=home,
                glibc_root=smoke_root,
            ),
            "outside-home base was accepted",
        )

        unmanaged = home / "unmanaged"
        (unmanaged / "src/proot-production").mkdir(parents=True)
        raw_lock["build"]["script_sha256"] = sha256(builder)
        lock_path.write_text(json.dumps(raw_lock), encoding="utf-8")
        lock = MODULE.load_lock(lock_path)
        expect_failure(
            lambda: MODULE.install(
                unmanaged,
                prefix,
                lock_path,
                builder,
                lock,
                repo_root=repo,
                home=home,
                glibc_root=smoke_root,
            ),
            "unmanaged destination was accepted",
        )

    print("install-proot-runtime contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
