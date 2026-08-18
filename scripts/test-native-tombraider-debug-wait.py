#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "diagnostics/native-tombraider-debug-wait.c"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-debug-wait.") as directory:
        root = Path(directory)
        shim = root / "debug-wait.so"
        driver_source = root / "driver.c"
        driver = root / "driver"
        driver_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        warnings = [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wpedantic",
            "-Wformat=2",
            "-Wshadow",
        ]
        subprocess.run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                "-fPIC",
                "-shared",
                "-DSTEAM_ARM64_DEBUG_WAIT_SECONDS=1",
                *warnings,
                str(SOURCE),
                "-o",
                str(shim),
            ],
            check=True,
        )
        subprocess.run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                *warnings,
                str(driver_source),
                "-o",
                str(driver),
            ],
            check=True,
        )
        environment = {**os.environ, "LD_PRELOAD": str(shim)}

        start = time.monotonic()
        matched = subprocess.run(
            [str(driver), "wine", r"Z:\games\Tomb Raider\TombRaider.exe"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        elapsed = time.monotonic() - start
        assert matched.returncode == 0, matched.stderr
        assert "TOMB_RAIDER_DEBUG_WAIT_PID=" in matched.stderr
        assert "SECONDS=1" in matched.stderr
        assert 0.8 <= elapsed < 5.0, elapsed

        start = time.monotonic()
        control = subprocess.run(
            [str(driver), "wine", r"c:\windows\system32\steam.exe"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        elapsed = time.monotonic() - start
        assert control.returncode == 0, control.stderr
        assert "TOMB_RAIDER_DEBUG_WAIT_PID=" not in control.stderr
        assert elapsed < 0.8, elapsed

    print("native Tomb Raider debug-wait shim tests: PASS")


if __name__ == "__main__":
    main()
