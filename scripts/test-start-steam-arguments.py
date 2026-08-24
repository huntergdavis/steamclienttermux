#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).with_name("start-steam.sh")


def parse(*arguments, background=None):
    environment = os.environ.copy()
    environment["START_STEAM_PARSE_ONLY"] = "1"
    if background is not None:
        environment["STEAM_BACKGROUND"] = str(background)
    else:
        environment.pop("STEAM_BACKGROUND", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
    lines = result.stdout.splitlines()
    values = dict(line.split("=", 1) for line in lines[:3])
    values["args"] = [line.removeprefix("arg=") for line in lines[3:]]
    return values


def main():
    source = SCRIPT.read_text()
    assert 'duplicate_process_timeout="${STEAM_DUPLICATE_PROCESS_TIMEOUT:-10}"' in source
    assert source.count("settle_steam_processes") == 3
    assert source.count("--wait-for-cpu-log") == 1
    assert "multiple Steam main processes remained" in source
    assert "wait_for_top_app()" in source
    assert 'forward_bootstrap=${STEAM_ARM64_FORWARD_BOOTSTRAP:-strict}' in source
    assert '"$forward_dispatcher"' in source
    assert 'if [[ $forward_bootstrap == fast ]]' in source
    assert 'fast_forward_authenticated=1' in source
    assert '[[ $fast_forward_authenticated == 0 ]]' in source
    assert 'event=session_valid' in source
    assert 'event=fast_fallback' in source
    assert 'if thread_masks_are "$pid" "$mask"' in source
    assert 'x11_cold_start=0' in source
    assert 'if [[ $x11_cold_start == 1 ]]' in source
    assert 'steam_affinity_stamp="$base/runtime/steam-session-affinity-v1"' in source
    assert 'signature="version=1 x11=$x11_pid:$start_ticks:0-3"' in source
    assert '$(<"$steam_affinity_stamp") == "$signature"' in source
    assert 'cef_affinity=${STEAM_ARM64_CEF_AFFINITY:-auto}' in source
    assert 'cef_cpu_mask=0-3' in source
    assert 'process_mask_is "$helper_pid" "$cef_cpu_mask"' in source
    assert 'apply_uniform_affinity Steam-helper "$helper_pid" "$cef_cpu_mask"' in source
    assert 'pgrep -f -u "$(id -u)" -- "com.termux.x11 ${display}"' in source
    assert "'steamrtarm64/steam($| )'" in source
    assert "'steamrtarm64/steamwebhelper($| )'" in source
    assert '"termux-x11 com.termux.x11 ${display} "*' in source
    assert "${arguments[0]:-} == termux-x11" in source
    assert 'required_stable_count="${2:-$window_stable_seconds}"' in source
    assert '[[ -z "$window" && "$background_mode" == 0 ]]' in source
    assert 'wait_for_steam_window "${steam_pids[0]}" 1' in source
    assert "process_is_top_app()" in source
    assert 'if ! process_is_top_app "${x11_pids[0]}"; then' in source
    assert 'if [[ $x11_foreground_handoff == 1 ]]; then' in source
    assert '--steam-start-ticks "$steam_start_ticks"' in source
    reused_x11 = source.index('    1)\n        # A prior native Activity')
    foreground = source.index("        foreground_x11", reused_x11)
    wait_top = source.index('        wait_for_top_app "${x11_pids[0]}"', foreground)
    require_top = source.index('        require_top_app X11 "${x11_pids[0]}"', wait_top)
    wait_x11 = source.index('        wait_for_x11 || fail "existing X server', require_top)
    assert reused_x11 < foreground < wait_top < require_top < wait_x11
    assert parse() == {"appid": "", "background": "0", "argc": "0", "args": []}
    assert parse("203160", "-nolauncher", "-benchmark") == {
        "appid": "203160",
        "background": "1",
        "argc": "5",
        "args": ["-silent", "-applaunch", "203160", "-nolauncher", "-benchmark"],
    }
    assert parse("--appid", "203160", "--", "-nolauncher") == {
        "appid": "203160",
        "background": "1",
        "argc": "4",
        "args": ["-silent", "-applaunch", "203160", "-nolauncher"],
    }
    assert parse("-console", "-applaunch", "12210", "-foo") == {
        "appid": "12210",
        "background": "0",
        "argc": "4",
        "args": ["-console", "-applaunch", "12210", "-foo"],
    }
    assert parse("-console", "-applaunch", "12210", background=1)["args"] == [
        "-silent",
        "-console",
        "-applaunch",
        "12210",
    ]
    assert parse("203160", "-silent")["args"] == [
        "-applaunch",
        "203160",
        "-silent",
    ]

    invalid = subprocess.run(
        ["bash", str(SCRIPT), "--appid", "bad"],
        env={**os.environ, "START_STEAM_PARSE_ONLY": "1"},
        text=True,
        capture_output=True,
    )
    assert invalid.returncode != 0
    assert "positive numeric Steam AppID" in invalid.stderr
    invalid_suppression = subprocess.run(
        ["bash", str(SCRIPT), "--appid", "203160"],
        env={
            **os.environ,
            "START_STEAM_PARSE_ONLY": "1",
            "STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD": "invalid",
        },
        text=True,
        capture_output=True,
    )
    assert invalid_suppression.returncode != 0
    assert "STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD must be 0 or 1" in invalid_suppression.stderr
    wrong_app_suppression = subprocess.run(
        ["bash", str(SCRIPT), "--appid", "12210"],
        env={
            **os.environ,
            "START_STEAM_PARSE_ONLY": "1",
            "STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD": "1",
        },
        text=True,
        capture_output=True,
    )
    assert wrong_app_suppression.returncode != 0
    assert "valid only for AppID 203160" in wrong_app_suppression.stderr
    invalid_forward = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "START_STEAM_PARSE_ONLY": "1",
            "STEAM_ARM64_FORWARD_BOOTSTRAP": "invalid",
        },
        text=True,
        capture_output=True,
    )
    assert invalid_forward.returncode != 0
    assert "STEAM_ARM64_FORWARD_BOOTSTRAP must be strict or fast" in invalid_forward.stderr
    invalid_cef_affinity = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "START_STEAM_PARSE_ONLY": "1",
            "STEAM_ARM64_CEF_AFFINITY": "invalid",
        },
        text=True,
        capture_output=True,
    )
    assert invalid_cef_affinity.returncode != 0
    assert (
        "STEAM_ARM64_CEF_AFFINITY must be auto, compact, or responsive"
        in invalid_cef_affinity.stderr
    )
    print("start-steam argument tests: ok")


if __name__ == "__main__":
    main()
