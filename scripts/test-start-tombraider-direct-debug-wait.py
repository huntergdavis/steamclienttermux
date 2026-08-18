#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-direct-debug-wait.sh")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-direct-debug-wait.") as directory:
        root = Path(directory)
        result = root / "result"
        launcher = root / "launcher"
        launcher.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' \"${STEAM_ARM64_DIRECT_FEX_STARTUP_SLEEP:-}\" "
            "\"$*\" >\"$FIXTURE_RESULT\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        environment = {
            **os.environ,
            "TOMB_RAIDER_DIRECT_DEBUG_LAUNCHER": str(launcher),
            "FIXTURE_RESULT": str(result),
        }
        environment.pop("STEAM_ARM64_DIRECT_FEX_STARTUP_SLEEP", None)
        completed = subprocess.run(
            ["bash", str(SCRIPT), "test-argument"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert result.read_text(encoding="utf-8").splitlines() == [
            "10",
            "test-argument",
        ]

        link = root / "launcher-link"
        link.symlink_to(launcher)
        environment["TOMB_RAIDER_DIRECT_DEBUG_LAUNCHER"] = str(link)
        rejected = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 1
        assert "launcher is unavailable" in rejected.stderr

    print("Tomb Raider direct debug-wait wrapper tests: PASS")


if __name__ == "__main__":
    main()
