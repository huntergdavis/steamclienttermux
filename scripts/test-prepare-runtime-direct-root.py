#!/usr/bin/env python3

import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("prepare-runtime-direct-root.py")


def run(base: Path, l2s: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--base", str(base), "--l2s-root", str(l2s)],
        text=True,
        capture_output=True,
        check=check,
    )


def file_entry(path: str, data: bytes, mode: int, contents: str | None = None) -> str:
    fields = [
        path,
        "type=file",
        f"mode={mode:o}",
        "time=1700000000.0",
        f"size={len(data)}",
    ]
    if data:
        fields.append(f"sha256={hashlib.sha256(data).hexdigest()}")
    if contents is not None:
        fields.append(f"contents={contents}")
    return " ".join(fields)


def fixture(root: Path) -> tuple[Path, Path, Path]:
    base = root / "base"
    runtime = base / "runtime" / "SteamLinuxRuntime_4-arm64"
    platform = runtime / "platform-fixture"
    source = platform / "files"
    l2s = root / "rootfs" / ".l2s"
    source.mkdir(parents=True)
    l2s.mkdir(parents=True)
    (runtime / "run").write_text("dir=platform-fixture\n", encoding="utf-8")

    ordinary = b"ordinary runtime data\n"
    content = source / "ab" / "fixture-1.bin"
    content.parent.mkdir()
    content.write_bytes(ordinary)
    backing = l2s / ".l2s.tool0001"
    tool_data = b"materialized executable\n"
    backing.write_bytes(tool_data)
    backing.chmod(0o755)
    (source / "bin").mkdir()
    (source / "bin" / "tool").symlink_to(backing)
    (source / ".ref").touch()

    mtree = "\n".join(
        (
            "#mtree",
            ". type=dir",
            "./bin type=dir",
            "./etc type=dir",
            "./share type=dir",
            file_entry("./bin/tool", tool_data, 0o755),
            "./bin/sh type=link link=tool",
            file_entry("./.ref", b"", 0o644),
            file_entry("./share/ordinary", ordinary, 0o644, "./ab/fixture-1.bin"),
            file_entry("./share/empty", b"", 0o600),
            file_entry("./share/name\\040with\\040spaces", ordinary, 0o644, "./ab/fixture-1.bin"),
            "",
        )
    ).encode("ascii")
    with gzip.GzipFile(platform / "usr-mtree.txt.gz", "wb", mtime=0) as stream:
        stream.write(mtree)
    return base, l2s, backing


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="runtime-direct-root.") as directory:
        root = Path(directory)
        base, l2s, backing = fixture(root)
        run(base, l2s)

        current = base / "runtime" / "SteamLinuxRuntime_4-arm64-direct" / "current"
        assert current.is_symlink()
        destination = current.resolve(strict=True)
        tool = destination / "usr" / "bin" / "tool"
        assert tool.is_file() and not tool.is_symlink()
        assert tool.read_bytes() == backing.read_bytes()
        assert tool.stat().st_mode & 0o777 == 0o755
        assert (destination / "usr" / "share" / "ordinary").read_bytes() == b"ordinary runtime data\n"
        assert (destination / "usr" / "share" / "empty").read_bytes() == b""
        assert (destination / "usr" / "share" / "empty").stat().st_mode & 0o777 == 0o600
        assert (destination / "usr" / "share" / "name with spaces").is_file()
        assert (destination / "usr" / "bin" / "sh").is_symlink()
        assert os.readlink(destination / "usr" / "bin" / "sh") == "tool"
        assert (destination / "bin").is_symlink()
        assert os.readlink(destination / "bin") == "usr/bin"
        assert (destination / "etc").is_symlink()
        assert os.readlink(destination / "etc") == "usr/etc"
        assert (destination / ".ref").is_symlink()
        assert os.readlink(destination / ".ref") == "usr/.ref"
        assert (destination / ".steamclienttermux-runtime-direct-root").is_file()
        assert (
            destination
            / base.relative_to("/")
            / "mesa-kgsl/usr/share/drirc.d"
        ).is_dir()
        assert (
            destination
            / base.relative_to("/")
            / "removable-library/steamapps/common"
        ).is_dir()

        first_destination = destination
        run(base, l2s)
        assert current.resolve(strict=True) == first_destination

    with tempfile.TemporaryDirectory(prefix="runtime-direct-root-unsafe.") as directory:
        root = Path(directory)
        base, l2s, _ = fixture(root)
        unsafe = root / "outside"
        unsafe.write_bytes(b"outside\n")
        tool = base / "runtime" / "SteamLinuxRuntime_4-arm64" / "platform-fixture" / "files" / "bin" / "tool"
        tool.unlink()
        tool.symlink_to(unsafe)
        rejected = run(base, l2s, check=False)
        assert rejected.returncode != 0
        assert "outside .l2s" in rejected.stderr

    print("direct Runtime 4 root tests: PASS")


if __name__ == "__main__":
    main()
