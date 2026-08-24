#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
WAITER = ROOT / "scripts/wait-steam-app-launch.sh"
INSTALLER = ROOT / "scripts/install-project-files.sh"


def current_start_ticks():
    stat = Path(f"/proc/{os.getpid()}/stat").read_text(encoding="ascii")
    return stat.rsplit(") ", 1)[1].split()[19]


def command(log, offset, appid="203160", ticks=None, timeout="2"):
    return [
        "bash",
        str(WAITER),
        "--steam-pid",
        str(os.getpid()),
        "--steam-start-ticks",
        ticks or current_start_ticks(),
        "--appid",
        appid,
        "--log",
        str(log),
        "--offset",
        str(offset),
        "--timeout",
        timeout,
    ]


def main():
    source = WAITER.read_text(encoding="utf-8")
    assert "tail --pid=\"$$\" --sleep-interval=0.1" in source
    assert "fields[19]" in source
    assert '"AppID $appid adding PID"' in source
    assert "stat -c" not in source
    assert "grep -F" not in source
    installer = INSTALLER.read_text(encoding="utf-8")
    assert '"$base/compat-bin/wait-steam-app-launch.sh" 700' in installer

    with tempfile.TemporaryDirectory(prefix="steam-app-wait.") as directory:
        log = Path(directory) / "gameprocess_log.txt"
        log.write_text("AppID 203160 adding PID 1\n", encoding="utf-8")
        offset = log.stat().st_size
        started = time.monotonic()
        process = subprocess.Popen(command(log, offset))
        time.sleep(0.15)
        assert process.poll() is None, "waiter accepted a marker before its offset"
        with log.open("a", encoding="utf-8") as stream:
            stream.write("AppID 12210 adding PID 2\n")
            stream.flush()
            time.sleep(0.15)
            assert process.poll() is None, "waiter accepted the wrong AppID"
            stream.write("AppID 203160 adding PID 3\n")
            stream.flush()
        assert process.wait(timeout=2) == 0
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, elapsed

        stale = subprocess.run(
            command(log, log.stat().st_size, ticks=str(int(current_start_ticks()) + 1)),
            check=False,
        )
        assert stale.returncode != 0

        linked = Path(directory) / "linked.log"
        linked.symlink_to(log)
        rejected = subprocess.run(
            command(linked, 0), text=True, capture_output=True, check=False
        )
        assert rejected.returncode == 2

    print("Steam AppID incremental wait tests: PASS")


if __name__ == "__main__":
    main()
