#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("run-tombraider-native-benchmark.sh")
PROTON_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-proton-40c-ceiling.sh"
)
FAST_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-fast-40c-ceiling.sh"
)
DIRECT_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-direct-safe-40c-ceiling.sh"
)
DIRECT_FAST_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-direct-fast-40c-ceiling.sh"
)
DIRECT_SAFE_FULL_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-direct-safe-full-topology-40c-ceiling.sh"
)
DIRECT_FAST_FULL_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-direct-fast-full-topology-40c-ceiling.sh"
)
DIRECT_SAFE_FULL_RAKNET_NICE19_WRAPPER = Path(__file__).with_name(
    "test-tomb-raider-direct-safe-full-topology-raknet-nice19-40c-ceiling.sh"
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

        fast_capture = root / "fast-capture"
        wrapper_environment["BENCHMARK_CAPTURE"] = str(fast_capture)
        subprocess.run(
            ["bash", str(FAST_WRAPPER), "--runs", "2"],
            env=wrapper_environment,
            check=True,
        )
        assert fast_capture.read_text().splitlines() == [
            "arg=--profile",
            "arg=fast",
            "arg=--start-temperature-ceiling-c",
            "arg=40",
            "arg=--runs",
            "arg=2",
        ]

        direct_capture = root / "direct-capture"
        wrapper_environment["BENCHMARK_CAPTURE"] = str(direct_capture)
        subprocess.run(
            ["bash", str(DIRECT_WRAPPER), "--warmups", "0"],
            env=wrapper_environment,
            check=True,
        )
        assert direct_capture.read_text().splitlines() == [
            "arg=--backend",
            "arg=direct",
            "arg=--profile",
            "arg=safe",
            "arg=--start-temperature-ceiling-c",
            "arg=40",
            "arg=--warmups",
            "arg=0",
        ]

        direct_fast_capture = root / "direct-fast-capture"
        wrapper_environment["BENCHMARK_CAPTURE"] = str(direct_fast_capture)
        subprocess.run(
            ["bash", str(DIRECT_FAST_WRAPPER), "--runs", "1"],
            env=wrapper_environment,
            check=True,
        )
        assert direct_fast_capture.read_text().splitlines() == [
            "arg=--backend",
            "arg=direct",
            "arg=--profile",
            "arg=fast",
            "arg=--start-temperature-ceiling-c",
            "arg=40",
            "arg=--runs",
            "arg=1",
        ]

        for profile, wrapper in (
            ("safe", DIRECT_SAFE_FULL_WRAPPER),
            ("fast", DIRECT_FAST_FULL_WRAPPER),
        ):
            full_capture = root / f"direct-{profile}-full-capture"
            wrapper_environment["BENCHMARK_CAPTURE"] = str(full_capture)
            subprocess.run(
                ["bash", str(wrapper), "--runs", "1"],
                env=wrapper_environment,
                check=True,
            )
            assert full_capture.read_text().splitlines() == [
                "arg=--backend",
                "arg=direct",
                "arg=--profile",
                f"arg={profile}",
                "arg=--startup-topology",
                "arg=full",
                "arg=--start-temperature-ceiling-c",
                "arg=40",
                "arg=--runs",
                "arg=1",
            ]

        priority_capture = root / "direct-safe-full-raknet-nice19-capture"
        wrapper_environment["BENCHMARK_CAPTURE"] = str(priority_capture)
        subprocess.run(
            ["bash", str(DIRECT_SAFE_FULL_RAKNET_NICE19_WRAPPER), "--runs", "1"],
            env=wrapper_environment,
            check=True,
        )
        assert priority_capture.read_text().splitlines() == [
            "arg=--backend",
            "arg=direct",
            "arg=--profile",
            "arg=safe",
            "arg=--startup-topology",
            "arg=full",
            "arg=--raknet-nice",
            "arg=19",
            "arg=--start-temperature-ceiling-c",
            "arg=40",
            "arg=--runs",
            "arg=1",
        ]

    print("native Tomb Raider benchmark broker and profile wrapper tests: PASS")


if __name__ == "__main__":
    main()
