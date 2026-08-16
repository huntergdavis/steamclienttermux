#!/usr/bin/env python3
"""Build the reusable /usr tree described by a Steam Runtime mtree."""

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from typing import NoReturn


PLATFORM_RE = re.compile(r"^dir=([A-Za-z0-9._-]+)$", re.MULTILINE)
OCTAL_ESCAPE_RE = re.compile(rb"\\([0-7]{3})")


@dataclass(frozen=True)
class MtreeEntry:
    relative: Path | None
    entry_type: str
    attributes: dict[str, str]


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


def decode_mtree_word(value: str) -> str:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as error:
        fail(f"mtree word is not ASCII-escaped: {value!r}")
    decoded = OCTAL_ESCAPE_RE.sub(lambda match: bytes((int(match.group(1), 8),)), encoded)
    if b"\\" in decoded or b"\0" in decoded:
        fail(f"unsupported mtree escape: {value!r}")
    return os.fsdecode(decoded)


def relative_mtree_path(value: str) -> Path | None:
    decoded = decode_mtree_word(value)
    if decoded == ".":
        return None
    if not decoded.startswith("./"):
        fail(f"mtree path is not relative: {decoded!r}")
    pure = PurePosixPath(decoded[2:])
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        fail(f"unsafe mtree path: {decoded!r}")
    return Path(*pure.parts)


def parse_mtree(data: bytes) -> list[MtreeEntry]:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        fail(f"mtree is not ASCII-escaped: {error}")
    entries: list[MtreeEntry] = []
    seen: set[Path | None] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            fail(f"invalid mtree line {line_number}")
        relative = relative_mtree_path(fields[0])
        attributes: dict[str, str] = {}
        for field in fields[1:]:
            if "=" not in field:
                fail(f"invalid mtree attribute on line {line_number}: {field!r}")
            name, value = field.split("=", 1)
            if not name or name in attributes:
                fail(f"duplicate mtree attribute on line {line_number}: {name!r}")
            attributes[name] = value
        entry_type = attributes.get("type", "")
        if entry_type not in ("dir", "file", "link"):
            fail(f"unsupported mtree type on line {line_number}: {entry_type!r}")
        if relative in seen:
            fail(f"duplicate mtree path on line {line_number}: {fields[0]!r}")
        seen.add(relative)
        entries.append(MtreeEntry(relative, entry_type, attributes))
    if not entries or entries[0] != MtreeEntry(None, "dir", {"type": "dir"}):
        fail("mtree does not begin with its root directory")
    return entries


def content_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def file_mode(attributes: dict[str, str]) -> int:
    value = attributes.get("mode")
    if value is None or not re.fullmatch(r"[0-7]{3,4}", value):
        fail(f"invalid or missing file mode: {value!r}")
    mode = int(value, 8)
    if mode & ~0o7777:
        fail(f"file mode is out of range: {value!r}")
    return mode


def source_file(entry: MtreeEntry, files: Path, l2s_root: Path) -> Path | None:
    assert entry.relative is not None
    contents = entry.attributes.get("contents")
    if contents is None:
        source = files / entry.relative
    else:
        content_relative = relative_mtree_path(contents)
        if content_relative is None:
            fail(f"invalid contents path for {entry.relative}")
        source = files / content_relative

    if not source.exists():
        expected_size = entry.attributes.get("size")
        if not source.is_symlink() and expected_size == "0" and "sha256" not in entry.attributes:
            return None
        fail(f"runtime content is unavailable: {source}")
    metadata = source.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        resolved = source.resolve(strict=True)
        try:
            resolved.relative_to(l2s_root)
        except ValueError:
            fail(f"pseudo-hardlink resolves outside .l2s: {source} -> {resolved}")
        source = resolved
        metadata = source.stat()
    elif not stat.S_ISREG(metadata.st_mode):
        fail(f"runtime content is not a regular file: {source}")
    if not stat.S_ISREG(metadata.st_mode):
        fail(f"pseudo-hardlink target is not a regular file: {source}")

    expected_size = entry.attributes.get("size")
    expected_hash = entry.attributes.get("sha256")
    if expected_size is None or not expected_size.isdecimal():
        fail(f"invalid or missing file size for {entry.relative}")
    if metadata.st_size != int(expected_size):
        fail(f"runtime content size mismatch: {source}")
    if expected_size == "0" and expected_hash is None:
        return source
    if expected_hash is None or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        fail(f"invalid or missing content hash for {entry.relative}")
    if content_digest(source) != expected_hash:
        fail(f"runtime content hash mismatch: {source}")
    return source


def build_sysroot(stage: Path, entries: list[MtreeEntry], files: Path, l2s_root: Path) -> None:
    usr = stage / "usr"
    usr.mkdir(mode=0o755)
    directories = [entry for entry in entries if entry.entry_type == "dir" and entry.relative is not None]
    directories.sort(key=lambda entry: len(entry.relative.parts))
    for entry in directories:
        assert entry.relative is not None
        destination = usr / entry.relative
        destination.mkdir(mode=0o755)

    for entry in entries:
        if entry.entry_type != "file":
            continue
        assert entry.relative is not None
        destination = usr / entry.relative
        source = source_file(entry, files, l2s_root)
        if source is None:
            destination.touch(mode=file_mode(entry.attributes))
        else:
            shutil.copyfile(source, destination, follow_symlinks=True)
            destination.chmod(file_mode(entry.attributes))

    for entry in entries:
        if entry.entry_type != "link":
            continue
        assert entry.relative is not None
        target_value = entry.attributes.get("link")
        if target_value is None:
            fail(f"missing symlink target for {entry.relative}")
        target = decode_mtree_word(target_value)
        if not target:
            fail(f"empty symlink target for {entry.relative}")
        (usr / entry.relative).symlink_to(target)

    # Match pv_runtime_create_copy(): a Flatpak-style runtime is a merged
    # /usr, while the no-copy path expects a complete sysroot. Its own copy
    # routine adds these exact top-level links after applying usr-mtree.txt.
    for member in sorted(path.name for path in usr.iterdir()):
        if (
            member in ("bin", "etc", "sbin", "var")
            or (member.startswith("lib") and member != "libexec")
        ):
            (stage / member).symlink_to(f"usr/{member}")
    ref = usr / ".ref"
    if not ref.is_file() or ref.is_symlink():
        fail(f"runtime mtree did not provide its lock file: {ref}")
    (stage / ".ref").symlink_to("usr/.ref")


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
    platform = runtime / matches[0]
    protected_directory(platform)
    files = protected_directory(platform / "files")
    mtree_path = platform / "usr-mtree.txt.gz"
    if not mtree_path.is_file() or mtree_path.is_symlink():
        fail(f"runtime mtree is unavailable: {mtree_path}")
    l2s_root = protected_directory(l2s_root)
    try:
        with gzip.open(mtree_path, "rb") as stream:
            mtree_data = stream.read()
    except (gzip.BadGzipFile, EOFError) as error:
        fail(f"invalid runtime mtree: {error}")
    entries = parse_mtree(mtree_data)

    identity = hashlib.sha256(b"steamclienttermux-runtime-direct-v3\0")
    identity.update(os.fsencode(matches[0]))
    identity.update(b"\0")
    identity.update(mtree_data)
    digest = identity.hexdigest()
    parent = base / "runtime" / "SteamLinuxRuntime_4-arm64-direct"
    protected_directory(parent, create=True)
    destination = parent / digest
    marker = destination / ".steamclienttermux-runtime-direct-root"

    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not marker.is_file() or marker.is_symlink():
            fail(f"refusing unmarked direct runtime root: {destination}")
        protected_directory(destination)
        if marker.read_text(encoding="ascii").strip() != digest:
            fail(f"direct runtime marker mismatch: {marker}")
        file_entries = {
            entry.relative: entry
            for entry in entries
            if entry.entry_type == "file" and entry.relative is not None
        }
        critical = [
            relative
            for relative in (
                Path("bin/readlink"),
                Path("bin/env"),
                Path("lib/aarch64-linux-gnu/ld-linux-aarch64.so.1"),
            )
            if relative in file_entries
        ]
        if not critical:
            critical = [next(iter(file_entries))]
        for relative in critical:
            path = destination / "usr" / relative
            if not path.is_file() or path.is_symlink():
                fail(f"existing direct runtime is incomplete: {path}")
        for member in sorted(path.name for path in (destination / "usr").iterdir()):
            if (
                member in ("bin", "etc", "sbin", "var")
                or (member.startswith("lib") and member != "libexec")
            ):
                link = destination / member
                if not link.is_symlink() or os.readlink(link) != f"usr/{member}":
                    fail(f"existing direct runtime has an invalid merged-/usr link: {link}")
        ref = destination / ".ref"
        if not ref.is_symlink() or os.readlink(ref) != "usr/.ref":
            fail(f"existing direct runtime has an invalid lock link: {ref}")
        select_current(parent, destination)
        return destination

    stage = parent / f".prepare-{os.getpid()}"
    if stage.exists() or stage.is_symlink():
        fail(f"preparation path already exists: {stage}")
    try:
        stage.mkdir(mode=0o700)
        build_sysroot(stage, entries, files, l2s_root)
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
