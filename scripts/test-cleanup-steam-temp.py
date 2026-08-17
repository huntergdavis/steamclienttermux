#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("cleanup-steam-temp.py")


def run(prefix, proc_root, now, apply=False):
    command = [
        "python3",
        str(SCRIPT),
        "--prefix",
        str(prefix),
        "--proc-root",
        str(proc_root),
        "--now",
        str(now),
        "--minimum-age",
        "60",
    ]
    if apply:
        command.append("--apply")
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        prefix = root / "prefix"
        tmp_root = prefix / "tmp"
        proc_root = root / "proc"
        tmp_root.mkdir(parents=True)
        proc_root.mkdir()
        uid = os.getuid()
        now = 10_000.0

        stale = tmp_root / f"u{uid}-Shm_deadbeef"
        opened = tmp_root / f"u{uid}-Shm_cafebabe"
        too_new = tmp_root / f"u{uid}-Shm_1234abcd"
        wrong_mode = tmp_root / f"u{uid}-Shm_abcdef12"
        malformed = tmp_root / "u0-Shm_not-hex"
        for candidate in (stale, opened, too_new, wrong_mode, malformed):
            candidate.write_bytes(candidate.name.encode())
            candidate.chmod(0o700)
            os.utime(candidate, (now - 120, now - 120))
        os.utime(too_new, (now - 10, now - 10))
        wrong_mode.chmod(0o600)

        descriptor_root = proc_root / "100/fd"
        descriptor_root.mkdir(parents=True)
        os.symlink(opened, descriptor_root / "3")

        dry = run(prefix, proc_root, now)
        assert dry["mode"] == "dry_run"
        assert dry["eligible_closed_count"] == 1
        assert dry["open_count"] == 1
        assert stale.exists()
        assert opened.exists()

        applied = run(prefix, proc_root, now, apply=True)
        assert applied["mode"] == "apply"
        assert applied["eligible_closed_count"] == 1
        assert not stale.exists()
        assert opened.exists()
        assert too_new.exists()
        assert wrong_mode.exists()
        assert malformed.exists()

    print("Steam temp cleanup tests: PASS")


if __name__ == "__main__":
    main()
