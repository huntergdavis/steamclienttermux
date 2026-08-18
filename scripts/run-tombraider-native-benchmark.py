#!/usr/bin/env python3
"""Run a controlled panel-native Tomb Raider benchmark series."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import statistics
import subprocess
import sys
import time


PANEL_GEOMETRY = "2800x1752"
RESULT_GLOB = "benchmarkresults*.txt"
PROOT_GUARD_GLOB = "tomb-raider-affinity-*.log"
DIRECT_GUARD_GLOB = "tombraider-direct-affinity-*.log"
METRIC_PATTERNS = {
    "minimum_fps": re.compile(
        r"(?im)^\s*(?:min(?:imum)?\s*fps|minfps)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "maximum_fps": re.compile(
        r"(?im)^\s*(?:max(?:imum)?\s*fps|maxfps)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"
    ),
    "average_fps": re.compile(
        r"(?im)^\s*(?:(?:avg|average)\s*fps|avgfps|average)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"
    ),
}
CEF_HOLD_LOG_PATTERN = re.compile(
    r"Steam CEF experimental hold: active; ([1-9][0-9]*(?:,[1-9][0-9]*)*)\n"
    r"Steam CEF experimental hold: game exited\n"
    r"Steam CEF experimental hold: resumed ([1-9][0-9]*(?:,[1-9][0-9]*)*)\n?"
)
X11_ISOLATION_LOG_PATTERN = re.compile(
    r"Termux X11 experimental isolation: active; pid=([1-9][0-9]*); "
    r"cpus=([0-7](?:,[0-7])*); tids=([1-9][0-9]*(?:,[1-9][0-9]*)*)\n"
    r"Termux X11 experimental isolation: game exited\n"
    r"Termux X11 experimental isolation: restored; "
    r"tids=([1-9][0-9]*(?:,[1-9][0-9]*)*)\n?"
)
DIRECT_DISPATCH_COMPLETION_PATTERN = re.compile(
    r"Tomb Raider direct dispatch completed: mode=tombraider-benchmark "
    r"child_preload=lean launcher=0 server=1 server_log=(\S+) launcher_log=(\S+)"
)
PULSE_MAINLOOP_ABORT = (
    "Assertion '!e->dead' failed at ../src/pulse/mainloop.c:207, "
    "function mainloop_io_free(). Aborting."
)
SERIES_PHASES = frozenset(
    {
        "initializing",
        "preflight",
        "cooldown",
        "launching_or_running",
        "validating_result",
        "result_accepted",
        "complete",
        "failed",
    }
)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None


def require_regular(path: Path, label: str, executable: bool = False) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular non-symlink file: {path}")
    if executable and not os.access(path, os.X_OK):
        raise RuntimeError(f"{label} is not executable: {path}")


def cgroup_classes(path: Path = Path("/proc/self/cgroup")) -> dict[str, str]:
    result = {}
    text = read_text(path) or ""
    for line in text.splitlines():
        _index, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, value = remainder.partition(":")
        if not separator:
            continue
        for controller in controllers.split(","):
            if controller:
                result[controller] = value
    return result


def require_top_app(path: Path = Path("/proc/self/cgroup")) -> None:
    classes = cgroup_classes(path)
    if classes.get("cpuset") != "/top-app" or classes.get("cpu") != "/top-app":
        raise RuntimeError(
            "benchmark runner is not in Android top-app cgroups "
            f"(cpuset={classes.get('cpuset', 'unknown')}, "
            f"cpu={classes.get('cpu', 'unknown')}); launch it through the "
            "foreground Termux RunCommandService session"
        )


def process_tokens(path: Path) -> list[bytes]:
    try:
        return [token for token in path.read_bytes().split(b"\0") if token]
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return []


def find_exact_processes(proc_root: Path, executable: Path) -> list[int]:
    target = os.fsencode(str(executable))
    matches = []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        if target in process_tokens(process / "cmdline"):
            matches.append(int(process.name))
    return sorted(matches)


def find_tomb_raider_processes(proc_root: Path) -> list[int]:
    matches = []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        tokens = process_tokens(process / "cmdline")
        if not tokens:
            continue
        executable = tokens[0].replace(b"\\", b"/").lower()
        if executable == b"tombraider.exe" or executable.endswith(
            b"/tombraider.exe"
        ):
            matches.append(int(process.name))
    return sorted(matches)


def environment_for_pid(proc_root: Path, pid: int) -> dict[str, str]:
    data = (proc_root / str(pid) / "environ").read_bytes()
    result = {}
    for entry in data.split(b"\0"):
        key, separator, value = entry.partition(b"=")
        if separator:
            result[os.fsdecode(key)] = os.fsdecode(value)
    return result


def file_state(paths) -> dict[str, tuple[int, int, int]]:
    result = {}
    for path in paths:
        try:
            metadata = path.lstat()
        except (FileNotFoundError, OSError):
            continue
        if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            result[str(path)] = (
                metadata.st_ino,
                metadata.st_mtime_ns,
                metadata.st_size,
            )
    return result


def new_regular_files(directory: Path, pattern: str, before) -> list[Path]:
    current = file_state(directory.glob(pattern))
    return sorted(Path(path) for path in current if path not in before)


def validate_post_result_pulse_abort(
    launch_log: Path,
    return_code: int,
    base: Path,
    proc_root: Path,
) -> dict[str, str | int]:
    if return_code != 1:
        raise RuntimeError(
            f"direct benchmark returned {return_code}, not the exact post-result "
            "PulseAudio abort status 1"
        )
    require_regular(launch_log, "direct benchmark launch log")
    completion_lines = [
        line
        for line in launch_log.read_text().splitlines()
        if line.startswith("Tomb Raider direct dispatch completed:")
    ]
    if len(completion_lines) != 1:
        raise RuntimeError(
            "nonzero direct benchmark has no unique dispatch completion record"
        )
    match = DIRECT_DISPATCH_COMPLETION_PATTERN.fullmatch(completion_lines[0])
    if match is None:
        raise RuntimeError(
            "nonzero direct benchmark does not match the protected Pulse abort route"
        )

    logs = (base / "logs").resolve()
    server_log = Path(match.group(1))
    launcher_log = Path(match.group(2))
    for path, label, name_pattern in (
        (
            server_log,
            "direct dispatcher server log",
            r"tombraider-direct-tombraider-benchmark-lean-\d{8}T\d{6}Z\.log",
        ),
        (
            launcher_log,
            "direct dispatcher launcher log",
            r"tombraider-direct-launcher-tombraider-benchmark-lean-\d{8}T\d{6}Z\.log",
        ),
    ):
        require_regular(path, label)
        if path.parent.resolve() != logs or re.fullmatch(name_pattern, path.name) is None:
            raise RuntimeError(f"{label} is outside the protected log path: {path}")

    server_raw = server_log.read_bytes()
    server_text = server_raw.decode("utf-8", errors="replace")
    if server_text.count(PULSE_MAINLOOP_ABORT) != 1:
        raise RuntimeError(
            "nonzero direct benchmark lacks the exact PulseAudio shutdown assertion"
        )
    dispatch_lines = [
        line for line in server_text.splitlines() if line.startswith("DISPATCH_STATUS=")
    ]
    if dispatch_lines != ["DISPATCH_STATUS=1 TRACER_PID=0"]:
        raise RuntimeError(
            f"nonzero direct benchmark has unexpected dispatch status: {dispatch_lines}"
        )
    live_games = find_tomb_raider_processes(proc_root)
    if live_games:
        raise RuntimeError(
            f"post-result PulseAudio abort left Tomb Raider active: {live_games}"
        )
    return {
        "reason": "post-result-pulseaudio-mainloop-abort",
        "return_code": return_code,
        "server_log": str(server_log),
        "server_log_sha256": hashlib.sha256(server_raw).hexdigest(),
    }


def decode_result(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\0" in data[:128]:
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def parse_benchmark_result(data: bytes) -> dict[str, float]:
    text = decode_result(data)
    result = {}
    for name, pattern in METRIC_PATTERNS.items():
        match = pattern.search(text)
        if match is None:
            raise RuntimeError(f"benchmark result does not contain {name}")
        result[name] = float(match.group(1))
    return result


def parse_topology_fix_status(output: str) -> str:
    match = re.fullmatch(
        r"Tomb Raider CPU topology fix: enabled; SHA-256 ([0-9a-f]{64})\n?",
        output,
    )
    if match is None:
        raise RuntimeError("Tomb Raider CPU-topology fix is not enabled")
    return match.group(1)


def parse_cef_hold_log(output: str) -> list[int]:
    match = CEF_HOLD_LOG_PATTERN.fullmatch(output)
    if match is None:
        raise RuntimeError("Steam CEF hold log is incomplete or contains errors")
    active = [int(value) for value in match.group(1).split(",")]
    resumed = [int(value) for value in match.group(2).split(",")]
    if active != sorted(set(active)):
        raise RuntimeError("Steam CEF hold active PID set is not sorted and unique")
    if resumed != active:
        raise RuntimeError("Steam CEF hold did not resume the exact active PID set")
    return active


def parse_x11_isolation_log(output: str) -> dict[str, int | list[int]]:
    match = X11_ISOLATION_LOG_PATTERN.fullmatch(output)
    if match is None:
        raise RuntimeError("Termux X11 isolation log is incomplete or contains errors")
    pid = int(match.group(1))
    cpus = [int(value) for value in match.group(2).split(",")]
    active = [int(value) for value in match.group(3).split(",")]
    restored = [int(value) for value in match.group(4).split(",")]
    if cpus != sorted(set(cpus)):
        raise RuntimeError("Termux X11 isolation CPU set is not sorted and unique")
    if active != sorted(set(active)) or restored != sorted(set(restored)):
        raise RuntimeError("Termux X11 isolation TID sets are not sorted and unique")
    if not set(active).issubset(restored):
        raise RuntimeError("Termux X11 isolation did not restore every active TID")
    return {"pid": pid, "cpus": cpus, "active_tids": active, "restored_tids": restored}


def parse_recorded_passes(value: str) -> tuple[int, ...]:
    try:
        passes = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "recorded pass list must contain comma-separated positive integers"
        ) from error
    if not passes or any(number <= 0 for number in passes):
        raise argparse.ArgumentTypeError(
            "recorded pass list must contain comma-separated positive integers"
        )
    if tuple(sorted(set(passes))) != passes:
        raise argparse.ArgumentTypeError(
            "recorded pass list must be sorted and contain no duplicates"
        )
    return passes


def parse_cpu_set(value: str) -> tuple[int, ...]:
    try:
        cpus = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "CPU set must contain comma-separated CPU numbers"
        ) from error
    if not cpus or any(cpu < 0 or cpu > 7 for cpu in cpus):
        raise argparse.ArgumentTypeError("CPU numbers must be from 0 through 7")
    if tuple(sorted(set(cpus))) != cpus:
        raise argparse.ArgumentTypeError(
            "CPU set must be sorted and contain no duplicates"
        )
    return cpus


def parse_xrandr_geometry(output: str) -> str | None:
    match = re.search(r"^Screen 0:.* current (\d+) x (\d+),", output, re.MULTILINE)
    return f"{match.group(1)}x{match.group(2)}" if match else None


def parse_xrandr_refresh(output: str) -> list[float]:
    refresh = []
    for line in output.splitlines():
        if "*" not in line:
            continue
        for value in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\*", line):
            refresh.append(float(value))
    return refresh


def meminfo(proc_root: Path) -> dict[str, int]:
    wanted = {"MemAvailable", "SwapFree", "SwapTotal"}
    result = {}
    text = read_text(proc_root / "meminfo") or ""
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            result[f"{key}_kib"] = int(value.split()[0])
    return result


def cpu_snapshot(cpu_root: Path) -> list[dict[str, int | None]]:
    result = []
    for cpu in range(os.cpu_count() or 0):
        root = cpu_root / f"cpu{cpu}" / "cpufreq"
        row = {"cpu": cpu}
        for name, filename in (
            ("current_khz", "scaling_cur_freq"),
            ("policy_max_khz", "scaling_max_freq"),
            ("hardware_max_khz", "cpuinfo_max_freq"),
        ):
            value = read_text(root / filename)
            row[name] = int(value) if value and value.isdecimal() else None
        result.append(row)
    return result


def gpu_snapshot(kgsl_root: Path) -> dict[str, int | str | None]:
    available = read_text(kgsl_root / "devfreq/available_frequencies")
    numeric_available = (
        [int(value) for value in available.split() if value.isdecimal()]
        if available
        else []
    )
    result: dict[str, int | str | None] = {
        "busy_percent": read_text(kgsl_root / "gpu_busy_percentage"),
        "available_frequencies_hz": available,
        "hardware_max_hz": max(numeric_available) if numeric_available else None,
    }
    for name, filename in (
        ("current_hz", "devfreq/cur_freq"),
        ("policy_max_hz", "devfreq/max_freq"),
        ("thermal_pwrlevel", "thermal_pwrlevel"),
    ):
        value = read_text(kgsl_root / filename)
        result[name] = int(value) if value and value.isdecimal() else value
    return result


def thermal_snapshot(thermal_root: Path, limit: int = 12):
    result = []
    for zone in thermal_root.glob("thermal_zone*"):
        name = read_text(zone / "type")
        value = read_text(zone / "temp")
        if name is None or value is None:
            continue
        try:
            temperature = int(value)
        except ValueError:
            continue
        result.append({"zone": name, "millidegrees_c": temperature})
    return sorted(result, key=lambda row: -row["millidegrees_c"])[:limit]


def system_snapshot(proc_root: Path, cpu_root: Path, kgsl_root: Path, thermal_root: Path):
    return {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "memory": meminfo(proc_root),
        "cpu": cpu_snapshot(cpu_root),
        "gpu": gpu_snapshot(kgsl_root),
        "thermal": thermal_snapshot(thermal_root),
    }


def throttle_issues(snapshot) -> list[str]:
    issues = []
    throttled_cpus = []
    for row in snapshot["cpu"]:
        policy = row["policy_max_khz"]
        hardware = row["hardware_max_khz"]
        if policy is not None and hardware is not None and policy < hardware:
            throttled_cpus.append(row["cpu"])
    if throttled_cpus:
        issues.append(f"CPU policy is throttled before the pass: {throttled_cpus}")
    gpu = snapshot["gpu"]
    if (
        isinstance(gpu["policy_max_hz"], int)
        and isinstance(gpu["hardware_max_hz"], int)
        and gpu["policy_max_hz"] < gpu["hardware_max_hz"]
    ):
        issues.append(
            "GPU policy is throttled before the pass: "
            f"{gpu['policy_max_hz']} < {gpu['hardware_max_hz']}"
        )
    if gpu["thermal_pwrlevel"] not in (None, 0, "0"):
        issues.append(
            f"GPU thermal power level is nonzero before the pass: {gpu['thermal_pwrlevel']}"
        )
    return issues


def require_unthrottled(snapshot) -> None:
    issues = throttle_issues(snapshot)
    if issues:
        raise RuntimeError("; ".join(issues))


def maximum_temperature_millidegrees(snapshot) -> int | None:
    temperatures = [
        row["millidegrees_c"]
        for row in snapshot["thermal"]
        if isinstance(row.get("millidegrees_c"), int)
    ]
    return max(temperatures) if temperatures else None


def benchmark_readiness_issues(snapshot, temperature_ceiling: int) -> list[str]:
    issues = throttle_issues(snapshot)
    maximum = maximum_temperature_millidegrees(snapshot)
    if maximum is None:
        issues.append("thermal-zone temperatures are unavailable")
    elif maximum > temperature_ceiling:
        issues.append(
            f"maximum temperature is {maximum / 1000:.1f}C, "
            f"above {temperature_ceiling / 1000:.1f}C start ceiling"
        )
    return issues


def wait_for_benchmark_ready(
    snapshotter,
    temperature_ceiling: int,
    timeout_seconds: int,
    poll_seconds: int,
    stable_samples: int,
    *,
    monotonic=time.monotonic,
    sleeper=time.sleep,
):
    started = monotonic()
    stable = 0
    latest = None
    latest_issues = []
    while True:
        latest = snapshotter()
        latest_issues = benchmark_readiness_issues(latest, temperature_ceiling)
        if latest_issues:
            stable = 0
        else:
            stable += 1
            if stable >= stable_samples:
                return latest, round(monotonic() - started, 3)
        elapsed = monotonic() - started
        if elapsed >= timeout_seconds:
            raise RuntimeError(
                f"cooldown did not reach {stable_samples} stable ready samples "
                f"within {timeout_seconds}s; last state: "
                + "; ".join(latest_issues or [f"stable samples {stable}/{stable_samples}"])
            )
        print(
            "cooldown: "
            + "; ".join(latest_issues or [f"stable sample {stable}/{stable_samples}"]),
            flush=True,
        )
        sleeper(min(poll_seconds, max(0, timeout_seconds - elapsed)))


def command_failure(command, output: Path, return_code: int) -> RuntimeError:
    return RuntimeError(
        f"command exited {return_code}; inspect {output}: "
        + " ".join(str(value) for value in command)
    )


def run_logged_outcome(command, environment, output: Path) -> tuple[float, int]:
    started = time.monotonic()
    completed = subprocess.run(
        [str(value) for value in command],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    elapsed = time.monotonic() - started
    output.write_text(completed.stdout)
    return elapsed, completed.returncode


def run_logged(command, environment, output: Path) -> float:
    elapsed, return_code = run_logged_outcome(command, environment, output)
    if return_code != 0:
        raise command_failure(command, output, return_code)
    return elapsed


def run_logged_with_cef_holder(
    command,
    environment,
    output: Path,
    holder_command,
    holder_output: Path,
    allow_launch_failure: bool = False,
) -> tuple[float, list[int], int]:
    launch_error = None
    elapsed = None
    launch_return_code = None
    with holder_output.open("w") as holder_log:
        holder = subprocess.Popen(
            [str(value) for value in holder_command],
            env=environment,
            stdout=holder_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            elapsed, launch_return_code = run_logged_outcome(
                command, environment, output
            )
            if launch_return_code != 0 and not allow_launch_failure:
                launch_error = command_failure(command, output, launch_return_code)
        except BaseException as error:
            launch_error = error
        try:
            holder_return_code = holder.wait(timeout=15)
        except subprocess.TimeoutExpired as error:
            holder.terminate()
            try:
                holder_return_code = holder.wait(timeout=15)
            except subprocess.TimeoutExpired as stop_error:
                raise RuntimeError(
                    "Steam CEF holder did not stop after graceful termination; "
                    "it will retain its own bounded hold timeout"
                ) from stop_error
            if launch_error is None:
                launch_error = RuntimeError(
                    "Steam CEF holder outlived the game launch command"
                )
        if launch_error is not None:
            raise launch_error
        if holder_return_code != 0:
            raise RuntimeError(
                f"Steam CEF holder exited {holder_return_code}; inspect {holder_output}"
            )
    if elapsed is None:
        raise RuntimeError("game launch elapsed time is unavailable")
    if launch_return_code is None:
        raise RuntimeError("game launch return code is unavailable")
    return elapsed, parse_cef_hold_log(holder_output.read_text()), launch_return_code


def run_logged_with_x11_isolator(
    command,
    environment,
    output: Path,
    isolator_command,
    isolator_output: Path,
    allow_launch_failure: bool = False,
) -> tuple[float, dict[str, int | list[int]], int]:
    launch_error = None
    elapsed = None
    launch_return_code = None
    with isolator_output.open("w") as isolator_log:
        isolator = subprocess.Popen(
            [str(value) for value in isolator_command],
            env=environment,
            stdout=isolator_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            elapsed, launch_return_code = run_logged_outcome(
                command, environment, output
            )
            if launch_return_code != 0 and not allow_launch_failure:
                launch_error = command_failure(command, output, launch_return_code)
        except BaseException as error:
            launch_error = error
        try:
            isolator_return_code = isolator.wait(timeout=15)
        except subprocess.TimeoutExpired as error:
            isolator.terminate()
            try:
                isolator_return_code = isolator.wait(timeout=15)
            except subprocess.TimeoutExpired as stop_error:
                raise RuntimeError(
                    "Termux X11 isolator did not stop after graceful termination; "
                    "it retains its own bounded isolation timeout"
                ) from stop_error
            if launch_error is None:
                launch_error = RuntimeError(
                    "Termux X11 isolator outlived the game launch command"
                )
        if launch_error is not None:
            raise launch_error
        if isolator_return_code != 0:
            raise RuntimeError(
                f"Termux X11 isolator exited {isolator_return_code}; "
                f"inspect {isolator_output}"
            )
    if elapsed is None:
        raise RuntimeError("game launch elapsed time is unavailable")
    if launch_return_code is None:
        raise RuntimeError("game launch return code is unavailable")
    return (
        elapsed,
        parse_x11_isolation_log(isolator_output.read_text()),
        launch_return_code,
    )


def python_tool_command(tool: Path, *arguments: str) -> list[Path | str]:
    return [Path(sys.executable), tool, *arguments]


def atomic_json(path: Path, data) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w") as output:
        json.dump(data, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def set_series_phase(
    series: dict, phase: str, active_pass: dict | None = None
) -> None:
    if phase not in SERIES_PHASES:
        raise ValueError(f"unknown benchmark series phase: {phase}")
    updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    series["phase"] = phase
    series["phase_updated_at"] = updated_at
    if active_pass is None:
        series["active_pass"] = None
        return
    current = {
        key: value
        for key, value in active_pass.items()
        if key not in ("phase", "updated_at")
    }
    current["phase"] = phase
    current["updated_at"] = updated_at
    series["active_pass"] = current


def aggregate_results(runs) -> dict[str, dict[str, float]]:
    recorded = [run["metrics"] for run in runs if run["kind"] == "recorded"]
    if not recorded:
        raise RuntimeError("benchmark series has no recorded passes")
    result = {}
    for metric in ("minimum_fps", "maximum_fps", "average_fps"):
        values = [row[metric] for row in recorded]
        result[metric] = {
            "mean": round(statistics.fmean(values), 3),
            "median": round(statistics.median(values), 3),
            "values": values,
        }
    return result


def aggregate_cef_hold_conditions(runs) -> dict[str, dict[str, dict[str, float]]]:
    control = [
        run
        for run in runs
        if run["kind"] == "recorded" and not run["steam_cef_hold"]
    ]
    held = [
        run
        for run in runs
        if run["kind"] == "recorded" and run["steam_cef_hold"]
    ]
    if not control or not held:
        raise RuntimeError("paired CEF comparison requires control and held passes")
    return {
        "control": aggregate_results(control),
        "steam_cef_hold": aggregate_results(held),
    }


def aggregate_x11_isolation_conditions(runs) -> dict[str, dict[str, dict[str, float]]]:
    control = [
        run
        for run in runs
        if run["kind"] == "recorded" and not run["x11_isolation"]
    ]
    isolated = [
        run
        for run in runs
        if run["kind"] == "recorded" and run["x11_isolation"]
    ]
    if not control or not isolated:
        raise RuntimeError("paired X11 isolation comparison requires both conditions")
    return {
        "control": aggregate_results(control),
        "x11_isolation": aggregate_results(isolated),
    }


def aggregate_raknet_exclusive_conditions(
    runs,
) -> dict[str, dict[str, dict[str, float]]]:
    control = [
        run
        for run in runs
        if run["kind"] == "recorded" and not run["raknet_exclusive"]
    ]
    exclusive = [
        run
        for run in runs
        if run["kind"] == "recorded" and run["raknet_exclusive"]
    ]
    if not control or not exclusive:
        raise RuntimeError(
            "paired RakNet-exclusive comparison requires both conditions"
        )
    return {
        "control": aggregate_results(control),
        "raknet_exclusive": aggregate_results(exclusive),
    }


def affinity_log_is_ready(
    text: str, backend: str, expected_game_cpus: str = "1-7"
) -> bool:
    ready_lines = [
        line
        for line in text.splitlines()
        if line.startswith("Tomb Raider performance state: ready;")
    ]
    if len(ready_lines) != 1:
        return False
    if backend == "direct":
        return (
            f"CPUs {expected_game_cpus}" in ready_lines[0]
            and (
                "observing inherited startup topology on CPUs " in text
                or "holding startup topology on CPUs " in text
            )
            and "startup topology ready; logical=" in text
        )
    return backend == "proot"


def mark_series_failed(series: dict, error: BaseException) -> None:
    series["status"] = "failed"
    set_series_phase(series, "failed", series.get("active_pass"))
    series["failure"] = {
        "type": type(error).__name__,
        "message": str(error),
    }
    series["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    home = Path.home()
    parser = argparse.ArgumentParser(
        description="Run one warm-up and a controlled native-host Tomb Raider series"
    )
    parser.add_argument("--profile", choices=("safe", "proton", "fast"), default="safe")
    parser.add_argument("--backend", choices=("proot", "direct"), default="proot")
    cef_group = parser.add_mutually_exclusive_group()
    cef_group.add_argument(
        "--hold-steam-cef",
        action="store_true",
        help="experimentally suspend verified native Steam CEF descendants during each pass",
    )
    cef_group.add_argument(
        "--steam-cef-hold-recorded-passes",
        type=parse_recorded_passes,
        default=(),
        metavar="N[,N...]",
        help="recorded pass numbers that receive the experimental native Steam CEF hold",
    )
    x11_group = parser.add_mutually_exclusive_group()
    x11_group.add_argument(
        "--isolate-x11",
        action="store_true",
        help="experimentally isolate verified Termux:X11 threads each pass",
    )
    x11_group.add_argument(
        "--x11-isolation-recorded-passes",
        type=parse_recorded_passes,
        default=(),
        metavar="N[,N...]",
        help="recorded pass numbers that receive experimental X11 CPU isolation",
    )
    parser.add_argument(
        "--x11-isolation-cpus",
        type=parse_cpu_set,
        default=(0,),
        metavar="CPU[,CPU...]",
        help="validated CPU set used by the opt-in X11 isolation experiment",
    )
    parser.add_argument(
        "--raknet-nice",
        type=int,
        help="opt-in nice value for the isolated RakNet receive thread",
    )
    parser.add_argument(
        "--raknet-exclusive-recorded-passes",
        type=parse_recorded_passes,
        default=(),
        metavar="N[,N...]",
        help=(
            "recorded pass numbers that reserve CPU1 for RakNet and constrain "
            "other game threads to CPUs2-7"
        ),
    )
    parser.add_argument(
        "--startup-topology",
        choices=("available", "full"),
        default="available",
        help="direct child affinity required before Proton exec",
    )
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--base", default=str(home / "steam-arm64"))
    parser.add_argument("--primer", default=str(home / "start-steam-native.sh"))
    parser.add_argument("--launcher")
    parser.add_argument("--display", default=":0")
    parser.add_argument("--output-dir")
    parser.add_argument("--cooldown-timeout", type=int, default=1800)
    parser.add_argument("--cooldown-poll", type=int, default=10)
    parser.add_argument("--cooldown-stable-samples", type=int, default=3)
    parser.add_argument("--start-temperature-margin-c", type=float, default=2.0)
    parser.add_argument(
        "--start-temperature-ceiling-c",
        type=float,
        help=(
            "fixed maximum starting sensor temperature for every pass; "
            "use this instead of the warm-up-relative margin for cross-series A/Bs"
        ),
    )
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if not 0 <= arguments.warmups <= 3:
        print("warmups must be between 0 and 3", file=sys.stderr)
        return 2
    if not 1 <= arguments.runs <= 10:
        print("runs must be between 1 and 10", file=sys.stderr)
        return 2
    if arguments.cooldown_timeout <= 0 or arguments.cooldown_poll <= 0:
        print("cooldown timeout and poll must be positive", file=sys.stderr)
        return 2
    if not 1 <= arguments.cooldown_stable_samples <= 12:
        print("cooldown stable samples must be between 1 and 12", file=sys.stderr)
        return 2
    if not 0 <= arguments.start_temperature_margin_c <= 20:
        print("start temperature margin must be between 0C and 20C", file=sys.stderr)
        return 2
    if (
        arguments.start_temperature_ceiling_c is not None
        and not 20 <= arguments.start_temperature_ceiling_c <= 80
    ):
        print(
            "start temperature ceiling must be between 20C and 80C",
            file=sys.stderr,
        )
        return 2
    if arguments.raknet_nice is not None and not 0 <= arguments.raknet_nice <= 19:
        print("RakNet nice value must be between 0 and 19", file=sys.stderr)
        return 2
    if arguments.raknet_nice is not None and arguments.backend != "direct":
        print("RakNet nice experiments require the direct backend", file=sys.stderr)
        return 2
    cef_hold_requested = bool(
        arguments.hold_steam_cef or arguments.steam_cef_hold_recorded_passes
    )
    x11_isolation_requested = bool(
        arguments.isolate_x11 or arguments.x11_isolation_recorded_passes
    )
    raknet_exclusive_requested = bool(
        arguments.raknet_exclusive_recorded_passes
    )
    if cef_hold_requested and arguments.backend != "direct":
        print("Steam CEF hold experiments require the direct backend", file=sys.stderr)
        return 2
    if any(
        number > arguments.runs
        for number in arguments.steam_cef_hold_recorded_passes
    ):
        print("Steam CEF hold pass number exceeds configured recorded runs", file=sys.stderr)
        return 2
    if x11_isolation_requested and arguments.backend != "direct":
        print("Termux X11 isolation experiments require the direct backend", file=sys.stderr)
        return 2
    if any(
        number > arguments.runs
        for number in arguments.x11_isolation_recorded_passes
    ):
        print("X11 isolation pass number exceeds configured recorded runs", file=sys.stderr)
        return 2
    if cef_hold_requested and x11_isolation_requested:
        print("CEF hold and X11 isolation cannot be combined in one series", file=sys.stderr)
        return 2
    if raknet_exclusive_requested and arguments.backend != "direct":
        print("RakNet-exclusive experiments require the direct backend", file=sys.stderr)
        return 2
    if any(
        number > arguments.runs
        for number in arguments.raknet_exclusive_recorded_passes
    ):
        print(
            "RakNet-exclusive pass number exceeds configured recorded runs",
            file=sys.stderr,
        )
        return 2
    if raknet_exclusive_requested and (
        cef_hold_requested
        or x11_isolation_requested
        or arguments.raknet_nice is not None
    ):
        print(
            "RakNet-exclusive passes cannot be combined with CEF, X11, or "
            "RakNet-nice experiments",
            file=sys.stderr,
        )
        return 2
    if arguments.startup_topology != "available" and arguments.backend != "direct":
        print("full startup topology requires the direct backend", file=sys.stderr)
        return 2

    base = Path(arguments.base).resolve()
    primer = Path(arguments.primer).resolve()
    launcher = Path(
        arguments.launcher
        or (
            Path.home() / "start-tombraider-direct-benchmark"
            if arguments.backend == "direct"
            else Path.home() / "start-tombraider-native.sh"
        )
    ).resolve()
    game_directory = base / "removable-library/steamapps/common/Tomb Raider"
    guard_directory = base / "logs"
    profile_checker = base / "compat-bin/configure-tombraider-performance.py"
    topology_checker = base / "compat-bin/configure-tombraider-cpu-topology.py"
    cef_holder = base / "compat-bin/hold-tombraider-steam-cef.py"
    x11_isolator = base / "compat-bin/isolate-tombraider-x11.py"
    steam_executable = base / "client/steamrtarm64/steam"
    proc_root = Path("/proc")
    cpu_root = Path("/sys/devices/system/cpu")
    kgsl_root = Path("/sys/class/kgsl/kgsl-3d0")
    thermal_root = Path("/sys/class/thermal")
    series_id = (
        dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + f"-{arguments.profile}"
    )
    output_directory = (
        Path(arguments.output_dir).resolve()
        if arguments.output_dir
        else base / "logs/tombraider-benchmarks" / series_id
    )
    series = None

    try:
        require_top_app()
        required = [
            (launcher, f"{arguments.backend} Tomb Raider launcher"),
            (profile_checker, "Tomb Raider profile checker"),
            (steam_executable, "native Steam executable"),
        ]
        if arguments.backend == "proot":
            required.insert(0, (primer, "native Steam primer"))
        else:
            required.append((topology_checker, "Tomb Raider CPU-topology checker"))
            if cef_hold_requested:
                required.append((cef_holder, "native Steam CEF holder"))
            if x11_isolation_requested:
                required.append((x11_isolator, "Termux X11 isolator"))
        for path, label in required:
            require_regular(path, label, executable=True)
        if not game_directory.is_dir() or game_directory.is_symlink():
            raise RuntimeError(f"game directory is unavailable or unsafe: {game_directory}")
        existing_steam_pids = find_exact_processes(proc_root, steam_executable)
        if arguments.backend == "direct":
            if len(existing_steam_pids) != 1:
                raise RuntimeError(
                    "direct benchmark requires exactly one existing native Steam "
                    f"process, found {existing_steam_pids}"
                )
        elif existing_steam_pids:
            raise RuntimeError(
                "native Steam is already active; stop it before a profile-controlled series"
            )
        output_directory.mkdir(parents=True, mode=0o700, exist_ok=False)

        environment = {
            **os.environ,
            "DISPLAY": arguments.display,
            "STEAM_BACKGROUND": "1",
            "STEAM_ARM64_FEX_PROFILE": arguments.profile,
        }
        environment.pop("TOMB_RAIDER_RAKNET_NICE", None)
        environment.pop("TOMB_RAIDER_GAME_CPUS", None)
        environment.pop("STEAM_ARM64_DIRECT_STARTUP_TOPOLOGY", None)
        if arguments.backend == "direct":
            environment["STEAM_ARM64_DIRECT_STARTUP_TOPOLOGY"] = (
                arguments.startup_topology
            )
        if arguments.raknet_nice is not None:
            environment["TOMB_RAIDER_RAKNET_NICE"] = str(arguments.raknet_nice)
        series = {
            "schema_version": 1,
            "status": "initializing",
            "series_id": series_id,
            "game": "Tomb Raider (2013)",
            "appid": 203160,
            "stack": (
                "native glibc Steam host; direct Runtime 4/Proton game execution"
                if arguments.backend == "direct"
                else "native glibc Steam host; Runtime 4/PRoot/Proton game boundary"
            ),
            "target": {
                "resolution": PANEL_GEOMETRY,
                "graphics": "Low",
                "vsync": "off",
                "motion_blur": "off",
                "fex_profile": arguments.profile,
                "raknet_nice": arguments.raknet_nice,
                "raknet_exclusive_recorded_passes": list(
                    arguments.raknet_exclusive_recorded_passes
                ),
                "steam_cef_hold": arguments.hold_steam_cef,
                "steam_cef_hold_recorded_passes": list(
                    arguments.steam_cef_hold_recorded_passes
                ),
                "x11_isolation": arguments.isolate_x11,
                "x11_isolation_recorded_passes": list(
                    arguments.x11_isolation_recorded_passes
                ),
                "x11_isolation_cpus": list(arguments.x11_isolation_cpus),
                "startup_topology": arguments.startup_topology,
                "backend": arguments.backend,
                "warmups": arguments.warmups,
                "recorded_runs": arguments.runs,
                "cooldown_timeout_seconds": arguments.cooldown_timeout,
                "cooldown_poll_seconds": arguments.cooldown_poll,
                "cooldown_stable_samples": arguments.cooldown_stable_samples,
                "start_temperature_margin_c": arguments.start_temperature_margin_c,
            },
            "method": (
                "Game command-line -benchmark mode; no profiler, capture, or "
                "window switch runs during the timed scene"
            ),
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "runs": [],
        }
        set_series_phase(series, "initializing")
        atomic_json(output_directory / "series.json", series)

        profile_log = output_directory / "profile-check.log"
        # RunCommandService does not inherit the interactive termux-exec
        # preload, so a child cannot resolve this tool's /usr/bin/env shebang.
        # Reuse the already-resolved absolute Python interpreter instead.
        run_logged(
            python_tool_command(profile_checker, "--check"),
            environment,
            profile_log,
        )
        if arguments.backend == "direct":
            topology_log = output_directory / "cpu-topology-fix-check.log"
            run_logged(
                python_tool_command(topology_checker, "--check"),
                environment,
                topology_log,
            )
            series["target"]["cpu_topology_fix_sha256"] = (
                parse_topology_fix_status(topology_log.read_text())
            )
            atomic_json(output_directory / "series.json", series)
            steam_pids = existing_steam_pids
            series["steam_reused"] = True
        else:
            prime_log = output_directory / "steam-prime.log"
            series["steam_prime_seconds"] = round(
                run_logged([primer], environment, prime_log), 3
            )
            steam_pids = find_exact_processes(proc_root, steam_executable)
        if len(steam_pids) != 1:
            raise RuntimeError(
                f"expected one native Steam process after priming, found {steam_pids}"
            )
        steam_environment = environment_for_pid(proc_root, steam_pids[0])
        effective_profile = steam_environment.get("STEAM_ARM64_FEX_PROFILE")
        if arguments.backend == "direct":
            series["steam_fex_profile"] = effective_profile
            series["direct_game_fex_profile"] = arguments.profile
        elif effective_profile != arguments.profile:
            raise RuntimeError(
                f"native Steam inherited FEX profile {effective_profile!r}, "
                f"expected {arguments.profile!r}"
            )
        series["steam_pid"] = steam_pids[0]

        xrandr = subprocess.run(
            ["xrandr", "--current"],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        (output_directory / "xrandr.txt").write_text(xrandr.stdout)
        if xrandr.returncode != 0:
            raise RuntimeError("xrandr preflight failed")
        geometry = parse_xrandr_geometry(xrandr.stdout)
        if geometry != PANEL_GEOMETRY:
            raise RuntimeError(
                f"X11 geometry is {geometry or 'unknown'}, expected {PANEL_GEOMETRY}"
            )
        series["display"] = {
            "geometry": geometry,
            "active_refresh_hz": parse_xrandr_refresh(xrandr.stdout),
        }

        total = arguments.warmups + arguments.runs
        temperature_ceiling = (
            round(arguments.start_temperature_ceiling_c * 1000)
            if arguments.start_temperature_ceiling_c is not None
            else None
        )
        fixed_temperature_ceiling = temperature_ceiling is not None
        if fixed_temperature_ceiling:
            series["target"]["configured_start_temperature_ceiling_millidegrees_c"] = (
                temperature_ceiling
            )
            series["target"]["start_temperature_ceiling_millidegrees_c"] = (
                temperature_ceiling
            )
        for index in range(total):
            kind = "warmup" if index < arguments.warmups else "recorded"
            number = index + 1 if kind == "warmup" else index - arguments.warmups + 1
            label = f"{kind}-{number}"
            use_cef_hold = arguments.hold_steam_cef or (
                kind == "recorded"
                and number in arguments.steam_cef_hold_recorded_passes
            )
            use_x11_isolation = arguments.isolate_x11 or (
                kind == "recorded"
                and number in arguments.x11_isolation_recorded_passes
            )
            use_raknet_exclusive = (
                kind == "recorded"
                and number in arguments.raknet_exclusive_recorded_passes
            )
            expected_game_cpus = "2-7" if use_raknet_exclusive else "1-7"
            active_pass = {
                "kind": kind,
                "number": number,
                "label": label,
                "game_cpus": expected_game_cpus,
                "steam_cef_hold": use_cef_hold,
                "x11_isolation": use_x11_isolation,
                "raknet_exclusive": use_raknet_exclusive,
            }
            series["status"] = "running"
            set_series_phase(
                series,
                "preflight" if temperature_ceiling is None else "cooldown",
                active_pass,
            )
            atomic_json(output_directory / "series.json", series)
            if temperature_ceiling is None:
                before = system_snapshot(proc_root, cpu_root, kgsl_root, thermal_root)
                require_unthrottled(before)
                initial_temperature = maximum_temperature_millidegrees(before)
                if initial_temperature is None:
                    raise RuntimeError("thermal-zone temperatures are unavailable")
                temperature_ceiling = initial_temperature + round(
                    arguments.start_temperature_margin_c * 1000
                )
                series["target"]["initial_max_temperature_millidegrees_c"] = (
                    initial_temperature
                )
                series["target"]["start_temperature_ceiling_millidegrees_c"] = (
                    temperature_ceiling
                )
                cooldown_seconds = 0.0
            else:
                before, cooldown_seconds = wait_for_benchmark_ready(
                    lambda: system_snapshot(
                        proc_root, cpu_root, kgsl_root, thermal_root
                    ),
                    temperature_ceiling,
                    arguments.cooldown_timeout,
                    arguments.cooldown_poll,
                    arguments.cooldown_stable_samples,
                )
                if fixed_temperature_ceiling and index == 0:
                    series["target"]["initial_max_temperature_millidegrees_c"] = (
                        maximum_temperature_millidegrees(before)
                    )
            result_before = file_state(game_directory.glob(RESULT_GLOB))
            guard_glob = (
                DIRECT_GUARD_GLOB
                if arguments.backend == "direct"
                else PROOT_GUARD_GLOB
            )
            guard_before = file_state(guard_directory.glob(guard_glob))
            launch_log = output_directory / f"{label}-launch.log"
            launch_command = (
                [launcher]
                if arguments.backend == "direct"
                else [launcher, "-benchmark"]
            )
            cef_hold_pids = None
            x11_isolation_evidence = None
            pass_environment = environment.copy()
            pass_environment["TOMB_RAIDER_GAME_CPUS"] = expected_game_cpus
            launch_return_code = 0
            set_series_phase(series, "launching_or_running", active_pass)
            atomic_json(output_directory / "series.json", series)
            if use_cef_hold:
                cef_hold_log = output_directory / f"{label}-steam-cef-hold.log"
                elapsed, cef_hold_pids, launch_return_code = run_logged_with_cef_holder(
                    launch_command,
                    pass_environment,
                    launch_log,
                    python_tool_command(
                        cef_holder,
                        "--acknowledge-experimental",
                        "--wait-seconds",
                        "300",
                        "--delay-seconds",
                        "25",
                        "--hold-timeout-seconds",
                        "300",
                    ),
                    cef_hold_log,
                    allow_launch_failure=arguments.backend == "direct",
                )
            elif use_x11_isolation:
                x11_isolation_log = output_directory / f"{label}-x11-isolation.log"
                (
                    elapsed,
                    x11_isolation_evidence,
                    launch_return_code,
                ) = run_logged_with_x11_isolator(
                    launch_command,
                    pass_environment,
                    launch_log,
                    python_tool_command(
                        x11_isolator,
                        "--acknowledge-experimental",
                        "--display",
                        arguments.display,
                        "--cpus",
                        ",".join(str(cpu) for cpu in arguments.x11_isolation_cpus),
                        "--wait-seconds",
                        "300",
                        "--delay-seconds",
                        "25",
                        "--isolation-timeout-seconds",
                        "300",
                    ),
                    x11_isolation_log,
                    allow_launch_failure=arguments.backend == "direct",
                )
            else:
                if arguments.backend == "direct":
                    elapsed, launch_return_code = run_logged_outcome(
                        launch_command, pass_environment, launch_log
                    )
                else:
                    elapsed = run_logged(
                        launch_command, pass_environment, launch_log
                    )

            set_series_phase(series, "validating_result", active_pass)
            atomic_json(output_directory / "series.json", series)

            result_files = new_regular_files(game_directory, RESULT_GLOB, result_before)
            if len(result_files) != 1:
                raise RuntimeError(
                    f"{label} produced {len(result_files)} benchmark result files: "
                    + ", ".join(str(path) for path in result_files)
                )
            guard_files = new_regular_files(guard_directory, guard_glob, guard_before)
            ready_guards = [
                path
                for path in guard_files
                if affinity_log_is_ready(
                    read_text(path) or "",
                    arguments.backend,
                    expected_game_cpus,
                )
            ]
            if len(ready_guards) != 1:
                raise RuntimeError(
                    f"{label} has {len(ready_guards)} ready affinity logs; "
                    f"changed logs: {guard_files}"
                )

            raw = result_files[0].read_bytes()
            metrics = parse_benchmark_result(raw)
            accepted_post_result_exit = None
            if launch_return_code != 0:
                if arguments.backend != "direct":
                    raise command_failure(
                        launch_command, launch_log, launch_return_code
                    )
                accepted_post_result_exit = validate_post_result_pulse_abort(
                    launch_log, launch_return_code, base, proc_root
                )
            raw_copy = output_directory / f"{label}-benchmark.txt"
            raw_copy.write_bytes(raw)
            guard_copy = output_directory / f"{label}-affinity.log"
            shutil.copyfile(ready_guards[0], guard_copy)
            after = system_snapshot(proc_root, cpu_root, kgsl_root, thermal_root)
            run = {
                "kind": kind,
                "number": number,
                "metrics": metrics,
                "elapsed_seconds": round(elapsed, 3),
                "launch_return_code": launch_return_code,
                "accepted_post_result_exit": accepted_post_result_exit,
                "cooldown_seconds": cooldown_seconds,
                "source_result": str(result_files[0]),
                "source_affinity_log": str(ready_guards[0]),
                "steam_cef_hold": use_cef_hold,
                "steam_cef_hold_pids": cef_hold_pids,
                "x11_isolation": use_x11_isolation,
                "x11_isolation_evidence": x11_isolation_evidence,
                "raknet_exclusive": use_raknet_exclusive,
                "game_cpus": expected_game_cpus,
                "before": before,
                "after": after,
            }
            series["runs"].append(run)
            series["status"] = "running"
            set_series_phase(series, "result_accepted", active_pass)
            atomic_json(output_directory / "series.json", series)
            print(
                f"{label}: min={metrics['minimum_fps']} "
                f"max={metrics['maximum_fps']} avg={metrics['average_fps']}",
                flush=True,
            )

        series["aggregate"] = aggregate_results(series["runs"])
        if arguments.steam_cef_hold_recorded_passes:
            series["condition_aggregates"] = aggregate_cef_hold_conditions(
                series["runs"]
            )
        if arguments.x11_isolation_recorded_passes:
            series["condition_aggregates"] = aggregate_x11_isolation_conditions(
                series["runs"]
            )
        if arguments.raknet_exclusive_recorded_passes:
            series["condition_aggregates"] = aggregate_raknet_exclusive_conditions(
                series["runs"]
            )
        series["status"] = "complete"
        series["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        set_series_phase(series, "complete")
        atomic_json(output_directory / "series.json", series)
        average = series["aggregate"]["average_fps"]
        print(
            f"recorded average FPS: mean={average['mean']} "
            f"median={average['median']} values={average['values']}"
        )
        print(output_directory / "series.json")
    except (OSError, RuntimeError, subprocess.SubprocessError, UnicodeError) as error:
        if series is not None and output_directory.is_dir():
            mark_series_failed(series, error)
            try:
                atomic_json(output_directory / "series.json", series)
            except OSError as artifact_error:
                print(
                    "run-tombraider-native-benchmark: could not record failure: "
                    f"{artifact_error}",
                    file=sys.stderr,
                )
        print(f"run-tombraider-native-benchmark: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
