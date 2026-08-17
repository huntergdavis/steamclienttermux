#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("run-tombraider-native-benchmark.sh")


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        capture = root / "capture"
        runner = root / "runner.py"
        runner.write_text("# benchmark runner\n")
        python = root / "python3"
        python.write_text(
            "#!/bin/sh\n"
            'printf "runner=%s\\n" "$1" > "$CAPTURE"\n'
            "shift\n"
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n'
        )
        python.chmod(0o700)
        environment = {
            **os.environ,
            "CAPTURE": str(capture),
            "TOMB_RAIDER_BENCHMARK_PYTHON": str(python),
            "TOMB_RAIDER_BENCHMARK_RUNNER": str(runner),
        }
        subprocess.run(
            ["bash", str(SCRIPT), "--profile", "safe", "--runs", "3"],
            env=environment,
            check=True,
        )
        assert capture.read_text().splitlines() == [
            f"runner={runner}",
            "arg=--profile",
            "arg=safe",
            "arg=--runs",
            "arg=3",
        ]

        runner.unlink()
        failed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
        )
        assert failed.returncode != 0
        assert "runner is unavailable or unsafe" in failed.stderr

    print("native Tomb Raider benchmark broker tests: PASS")


if __name__ == "__main__":
    main()
