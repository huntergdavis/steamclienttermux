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

        missing = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**os.environ, "STEAM_START_SCRIPT": str(root / "missing")},
            text=True,
            capture_output=True,
        )
        assert missing.returncode != 0
        assert "native Steam launcher is unavailable" in missing.stderr

    print("native Tomb Raider wrapper tests: PASS")


if __name__ == "__main__":
    main()
