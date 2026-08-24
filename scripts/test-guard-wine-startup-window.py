#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("guard-wine-startup-window.sh")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wine-startup-guard.") as directory:
        root = Path(directory)
        state = root / "state"
        calls = root / "calls"
        search_count = root / "search-count"
        class_count = root / "class-count"
        xdotool = root / "xdotool"
        xdotool.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >>\"$FIXTURE_CALLS\"\n"
            "case \"$1\" in\n"
            "  search)\n"
            "    if [[ $* == *--class* ]]; then exit 1; fi\n"
            "    count=0; [[ -f $FIXTURE_SEARCH_COUNT ]] && count=$(cat \"$FIXTURE_SEARCH_COUNT\"); count=$((count+1)); printf '%s\\n' \"$count\" >\"$FIXTURE_SEARCH_COUNT\"\n"
            "    if (( count == 1 )); then printf '1297\\n'; else printf '1297\\n65011713\\n'; fi;;\n"
            "  getwindowclassname)\n"
            "    count=0; [[ -f $FIXTURE_CLASS_COUNT ]] && count=$(cat \"$FIXTURE_CLASS_COUNT\"); count=$((count+1)); printf '%s\\n' \"$count\" >\"$FIXTURE_CLASS_COUNT\"\n"
            "    (( count > 1 )) && printf 'steam_app_203160\\n';;\n"
            "  getwindowgeometry) printf 'WINDOW=65011713\\nX=0\\nY=0\\nWIDTH=1280\\nHEIGHT=720\\nSCREEN=0\\n';;\n"
            "  getdisplaygeometry) printf '2800 1752\\n';;\n"
            "  windowmove) if [[ $3 == 2864 ]]; then printf 'concealed\\n' >>\"$FIXTURE_STATE\"; else printf 'revealed\\n' >>\"$FIXTURE_STATE\"; fi;;\n"
            "esac\n",
            encoding="utf-8",
        )
        xdotool.chmod(0o700)
        environment = {
            **os.environ,
            "WINE_STARTUP_GUARD_XDOTOOL": str(xdotool),
            "FIXTURE_CALLS": str(calls),
            "FIXTURE_STATE": str(state),
            "FIXTURE_SEARCH_COUNT": str(search_count),
            "FIXTURE_CLASS_COUNT": str(class_count),
        }
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--display",
                ":0",
                "--class",
                "steam_app_203160",
                "--hold-seconds",
                "0.01",
                "--timeout",
                "2",
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        states = state.read_text(encoding="utf-8").splitlines()
        assert states[0] == "concealed"
        assert states[-1] == "revealed"
        call_lines = calls.read_text(encoding="utf-8").splitlines()
        assert call_lines[:3] == [
            "search --onlyvisible --class ^steam_app_203160$",
            "getdisplaygeometry",
            "search --onlyvisible --name .*",
        ]
        assert "getwindowgeometry --shell 65011713" in call_lines
        assert "windowmove 65011713 2864 0" in call_lines
        assert call_lines[-1] == (
            "windowmove 65011713 0 0 windowraise 65011713 windowfocus 65011713"
        )
        assert "version=3 event=candidate_concealed" in result.stdout
        assert "event=class_confirmed" in result.stdout
        assert "event=revealed" in result.stdout

        invalid = subprocess.run(
            ["bash", str(SCRIPT), "--class", "bad class"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid.returncode != 0
        assert "invalid window class" in invalid.stderr

    print("Wine startup window guard tests: PASS")


if __name__ == "__main__":
    main()
