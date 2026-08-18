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
    fixed = module.build_parser().parse_args(
        ["--profile", "proton", "--start-temperature-ceiling-c", "40"]
    )
    assert fixed.profile == "proton"
    assert fixed.start_temperature_ceiling_c == 40.0
    direct = module.build_parser().parse_args(["--backend", "direct"])
    assert direct.backend == "direct"
    assert direct.launcher is None
    assert direct.raknet_nice is None
    direct_priority = module.build_parser().parse_args(
        ["--backend", "direct", "--raknet-nice", "19"]
    )
    assert direct_priority.raknet_nice == 19
    assert module.affinity_log_is_ready(
        "Tomb Raider PID 1: observing inherited startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1\n",
        "direct",
    )
    assert module.affinity_log_is_ready(
        "Tomb Raider PID 1: holding startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1\n",
        "direct",
    )
    assert not module.affinity_log_is_ready(
        "Tomb Raider performance state: ready; PID 1\n", "direct"
    )
    assert module.affinity_log_is_ready(
        "Tomb Raider performance state: ready; PID 1\n", "proot"
    )

    def snapshot(cpu_policy, gpu_policy, gpu_level, temperature):
        return {
            "cpu": [
                {
                    "cpu": 7,
                    "policy_max_khz": cpu_policy,
                    "hardware_max_khz": 2_995_200,
                }
            ],
            "gpu": {
                "policy_max_hz": gpu_policy,
                "hardware_max_hz": 818_000_000,
                "thermal_pwrlevel": gpu_level,
            },
            "thermal": [
                {"zone": "cpu-1-7", "millidegrees_c": temperature}
            ],
        }

    hot = snapshot(1_843_200, 492_000_000, 6, 73_900)
    ready = snapshot(2_995_200, 818_000_000, 0, 51_000)
    issues = module.benchmark_readiness_issues(hot, 52_300)
    assert any("CPU policy is throttled" in issue for issue in issues)
    assert any("GPU policy is throttled" in issue for issue in issues)
    assert any("maximum temperature" in issue for issue in issues)
    assert module.benchmark_readiness_issues(ready, 52_300) == []
    samples = iter((hot, ready, ready))
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    settled, elapsed = module.wait_for_benchmark_ready(
        lambda: next(samples),
        52_300,
        60,
        10,
        2,
        monotonic=lambda: clock[0],
        sleeper=sleep,
    )
    assert settled is ready
    assert elapsed == 20.0

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
        # Removable-storage metadata for an existing name can change between
        # scans. Only a previously absent timestamped result is a new pass.
        old.write_text("old rewritten")
        assert module.new_regular_files(results, module.RESULT_GLOB, before) == [new]

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
    failed = {"status": "initializing", "runs": []}
    module.mark_series_failed(failed, RuntimeError("controlled failure"))
    assert failed["status"] == "failed"
    assert failed["failure"] == {
        "type": "RuntimeError",
        "message": "controlled failure",
    }
    assert failed["finished_at"].endswith("+00:00")
    print("native Tomb Raider benchmark runner tests: PASS")


if __name__ == "__main__":
    main()
