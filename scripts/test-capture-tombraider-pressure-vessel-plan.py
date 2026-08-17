#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("capture-tombraider-pressure-vessel-plan.sh")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-plan-capture.") as directory:
        root = Path(directory)
        base = root / "base"
        for path in (base / "logs/runtime-plans", base / "run"):
            path.mkdir(parents=True, mode=0o700)
        launcher = root / "launcher"
        launcher.write_text(
            "#!/bin/bash\n"
            "set -e\n"
            "printf '%s\\n' \"$*\" >\"$FIXTURE_ARGS\"\n"
            "printf '%s\\n' \"${STEAM_ARM64_BWRAP_CAPTURE_PLAN:-}\" >\"$FIXTURE_CAPTURE\"\n"
            "printf '{\\\"fixture\\\":true}\\n' >\"$STEAM_ARM64_BWRAP_CAPTURE_PLAN\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        arguments = root / "arguments"
        capture_value = root / "capture-value"
        environment = {
            **os.environ,
            "STEAM_ARM64_BASE": str(base),
            "TOMB_RAIDER_CAPTURE_LAUNCHER": str(launcher),
            "TOMB_RAIDER_CAPTURE_WAIT_SECONDS": "2",
            "FIXTURE_ARGS": str(arguments),
            "FIXTURE_CAPTURE": str(capture_value),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert arguments.read_text().strip() == "--appid 203160 -- -nolauncher"
        capture = Path(capture_value.read_text().strip())
        assert capture.parent == base / "logs/runtime-plans"
        assert capture.read_text() == '{"fixture":true}\n'
        state = (base / "run/tombraider-plan-capture.state").read_text()
        assert "status=captured" in state
        assert f"capture={capture}" in state
        assert "without executing the game" in result.stdout

    print("Tomb Raider Pressure Vessel plan capture tests: PASS")


if __name__ == "__main__":
    main()
