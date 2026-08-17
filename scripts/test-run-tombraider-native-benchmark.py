#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "run-tombraider-native-benchmark.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("run_tombraider_benchmark", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_tool()
    assert module.parse_benchmark_result(
        b"MinFPS: 15.8\r\nMaxFPS: 29.8\r\nAverage FPS: 23.2\r\n"
    ) == {"minimum_fps": 15.8, "maximum_fps": 29.8, "average_fps": 23.2}
    assert module.parse_benchmark_result(
        "Minimum FPS = 19.0\nMaximum FPS = 36.0\nAvgFPS = 25.7\n".encode("utf-16")
    ) == {"minimum_fps": 19.0, "maximum_fps": 36.0, "average_fps": 25.7}
    try:
        module.parse_benchmark_result(b"MinFPS: 1\nMaxFPS: 2\n")
    except RuntimeError as error:
        assert "average_fps" in str(error)
    else:
        raise AssertionError("incomplete benchmark result was accepted")

    xrandr = (
        "Screen 0: minimum 320 x 200, current 2800 x 1752, maximum 8192 x 8192\n"
        "   2800x1752     119.92*  60.00\n"
    )
    assert module.parse_xrandr_geometry(xrandr) == "2800x1752"
    assert module.parse_xrandr_refresh(xrandr) == [119.92]
    checker = Path("/base/compat-bin/configure-tombraider-performance.py")
    assert module.python_tool_command(checker, "--check") == [
        Path(module.sys.executable),
        checker,
        "--check",
    ]

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cgroup = root / "cgroup"
        cgroup.write_text("3:cpuset:/top-app\n2:cpu:/top-app\n")
        module.require_top_app(cgroup)
        cgroup.write_text("3:cpuset:/moderate\n2:cpu:/background\n")
        try:
            module.require_top_app(cgroup)
        except RuntimeError as error:
            assert "not in Android top-app" in str(error)
        else:
            raise AssertionError("background benchmark runner was accepted")

        proc = root / "proc"
        (proc / "10").mkdir(parents=True)
        (proc / "11").mkdir()
        executable = Path("/base/client/steamrtarm64/steam")
        (proc / "10/cmdline").write_bytes(
            b"/glibc/ld-linux-aarch64.so.1\0--argv0\0"
            + str(executable).encode()
            + b"\0"
            + str(executable).encode()
            + b"\0"
        )
        (proc / "11/cmdline").write_bytes(
            b"/base/client/steamrtarm64/steamwebhelper\0"
        )
        assert module.find_exact_processes(proc, executable) == [10]

        results = root / "results"
        results.mkdir()
        old = results / "benchmarkresults-old.txt"
        old.write_text("old")
        before = module.file_state(results.glob(module.RESULT_GLOB))
        new = results / "benchmarkresults-new.txt"
        new.write_text("new")
        assert module.changed_regular_files(results, module.RESULT_GLOB, before) == [new]

    runs = [
        {
            "kind": "warmup",
            "metrics": {"minimum_fps": 1.0, "maximum_fps": 2.0, "average_fps": 1.5},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 10.0, "maximum_fps": 30.0, "average_fps": 20.0},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 12.0, "maximum_fps": 32.0, "average_fps": 22.0},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 14.0, "maximum_fps": 34.0, "average_fps": 24.0},
        },
    ]
    aggregate = module.aggregate_results(runs)
    assert aggregate["average_fps"] == {
        "mean": 22.0,
        "median": 22.0,
        "values": [20.0, 22.0, 24.0],
    }
    print("native Tomb Raider benchmark runner tests: PASS")


if __name__ == "__main__":
    main()
