#!/usr/bin/env python3

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


def fixture(root: Path) -> tuple[Path, Path, Path]:
    base = root / "base"
    runtime = base / "runtime" / "SteamLinuxRuntime_4-arm64"
    source = runtime / "platform-fixture" / "files"
    l2s = root / "rootfs" / ".l2s"
    source.mkdir(parents=True)
    l2s.mkdir(parents=True)
    (runtime / "run").write_text("dir=platform-fixture\n", encoding="utf-8")
    (source / "regular").write_bytes(b"ordinary runtime data\n")
    backing = l2s / ".l2s.tool0001"
    backing.write_bytes(b"materialized executable\n")
    backing.chmod(0o755)
    (source / "bin").mkdir()
    (source / "bin" / "tool").symlink_to(backing)
    return base, l2s, backing


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="runtime-direct-root.") as directory:
        root = Path(directory)
        base, l2s, backing = fixture(root)
        run(base, l2s)

        current = base / "runtime" / "SteamLinuxRuntime_4-arm64-direct" / "current"
        assert current.is_symlink()
        destination = current.resolve(strict=True)
        tool = destination / "bin" / "tool"
        assert tool.is_file() and not tool.is_symlink()
        assert tool.read_bytes() == backing.read_bytes()
        assert tool.stat().st_mode & 0o777 == 0o755
        assert (destination / "regular").read_bytes() == b"ordinary runtime data\n"
        assert (destination / ".steamclienttermux-runtime-direct-root").is_file()

        first_destination = destination
        run(base, l2s)
        assert current.resolve(strict=True) == first_destination

        unsafe = root / "outside"
        unsafe.write_bytes(b"outside\n")
        (base / "runtime" / "SteamLinuxRuntime_4-arm64" / "platform-fixture" / "files" / "bad").symlink_to(unsafe)
        rejected = run(base, l2s, check=False)
        assert rejected.returncode != 0
        assert "outside .l2s" in rejected.stderr

    print("direct Runtime 4 root tests: PASS")


if __name__ == "__main__":
    main()
