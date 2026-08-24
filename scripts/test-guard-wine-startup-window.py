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
        xdotool = root / "xdotool"
        xdotool.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "printf '%s\\n' \"$*\" >>\"$FIXTURE_CALLS\"\n"
            "case \"$1\" in\n"
            "  search)\n"
            "    if [[ $* == *--sync* ]]; then printf '65011713\\n'; exit 0; fi\n"
            "    exit 1;;\n"
            "  getwindowclassname) printf 'steam_app_203160\\n';;\n"
            "  windowunmap) printf 'hidden\\n' >>\"$FIXTURE_STATE\";;\n"
            "  windowmap) printf 'revealed\\n' >>\"$FIXTURE_STATE\";;\n"
            "esac\n",
            encoding="utf-8",
        )
        xdotool.chmod(0o700)
        environment = {
            **os.environ,
            "WINE_STARTUP_GUARD_XDOTOOL": str(xdotool),
            "FIXTURE_CALLS": str(calls),
            "FIXTURE_STATE": str(state),
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
        assert state.read_text(encoding="utf-8").splitlines() == [
            "hidden",
            "revealed",
        ]
        call_lines = calls.read_text(encoding="utf-8").splitlines()
        assert call_lines == [
            "search --onlyvisible --class ^steam_app_203160$",
            "search --sync --onlyvisible --class ^steam_app_203160$",
            "getwindowclassname 65011713",
            "windowunmap 65011713",
            "windowmap 65011713 windowraise 65011713 windowfocus 65011713",
        ]
        assert "event=hidden" in result.stdout
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
