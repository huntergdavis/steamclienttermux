#!/usr/bin/env python3
"""Test the native Steam-only lsof response against a synthetic proc tree."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "diagnostics" / "native-lsof.c"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="native-lsof-test-") as temporary:
        root = Path(temporary)
        proc_root = root / "proc"
        process = proc_root / "4321"
        process.mkdir(parents=True)
        (process / "cmdline").write_bytes(
            b"/opt/steamrtarm64/steamwebhelper\0"
            b"--utility-sub-type=network.mojom.NetworkService\0"
        )
        (process / "status").write_text(
            "Name:\thelper\nPPid:\t1234\n", encoding="utf-8"
        )
        helper = root / "native-lsof"
        subprocess.run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-Wpedantic",
                "-Wformat=2",
                "-Wshadow",
                str(SOURCE),
                "-o",
                str(helper),
            ],
            check=True,
        )
        environment = os.environ.copy()
        environment["STEAM_ARM64_LSOF_PROC_ROOT"] = str(proc_root)
        completed = subprocess.run(
            [str(helper), "-F", "pRun", "-i", "TCP@127.0.0.1:24680"],
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
        expected = (
            f"p4321\nR1234\nu{os.geteuid()}\n"
            "n127.0.0.1:24680->127.0.0.1:27060\n"
        )
        if completed.stdout != expected:
            raise AssertionError(f"unexpected native lsof output: {completed.stdout!r}")
        unsupported = subprocess.run(
            [str(helper), "-p", "4321"], env=environment, check=False
        )
        if unsupported.returncode != 1:
            raise AssertionError(
                f"unsupported query returned {unsupported.returncode}, expected 1"
            )

    print("native lsof tests: PASS")


if __name__ == "__main__":
    main()
