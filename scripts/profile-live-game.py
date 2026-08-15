#!/usr/bin/env python3
"""Take two low-overhead /proc snapshots of a live game session."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


PROC_ROOT = Path("/proc")
CPU_ROOT = Path("/sys/devices/system/cpu")
KGSL_ROOT = Path("/sys/class/kgsl/kgsl-3d0")
THERMAL_ROOT = Path("/sys/class/thermal")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None


def parse_stat(text: str) -> dict[str, int | str]:
    closing = text.rfind(")")
    opening = text.find("(")
    if opening < 0 or closing <= opening:
        raise ValueError("malformed proc stat record")
    pid = int(text[:opening].strip())
    name = text[opening + 1 : closing]
    fields = text[closing + 2 :].split()
    if len(fields) < 20:
        raise ValueError("short proc stat record")
    return {
        "pid": pid,
        "name": name,
        "ticks": int(fields[11]) + int(fields[12]),
        "start_ticks": int(fields[19]),
        "processor": int(fields[36]) if len(fields) > 36 else -1,
    }


def read_stat(path: Path) -> dict[str, int | str] | None:
    text = read_text(path)
    if text is None:
        return None
    try:
        return parse_stat(text)
    except (ValueError, IndexError):
        return None


def parse_status(path: Path) -> dict[str, str]:
    text = read_text(path)
    if text is None:
        return {}
    wanted = {"Name", "VmRSS", "Threads", "Cpus_allowed_list"}
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            result[key] = value.strip()
    return result


def same_uid_processes(proc_root: Path = PROC_ROOT) -> dict[int, dict[str, int | str]]:
    processes = {}
    for directory in proc_root.iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        record = read_stat(directory / "stat")
        if record is not None:
            processes[int(record["pid"])] = record
    return processes


def thread_stats(pid: int, proc_root: Path = PROC_ROOT) -> dict[int, dict[str, int | str]]:
    tasks = {}
    task_root = proc_root / str(pid) / "task"
    try:
        directories = list(task_root.iterdir())
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return tasks
    for directory in directories:
        if not directory.name.isdecimal():
            continue
        record = read_stat(directory / "stat")
        if record is not None:
            tasks[int(record["pid"])] = record
    return tasks


def find_target(processes: dict[int, dict[str, int | str]], name: str) -> int:
    matches = sorted(pid for pid, record in processes.items() if record["name"] == name)
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {name!r} process, found {len(matches)}")
    return matches[0]


def delta_rows(
    before: dict[int, dict[str, int | str]],
    after: dict[int, dict[str, int | str]],
    elapsed: float,
    clock_ticks: int,
) -> list[dict[str, int | float | str]]:
    rows = []
    for pid, final in after.items():
        initial = before.get(pid)
        if initial is None or initial["start_ticks"] != final["start_ticks"]:
            continue
        tick_delta = int(final["ticks"]) - int(initial["ticks"])
        if tick_delta < 0:
            continue
        rows.append(
            {
                "pid": pid,
                "name": str(final["name"]),
                "cpu_percent": round(tick_delta * 100.0 / clock_ticks / elapsed, 1),
                "processor": int(final["processor"]),
            }
        )
    return sorted(rows, key=lambda row: (-float(row["cpu_percent"]), int(row["pid"])))


def cpu_snapshot() -> list[dict[str, int | str | None]]:
    rows = []
    for cpu in range(os.cpu_count() or 0):
        root = CPU_ROOT / f"cpu{cpu}"
        rows.append(
            {
                "cpu": cpu,
                "capacity": read_text(root / "cpu_capacity"),
                "current_khz": read_text(root / "cpufreq/scaling_cur_freq"),
                "policy_max_khz": read_text(root / "cpufreq/scaling_max_freq"),
                "hardware_max_khz": read_text(root / "cpufreq/cpuinfo_max_freq"),
            }
        )
    return rows


def gpu_snapshot() -> dict[str, str | None]:
    return {
        "busy_percent": read_text(KGSL_ROOT / "gpu_busy_percentage"),
        "current_hz": read_text(KGSL_ROOT / "devfreq/cur_freq"),
        "policy_max_hz": read_text(KGSL_ROOT / "devfreq/max_freq"),
        "hardware_max_hz": read_text(KGSL_ROOT / "devfreq/available_frequencies"),
        "thermal_pwrlevel": read_text(KGSL_ROOT / "thermal_pwrlevel"),
    }


def thermal_snapshot(limit: int = 8) -> list[dict[str, int | str]]:
    rows = []
    for zone in THERMAL_ROOT.glob("thermal_zone*"):
        name = read_text(zone / "type")
        value = read_text(zone / "temp")
        if name is None or value is None:
            continue
        try:
            temperature = int(value)
        except ValueError:
            continue
        rows.append({"zone": name, "millidegrees_c": temperature})
    return sorted(rows, key=lambda row: -int(row["millidegrees_c"]))[:limit]


def memory_snapshot() -> dict[str, int]:
    text = read_text(PROC_ROOT / "meminfo") or ""
    wanted = {"MemAvailable", "SwapFree", "SwapTotal"}
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in wanted:
            result[f"{key}_kib"] = int(value.split()[0])
    return result


def build_report(name: str, seconds: float, top: int) -> dict[str, object]:
    clock_ticks = os.sysconf("SC_CLK_TCK")
    processes_before = same_uid_processes()
    target_pid = find_target(processes_before, name)
    target_threads_before = thread_stats(target_pid)
    started = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - started
    processes_after = same_uid_processes()
    target_threads_after = thread_stats(target_pid)
    if target_pid not in processes_after:
        raise RuntimeError(f"target process {target_pid} exited during sample")

    process_rows = delta_rows(processes_before, processes_after, elapsed, clock_ticks)
    thread_rows = delta_rows(
        target_threads_before, target_threads_after, elapsed, clock_ticks
    )
    status = parse_status(PROC_ROOT / str(target_pid) / "status")
    return {
        "sample_seconds": round(elapsed, 3),
        "target": {
            "pid": target_pid,
            "name": name,
            "cpu_percent": next(
                (row["cpu_percent"] for row in process_rows if row["pid"] == target_pid),
                None,
            ),
            "rss": status.get("VmRSS"),
            "threads": status.get("Threads"),
            "allowed_cpus": status.get("Cpus_allowed_list"),
        },
        "top_processes": process_rows[:top],
        "top_target_threads": thread_rows[:top],
        "cpu": cpu_snapshot(),
        "gpu": gpu_snapshot(),
        "thermal": thermal_snapshot(),
        "memory": memory_snapshot(),
    }


def print_human(report: dict[str, object]) -> None:
    target = report["target"]
    assert isinstance(target, dict)
    print(
        "TARGET"
        f" pid={target['pid']} name={target['name']} cpu={target['cpu_percent']}%"
        f" rss={target['rss']} threads={target['threads']}"
        f" allowed={target['allowed_cpus']} sample={report['sample_seconds']}s"
    )
    print("TOP_PROCESSES")
    for row in report["top_processes"]:
        print(
            f" pid={row['pid']} name={row['name']} cpu={row['cpu_percent']}%"
            f" last_cpu={row['processor']}"
        )
    print("TOP_TARGET_THREADS")
    for row in report["top_target_threads"]:
        print(
            f" tid={row['pid']} name={row['name']} cpu={row['cpu_percent']}%"
            f" last_cpu={row['processor']}"
        )
    gpu = report["gpu"]
    assert isinstance(gpu, dict)
    print(
        "GPU"
        f" busy={gpu['busy_percent']} current_hz={gpu['current_hz']}"
        f" policy_max_hz={gpu['policy_max_hz']}"
        f" thermal_pwrlevel={gpu['thermal_pwrlevel']}"
    )
    hottest = report["thermal"]
    print(
        "THERMAL"
        + "".join(
            f" {row['zone']}={int(row['millidegrees_c']) / 1000:.1f}C"
            for row in hottest[:4]
        )
    )
    print("MEMORY " + " ".join(f"{key}={value}" for key, value in report["memory"].items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="TombRaider.exe")
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    if not 0.5 <= arguments.seconds <= 10.0:
        parser.error("--seconds must be between 0.5 and 10")
    if not 1 <= arguments.top <= 50:
        parser.error("--top must be between 1 and 50")
    try:
        report = build_report(arguments.name, arguments.seconds, arguments.top)
    except RuntimeError as error:
        parser.error(str(error))
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
