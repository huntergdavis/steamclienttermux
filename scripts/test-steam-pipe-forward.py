#!/usr/bin/env python3
"""Focused safety and wire contracts for direct Steam FIFO forwarding."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
FORWARDER = REPO_ROOT / "scripts" / "steam-pipe-forward.py"


def invoke(pipe: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(FORWARDER),
            "--pipe",
            str(pipe),
            "--expected-uid",
            str(os.geteuid()),
            "--",
            *argv,
        ],
        text=True,
        capture_output=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-pipe-forward.") as temporary:
        private = Path(temporary) / ".steam"
        private.mkdir(mode=0o700)
        pipe = private / "steam.pipe"
        os.mkfifo(pipe, mode=0o600)

        reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
        success = invoke(pipe, "/client/steam", "-applaunch", "203160", "two words")
        assert success.returncode == 0, success.stderr
        payload = b""
        for _ in range(100):
            payload += os.read(reader, 4096)
            if payload.endswith(b"\n"):
                break
            time.sleep(0.01)
        os.close(reader)
        assert payload == b"/client/steam -applaunch 203160 'two words'\n"

        unavailable = invoke(pipe, "/client/steam", "-silent")
        assert unavailable.returncode == 75, unavailable

        pipe.chmod(0o644)
        unsafe = invoke(pipe, "/client/steam")
        assert unsafe.returncode not in (0, 75)
        assert "FIFO failed validation" in unsafe.stderr
        pipe.chmod(0o600)

        newline = invoke(pipe, "/client/steam", "bad\nargument")
        assert newline.returncode not in (0, 75)
        assert "line separators" in newline.stderr

        oversized_reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
        oversized = invoke(pipe, "/client/steam", "x" * 5000)
        os.close(oversized_reader)
        assert oversized.returncode not in (0, 75)
        assert "atomic FIFO capacity" in oversized.stderr

    print("Steam FIFO forwarder tests: PASS")


if __name__ == "__main__":
    main()
