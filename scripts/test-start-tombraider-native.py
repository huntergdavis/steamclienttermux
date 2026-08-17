#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-native.sh")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        capture = root / "capture"
        fake_start = root / "start-steam-native.sh"
        fake_start.write_text(
            "#!/bin/sh\n"
            'printf "background=%s\\n" "$STEAM_BACKGROUND" > "$CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n'
        )
        fake_start.chmod(0o700)

        environment = {
            **os.environ,
            "CAPTURE": str(capture),
            "STEAM_START_SCRIPT": str(fake_start),
            "TOMB_RAIDER_LAUNCH_RETRIES": "0",
        }
        subprocess.run(
            ["bash", str(SCRIPT), "-benchmark", "-foo"],
            env=environment,
            check=True,
        )
        assert capture.read_text().splitlines() == [
            "background=1",
            "arg=--appid",
            "arg=203160",
            "arg=--",
            "arg=-nolauncher",
            "arg=-benchmark",
            "arg=-foo",
        ]

        subprocess.run(
            ["bash", str(SCRIPT), "--proton-log", "-benchmark"],
            env=environment,
            check=True,
        )
        assert capture.read_text().splitlines() == [
            "background=1",
            "arg=--proton-log",
            "arg=--appid",
            "arg=203160",
            "arg=--",
            "arg=-nolauncher",
            "arg=-benchmark",
        ]

        missing = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**os.environ, "STEAM_START_SCRIPT": str(root / "missing")},
            text=True,
            capture_output=True,
        )
        assert missing.returncode != 0
        assert "native Steam launcher is unavailable" in missing.stderr

        retry_capture = root / "retry-capture"
        retry_count = root / "retry-count"
        retry_log = root / "gameprocess_log.txt"
        proc_root = root / "proc"
        proc_root.mkdir()
        fake_xdotool = root / "xdotool"
        fake_xdotool.write_text(
            "#!/bin/sh\n"
            '# The failed container creates an exact-looking process, but no window.\n'
            'if [ -d "$PROC_ROOT/27038" ]; then printf "65011713\\n"; fi\n'
        )
        fake_xdotool.chmod(0o700)
        retry_start = root / "retry-start-steam-native.sh"
        retry_start.write_text(
            "#!/bin/sh\n"
            'count=$(cat "$COUNT" 2>/dev/null || printf 0)\n'
            'count=$((count + 1))\n'
            'printf "%s\\n" "$count" > "$COUNT"\n'
            'printf "attempt=%s\\n" "$count" >> "$CAPTURE"\n'
            'if [ "$count" -eq 1 ]; then\n'
            '  mkdir -p "$PROC_ROOT/10"\n'
            '  printf "TombRaider.exe\\n" > "$PROC_ROOT/10/comm"\n'
            '  printf "STEAM_COMPAT_APP_ID=203160\\0STEAM_COMPAT_DATA_PATH=%s/removable-library-compatdata/203160\\0" "$STEAM_ARM64_BASE" > "$PROC_ROOT/10/environ"\n'
            '  printf "3:cpuset:/top-app\\n2:cpu:/top-app\\n" > "$PROC_ROOT/10/cgroup"\n'
            '  printf "AppID 203160 adding PID 10\\nRemove 203160 from running list\\n" >> "$GAME_LOG"\n'
            "else\n"
            '  rm -rf "$PROC_ROOT/10"\n'
            '  mkdir -p "$PROC_ROOT/27038"\n'
            '  printf "TombRaider.exe\\n" > "$PROC_ROOT/27038/comm"\n'
            '  printf "STEAM_COMPAT_APP_ID=203160\\0STEAM_COMPAT_DATA_PATH=%s/removable-library-compatdata/203160\\0" "$STEAM_ARM64_BASE" > "$PROC_ROOT/27038/environ"\n'
            '  printf "3:cpuset:/top-app\\n2:cpu:/top-app\\n" > "$PROC_ROOT/27038/cgroup"\n'
            "fi\n"
        )
        retry_start.chmod(0o700)
        retry_environment = {
            **os.environ,
            "CAPTURE": str(retry_capture),
            "COUNT": str(retry_count),
            "GAME_LOG": str(retry_log),
            "PROC_ROOT": str(proc_root),
            "STEAM_ARM64_BASE": str(root / "base"),
            "STEAM_START_SCRIPT": str(retry_start),
            "TOMB_RAIDER_GAMEPROCESS_LOG": str(retry_log),
            "TOMB_RAIDER_PROC_ROOT": str(proc_root),
            "TOMB_RAIDER_XDOTOOL": str(fake_xdotool),
            "TOMB_RAIDER_LAUNCH_RETRIES": "1",
            "TOMB_RAIDER_RETRY_WAIT_SECONDS": "4",
            "TOMB_RAIDER_WINDOW_STABLE_SECONDS": "2",
        }
        retry = subprocess.run(
            ["bash", str(SCRIPT)],
            env=retry_environment,
            text=True,
            capture_output=True,
        )
        assert retry.returncode == 0, retry.stderr
        assert retry_count.read_text().strip() == "2"
        assert retry_capture.read_text().splitlines() == [
            "attempt=1",
            "attempt=2",
        ]
        assert "fast pre-game exit detected" in retry.stderr
        assert "verified top-app TombRaider.exe and visible game window for 2s on attempt 2" in retry.stdout

    print("native Tomb Raider wrapper tests: PASS")


if __name__ == "__main__":
    main()
