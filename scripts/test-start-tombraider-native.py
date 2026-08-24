#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-native.sh")
PROCESS_MATCHER = SCRIPT.parent.parent / "bin" / "steam-arm64-process-match.sh"


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        capture = root / "capture"
        fake_start = root / "start-steam-native.sh"
        fake_start.write_text(
            "#!/bin/sh\n"
            'printf "background=%s\\n" "$STEAM_BACKGROUND" > "$CAPTURE"\n'
            'printf "bwrap_direct=%s\\n" "$STEAM_ARM64_BWRAP_DIRECT" >> "$CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n'
        )
        fake_start.chmod(0o700)

        environment = {
            **os.environ,
            "CAPTURE": str(capture),
            "STEAM_START_SCRIPT": str(fake_start),
            "STEAM_ARM64_BWRAP_DIRECT": "1",
            "TOMB_RAIDER_LAUNCH_RETRIES": "0",
        }
        subprocess.run(
            ["bash", str(SCRIPT), "-benchmark", "-foo"],
            env=environment,
            check=True,
        )
        assert capture.read_text().splitlines() == [
            "background=1",
            "bwrap_direct=0",
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
            "bwrap_direct=0",
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
            'if [ "$#" -eq 0 ]; then printf "prime\\n" >> "$CAPTURE"; exit 0; fi\n'
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
            '  (sleep 4; rm -rf "$PROC_ROOT/27038") &\n'
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
            "STEAM_ARM64_PROC_ROOT": str(proc_root),
            "STEAM_ARM64_PROCESS_MATCH_HELPER": str(PROCESS_MATCHER),
            "TOMB_RAIDER_XDOTOOL": str(fake_xdotool),
            "TOMB_RAIDER_LAUNCH_RETRIES": "1",
            "TOMB_RAIDER_RETRY_WAIT_SECONDS": "4",
            "TOMB_RAIDER_WINDOW_STABLE_SECONDS": "2",
            "TOMB_RAIDER_SUPERVISE_POLL_SECONDS": "1",
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
            "prime",
            "attempt=1",
            "attempt=2",
        ]
        assert "fast pre-game exit detected" in retry.stderr
        assert "verified top-app TombRaider.exe and visible game window for 2s on attempt 2" in retry.stdout
        assert "foreground supervision complete" in retry.stdout

        # An exact existing native Steam process skips only the redundant
        # readiness prime. The AppID launch and all supervision remain.
        warm_capture = root / "warm-capture"
        warm_count = root / "warm-count"
        warm_proc = root / "warm-proc"
        warm_proc.mkdir()
        steam_process = warm_proc / "77"
        steam_process.mkdir()
        steam_target = root / "warm-base/client/steamrtarm64/steam"
        steam_process.joinpath("cmdline").write_bytes(
            str(steam_target).encode() + b"\0-silent\0"
        )
        warm_game = warm_proc / "88"
        warm_game.mkdir()
        warm_game.joinpath("comm").write_text("TombRaider.exe\n")
        warm_game.joinpath("environ").write_bytes(
            b"STEAM_COMPAT_APP_ID=203160\0"
            + f"STEAM_COMPAT_DATA_PATH={root}/warm-base/removable-library-compatdata/203160".encode()
            + b"\0"
        )
        warm_game.joinpath("cgroup").write_text(
            "3:cpuset:/top-app\n2:cpu:/top-app\n"
        )
        warm_start = root / "warm-start-steam-native.sh"
        warm_start.write_text(
            "#!/bin/sh\n"
            'count=$(cat "$COUNT" 2>/dev/null || printf 0)\n'
            'printf "%s\\n" "$((count + 1))" > "$COUNT"\n'
            'printf "argc=%s\\n" "$#" >> "$CAPTURE"\n'
            '(sleep 3; rm -rf "$PROC_ROOT/88") &\n'
        )
        warm_start.chmod(0o700)
        warm_xdotool = root / "warm-xdotool"
        warm_xdotool.write_text("#!/bin/sh\nprintf '65011713\\n'\n")
        warm_xdotool.chmod(0o700)
        warm = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **os.environ,
                "CAPTURE": str(warm_capture),
                "COUNT": str(warm_count),
                "PROC_ROOT": str(warm_proc),
                "STEAM_ARM64_BASE": str(root / "warm-base"),
                "STEAM_ARM64_PROC_ROOT": str(warm_proc),
                "STEAM_ARM64_PROCESS_MATCH_HELPER": str(PROCESS_MATCHER),
                "STEAM_START_SCRIPT": str(warm_start),
                "TOMB_RAIDER_GAMEPROCESS_LOG": str(root / "warm-gameprocess.log"),
                "TOMB_RAIDER_PROC_ROOT": str(warm_proc),
                "TOMB_RAIDER_XDOTOOL": str(warm_xdotool),
                "TOMB_RAIDER_LAUNCH_RETRIES": "1",
                "TOMB_RAIDER_RETRY_WAIT_SECONDS": "4",
                "TOMB_RAIDER_WINDOW_STABLE_SECONDS": "1",
                "TOMB_RAIDER_SUPERVISE_POLL_SECONDS": "1",
            },
            text=True,
            capture_output=True,
        )
        assert warm.returncode == 0, warm.stderr
        assert warm_count.read_text().strip() == "1"
        assert warm_capture.read_text().splitlines() == ["argc=4"]
        assert "verified top-app TombRaider.exe" in warm.stdout

    print("native Tomb Raider wrapper tests: PASS")


if __name__ == "__main__":
    main()
