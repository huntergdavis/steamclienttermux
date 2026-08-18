#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-direct-benchmark.sh")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-direct-benchmark.") as directory:
        root = Path(directory)
        launcher = root / "launcher"
        capture = root / "capture"
        launcher.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' \"${TOMB_RAIDER_DIRECT_MODE:-}\" "
            "\"${TOMB_RAIDER_DIRECT_CHILD_PRELOAD:-}\" \"$*\" >\"$CAPTURE\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        environment = {
            **os.environ,
            "TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER": str(launcher),
            "CAPTURE": str(capture),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), "fixture"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert capture.read_text(encoding="utf-8").splitlines() == [
            "tombraider-benchmark",
            "lean",
            "fixture",
        ]

        link = root / "launcher-link"
        link.symlink_to(launcher)
        environment["TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER"] = str(link)
        rejected = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 1
        assert "launcher is unavailable" in rejected.stderr

    print("Tomb Raider direct-benchmark wrapper tests: PASS")


if __name__ == "__main__":
    main()
