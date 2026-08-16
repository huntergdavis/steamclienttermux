#!/usr/bin/env python3
"""Materialize PRoot pseudo-hardlinks into a reusable Runtime 4 sysroot."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from typing import NoReturn


PLATFORM_RE = re.compile(r"^dir=([A-Za-z0-9._-]+)$", re.MULTILINE)


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def protected_directory(path: Path, create: bool = False) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"unsafe directory: {path}")
    if metadata.st_uid != os.geteuid():
        fail(f"directory has an unexpected owner: {path}")
    if create:
        path.chmod(0o700)
    return path.resolve(strict=True)


def content_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.digest()


def inventory(source: Path, l2s_root: Path) -> tuple[str, list[tuple[Path, Path]]]:
    identity = hashlib.sha256(b"steamclienttermux-runtime-direct-v1\0")
    links: list[tuple[Path, Path]] = []
    content_cache: dict[tuple[int, int, int, int], bytes] = {}

    for directory, directory_names, file_names in os.walk(source, followlinks=False):
        directory_names.sort()
        file_names.sort()
        root = Path(directory)
        for name in directory_names + file_names:
            path = root / name
            relative = path.relative_to(source)
            metadata = path.lstat()
            identity.update(os.fsencode(str(relative)))
            identity.update(b"\0")
            if stat.S_ISDIR(metadata.st_mode):
                identity.update(b"directory\0")
                continue
            if path.is_symlink():
                if name in directory_names:
                    fail(f"directory symlinks are not supported: {path}")
                target = path.resolve(strict=True)
                target_metadata = target.stat()
                try:
                    target.relative_to(l2s_root)
                except ValueError:
                    fail(f"pseudo-hardlink resolves outside .l2s: {path} -> {target}")
                if not stat.S_ISREG(target_metadata.st_mode):
                    fail(f"pseudo-hardlink target is not a regular file: {target}")
                key = (
                    target_metadata.st_dev,
                    target_metadata.st_ino,
                    target_metadata.st_size,
                    target_metadata.st_mtime_ns,
                )
                if key not in content_cache:
                    content_cache[key] = content_digest(target)
                identity.update(b"pseudo-hardlink\0")
                identity.update(content_cache[key])
                links.append((relative, target))
                continue
            if stat.S_ISREG(metadata.st_mode):
                identity.update(b"regular\0")
                identity.update(content_digest(path))
                continue
            fail(f"unsupported runtime entry type: {path}")

    if not links:
        fail("runtime contains no PRoot pseudo-hardlinks to materialize")
    return identity.hexdigest(), links


def remove_stage(stage: Path, parent: Path) -> None:
    if not stage.exists() and not stage.is_symlink():
        return
    if stage.parent.resolve(strict=True) != parent.resolve(strict=True):
        fail(f"refusing cleanup outside direct-root parent: {stage}")
    if not stage.name.startswith(".prepare-") or stage.is_symlink():
        fail(f"refusing unsafe preparation cleanup: {stage}")
    shutil.rmtree(stage)


def select_current(parent: Path, destination: Path) -> None:
    current = parent / "current"
    temporary = parent / f".current-{os.getpid()}"
    if current.exists() and not current.is_symlink():
        fail(f"current selector is not a symlink: {current}")
    if temporary.exists() or temporary.is_symlink():
        fail(f"temporary selector already exists: {temporary}")
    temporary.symlink_to(destination.name)
    os.replace(temporary, current)


def prepare(base: Path, l2s_root: Path) -> Path:
    base = protected_directory(base)
    runtime = base / "runtime" / "SteamLinuxRuntime_4-arm64"
    protected_directory(runtime)
    run = runtime / "run"
    if not run.is_file() or run.is_symlink():
        fail(f"runtime run script is unavailable: {run}")
    matches = PLATFORM_RE.findall(run.read_text(encoding="utf-8"))
    if len(matches) != 1:
        fail("runtime run script has an unexpected platform selector")
    source = runtime / matches[0] / "files"
    protected_directory(source)
    l2s_root = protected_directory(l2s_root)

    digest, links = inventory(source, l2s_root)
    parent = base / "runtime" / "SteamLinuxRuntime_4-arm64-direct"
    protected_directory(parent, create=True)
    destination = parent / digest
    marker = destination / ".steamclienttermux-runtime-direct-root"

    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not marker.is_file()
            or marker.is_symlink()
        ):
            fail(f"refusing unmarked direct runtime root: {destination}")
        protected_directory(destination)
        remaining = next(
            (path for path in destination.rglob("*") if path.is_symlink()), None
        )
        if remaining is not None:
            fail(f"existing direct runtime contains a symlink: {remaining}")
        if marker.read_text(encoding="ascii").strip() != digest:
            fail(f"direct runtime marker mismatch: {marker}")
        select_current(parent, destination)
        return destination

    stage = parent / f".prepare-{os.getpid()}"
    if stage.exists() or stage.is_symlink():
        fail(f"preparation path already exists: {stage}")
    try:
        shutil.copytree(source, stage, symlinks=True)
        for relative, target in links:
            staged = stage / relative
            if not staged.is_symlink():
                fail(f"copied pseudo-hardlink changed type: {staged}")
            staged.unlink()
            shutil.copy2(target, staged, follow_symlinks=True)
        remaining = next((path for path in stage.rglob("*") if path.is_symlink()), None)
        if remaining is not None:
            fail(f"direct runtime still contains a symlink: {remaining}")
        marker = stage / ".steamclienttermux-runtime-direct-root"
        marker.write_text(f"{digest}\n", encoding="ascii")
        marker.chmod(0o600)
        stage.chmod(0o700)
        os.replace(stage, destination)
    finally:
        remove_stage(stage, parent)

    select_current(parent, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path.home() / "steam-arm64")
    parser.add_argument(
        "--l2s-root",
        type=Path,
        default=Path(os.environ.get("PREFIX", "/invalid-prefix"))
        / "var/lib/proot-distro/containers/debian/rootfs/.l2s",
    )
    arguments = parser.parse_args()
    try:
        destination = prepare(arguments.base, arguments.l2s_root)
    except (OSError, RuntimeError, UnicodeError) as error:
        print(f"prepare-runtime-direct-root: {error}", file=sys.stderr)
        return 1
    print(f"Prepared direct Runtime 4 root: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
