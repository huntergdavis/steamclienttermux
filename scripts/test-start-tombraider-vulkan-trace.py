#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-vulkan-trace.sh")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-vulkan-trace.") as directory:
        root = Path(directory)
        result = root / "result"
        launcher = root / "launcher"
        launcher.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' \"${TOMB_RAIDER_DIRECT_CHILD_PRELOAD:-}\" "
            "\"${TOMB_RAIDER_VULKAN_TRACE:-}\" "
            "\"${STEAM_PROCESS_TIMEOUT:-}\" \"${STEAM_WINDOW_TIMEOUT:-}\" "
            "\"${STEAM_APP_TIMEOUT:-}\" \"$*\" >\"$FIXTURE_RESULT\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        environment = {
            **os.environ,
            "TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER": str(launcher),
            "FIXTURE_RESULT": str(result),
        }
        completed = subprocess.run(
            ["bash", str(SCRIPT), "test-argument"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert result.read_text(encoding="utf-8").splitlines() == [
            "lean",
            "1",
            "60",
            "60",
            "300",
            "test-argument",
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

    print("Tomb Raider Vulkan-trace wrapper tests: PASS")


if __name__ == "__main__":
    main()
