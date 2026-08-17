#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-gtaiv-native.sh")


def main():
    with tempfile.TemporaryDirectory(prefix="start-gtaiv-native.") as directory:
        root = Path(directory)
        capture = root / "capture"
        count_path = root / "count"
        game_log = root / "gameprocess_log.txt"
        proc_root = root / "proc"
        proc_root.mkdir()
        fake_xdotool = root / "xdotool"
        fake_xdotool.write_text(
            "#!/bin/sh\n"
            'if [ -d "$PROC_ROOT/12210" ]; then printf "67108865\\n"; fi\n'
        )
        fake_xdotool.chmod(0o700)
        fake_start = root / "start-steam-native.sh"
        fake_start.write_text(
            "#!/bin/sh\n"
            'if [ "$#" -eq 0 ]; then printf "prime\\n" >> "$CAPTURE"; exit 0; fi\n'
            'count=$(cat "$COUNT" 2>/dev/null || printf 0)\n'
            'count=$((count + 1)); printf "%s\\n" "$count" > "$COUNT"\n'
            'printf "attempt=%s\\n" "$count" >> "$CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n'
            'if [ "$count" -eq 1 ]; then\n'
            '  printf "Remove 12210 from running list\\n" >> "$GAME_LOG"\n'
            'else\n'
            '  mkdir -p "$PROC_ROOT/12210"\n'
            '  printf "GTAIV.exe\\n" > "$PROC_ROOT/12210/comm"\n'
            '  printf "STEAM_COMPAT_APP_ID=12210\\0STEAM_COMPAT_DATA_PATH=%s/removable-library-compatdata/12210\\0" "$STEAM_ARM64_BASE" > "$PROC_ROOT/12210/environ"\n'
            '  printf "3:cpuset:/top-app\\n2:cpu:/top-app\\n" > "$PROC_ROOT/12210/cgroup"\n'
            '  (sleep 4; rm -rf "$PROC_ROOT/12210") &\n'
            'fi\n'
        )
        fake_start.chmod(0o700)
        environment = {
            **os.environ,
            "CAPTURE": str(capture),
            "COUNT": str(count_path),
            "GAME_LOG": str(game_log),
            "PROC_ROOT": str(proc_root),
            "STEAM_START_SCRIPT": str(fake_start),
            "STEAM_ARM64_BASE": str(root / "base"),
            "GTAIV_GAMEPROCESS_LOG": str(game_log),
            "GTAIV_PROC_ROOT": str(proc_root),
            "GTAIV_XDOTOOL": str(fake_xdotool),
            "GTAIV_RETRY_WAIT_SECONDS": "4",
            "GTAIV_WINDOW_STABLE_SECONDS": "2",
            "GTAIV_SUPERVISE_POLL_SECONDS": "1",
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), "-foo"],
            env=environment,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        lines = capture.read_text().splitlines()
        assert lines[0] == "prime"
        assert [line for line in lines if line.startswith("attempt=")] == [
            "attempt=1",
            "attempt=2",
        ]
        assert lines.count("arg=--appid") == 2
        assert lines.count("arg=12210") == 2
        assert lines.count("arg=--") == 2
        assert lines.count("arg=-foo") == 2
        assert "pre-game exit detected" in result.stderr
        assert "verified top-app GTAIV.exe" in result.stdout
        assert "foreground supervision complete" in result.stdout

        thin_capture = root / "thin-capture"
        thin_start = root / "thin-start.sh"
        thin_start.write_text(
            "#!/bin/sh\n"
            'printf "arg=%s\\n" "$@" > "$THIN_CAPTURE"\n'
        )
        thin_start.chmod(0o700)
        subprocess.run(
            ["bash", str(SCRIPT), "--proton-log", "-bar"],
            env={
                **os.environ,
                "THIN_CAPTURE": str(thin_capture),
                "STEAM_START_SCRIPT": str(thin_start),
                "GTAIV_LAUNCH_RETRIES": "0",
            },
            check=True,
        )
        assert thin_capture.read_text().splitlines() == [
            "arg=--proton-log",
            "arg=--appid",
            "arg=12210",
            "arg=--",
            "arg=-bar",
        ]

    print("native GTA IV wrapper tests: PASS")


if __name__ == "__main__":
    main()
