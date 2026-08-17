#!/usr/bin/env python3
"""Test exact direct and explicit-loader Steam process matching."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "bin" / "steam-arm64-process-match.sh"
TARGET = "/opt/steam/steamrtarm64/steam"


def write_cmdline(root: Path, pid: int, arguments: list[str]) -> None:
    process = root / str(pid)
    process.mkdir()
    (process / "cmdline").write_bytes(
        b"\0".join(argument.encode() for argument in arguments) + b"\0"
    )


def matches(proc_root: Path, home: Path, pid: int) -> bool:
    command = (
        f"source {HELPER!s}; "
        f"steam_arm64_process_matches {pid} {TARGET!s}"
    )
    completed = subprocess.run(
        ["bash", "-c", command],
        env={
            **os.environ,
            "HOME": str(home),
            "STEAM_ARM64_PROC_ROOT": str(proc_root),
        },
        check=False,
    )
    return completed.returncode == 0


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-process-match-") as temporary:
        home = Path(temporary)
        proc_root = home / "proc"
        proc_root.mkdir()
        loader = (
            home
            / ".local/share/tgcompat/glibc/deadbeef/lib/ld-linux-aarch64.so.1"
        )
        write_cmdline(proc_root, 101, [TARGET, "-silent"])
        write_cmdline(
            proc_root,
            102,
            [str(loader), "--inhibit-cache", "--argv0", TARGET, TARGET, "-silent"],
        )
        write_cmdline(proc_root, 103, [str(loader), "--argv0", "/wrong", TARGET])
        write_cmdline(proc_root, 104, ["/tmp/ld-linux-aarch64.so.1", "--argv0", TARGET, TARGET])
        write_cmdline(proc_root, 105, [str(loader), TARGET])

        assert matches(proc_root, home, 101)
        assert matches(proc_root, home, 102)
        assert not matches(proc_root, home, 103)
        assert not matches(proc_root, home, 104)
        assert not matches(proc_root, home, 105)
        assert not matches(proc_root, home, 999)

    print("Steam native process matcher tests: PASS")


if __name__ == "__main__":
    main()
