#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("run-tombraider-native-benchmark.sh")
PROTON_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-proton-40c-ceiling.sh"
)


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

        benchmark_capture = root / "benchmark-capture"
        benchmark = root / "run-tombraider-native-benchmark"
        benchmark.write_text(
            "#!/bin/sh\n"
            'printf "arg=%s\\n" "$@" > "$BENCHMARK_CAPTURE"\n'
        )
        benchmark.chmod(0o700)
        wrapper_environment = {
            **os.environ,
            "BENCHMARK_CAPTURE": str(benchmark_capture),
            "TOMB_RAIDER_BENCHMARK_COMMAND": str(benchmark),
        }
        subprocess.run(
            ["bash", str(PROTON_WRAPPER), "--runs", "1"],
            env=wrapper_environment,
            check=True,
        )
        assert benchmark_capture.read_text().splitlines() == [
            "arg=--profile",
            "arg=proton",
            "arg=--start-temperature-ceiling-c",
            "arg=40",
            "arg=--runs",
            "arg=1",
        ]

    print("native Tomb Raider benchmark broker and profile wrapper tests: PASS")


if __name__ == "__main__":
    main()
