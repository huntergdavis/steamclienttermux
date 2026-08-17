#!/usr/bin/env python3
"""Test idempotent insertion of Chromium's native shared-memory switch."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
PATCHER = REPO_ROOT / "bin" / "patch-steamwebhelper-native.sh"
ORIGINAL = 'exec taskset 0x7c $(pwd)/steamwebhelper "$@" &> ~/.steam/steam/logs/steamwebhelper.log'
PATCHED = 'exec taskset 0x7c $(pwd)/steamwebhelper --disable-dev-shm-usage "$@" &> ~/.steam/steam/logs/steamwebhelper.log'


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="webhelper-patch-test-") as temporary:
        base = Path(temporary)
        wrapper = base / "client" / "steamrtarm64" / "steamwebhelper.sh"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f"#!/bin/bash\n{ORIGINAL}\n", encoding="utf-8")
        environment = os.environ.copy()
        environment["STEAM_ARM64_BASE"] = str(base)
        for _ in range(2):
            subprocess.run(["bash", str(PATCHER)], env=environment, check=True)
        contents = wrapper.read_text(encoding="utf-8")
        if contents.count(PATCHED) != 1 or ORIGINAL in contents:
            raise AssertionError(f"unexpected patched wrapper: {contents!r}")
        backup = base / "backups" / "steamwebhelper.sh.pre-native-dev-shm"
        if ORIGINAL not in backup.read_text(encoding="utf-8"):
            raise AssertionError("patch backup does not contain the original launch line")

    print("native Steam webhelper patch tests: PASS")


if __name__ == "__main__":
    main()
