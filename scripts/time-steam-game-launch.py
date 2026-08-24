#!/usr/bin/env python3
"""Measure Steam-to-game launch stages without entering PRoot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


LOG_TIME = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
DXVK_MILESTONES = (
    ("dxvk_state_cache", "Found cache file:"),
    ("dxvk_swapchain", "Presenter: Actual swapchain properties:"),
    ("dxvk_compiler", "DXVK: Using "),
)
GAME_MODULE_MILESTONES = (
    ("module_winevulkan", "winevulkan.dll"),
    ("module_dxgi", "dxgi.dll"),
    ("module_d3d11", "d3d11.dll"),
    ("module_turnip", "libvulkan_freedreno.so"),
)


@dataclass(frozen=True)
class Process:
    pid: int
    name: str
    executable: str
    arguments: tuple[str, ...]


class LogFollower:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.offset = path.stat().st_size
        except FileNotFoundError:
            self.offset = 0

    def read(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return []
        if size < self.offset:
            self.offset = 0
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.offset)
            text = handle.read()
            self.offset = handle.tell()
        return text.splitlines()


class DxvkMilestoneFollower:
    """Follow only DXVK log directories created after this timer starts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        try:
            self.known_directories = {
                path for path in root.glob("dxvk-direct-*") if path.is_dir()
            }
        except OSError:
            self.known_directories = set()
        self.active_directories: set[Path] = set()
        self.followers: dict[Path, LogFollower] = {}

    def read(self) -> list[tuple[str, Path, str]]:
        try:
            directories = sorted(
                path for path in self.root.glob("dxvk-direct-*") if path.is_dir()
            )
        except OSError:
            return []
        for directory in directories:
            if directory in self.known_directories:
                continue
            self.known_directories.add(directory)
            self.active_directories.add(directory)
        for directory in sorted(self.active_directories):
            try:
                logs = sorted(directory.glob("*.log"))
            except OSError:
                continue
            for path in logs:
                if path in self.followers:
                    continue
                follower = LogFollower(path)
                # New logs must be consumed from byte zero. LogFollower's
                # normal behavior deliberately starts at the current end.
                follower.offset = 0
                self.followers[path] = follower

        records = []
        for path, follower in sorted(self.followers.items()):
            for line in follower.read():
                for event, marker in DXVK_MILESTONES:
                    if marker in line:
                        records.append((event, path, line.strip()))
        return records


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def parse_log_time(line: str) -> datetime | None:
    match = LOG_TIME.match(line)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def process_snapshot(proc_root: Path = Path("/proc")) -> list[Process]:
    result = []
    for directory in proc_root.iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            name = (directory / "comm").read_text().strip()
            raw = (directory / "cmdline").read_bytes()
            executable = os.readlink(directory / "exe")
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        arguments = tuple(
            item.decode("utf-8", errors="replace")
            for item in raw.split(b"\0")
            if item
        )
        result.append(Process(int(directory.name), name, executable, arguments))
    return result


def path_basename(value: str) -> str:
    return re.split(r"[\\/]", value)[-1]


def stage_processes(processes: list[Process], target_name: str) -> dict[str, Process]:
    stages = {}
    for process in processes:
        argument_zero = process.arguments[0] if process.arguments else ""
        command_name = path_basename(argument_zero)
        if "pressure_vessel" not in stages and (
            process.name == "pressure-vessel-wrap" or command_name == "pressure-vessel-wrap"
        ):
            stages["pressure_vessel"] = process
        if (
            "proton" not in stages
            and process.name.startswith("python")
            and any(argument.endswith("/proton") for argument in process.arguments)
        ):
            stages["proton"] = process
        if "wine" not in stages and (process.name == "wine" or command_name == "wine"):
            stages["wine"] = process
        if "wineserver" not in stages and (
            process.name == "wineserver" or command_name == "wineserver"
        ):
            stages["wineserver"] = process
        if "target_process" not in stages and (
            process.name == target_name or command_name.casefold() == target_name.casefold()
        ):
            stages["target_process"] = process
    return stages


def mapped_module_events(proc_root: Path, pid: int) -> dict[str, str]:
    """Return graphics modules currently mapped by one verified game PID."""

    try:
        lines = (proc_root / str(pid) / "maps").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return {}
    result = {}
    for line in lines:
        folded = line.casefold()
        for event, module in GAME_MODULE_MILESTONES:
            if event not in result and module in folded:
                fields = line.split(maxsplit=5)
                result[event] = fields[5] if len(fields) == 6 else module
    return result


def process_metrics(proc_root: Path, pid: int) -> dict[str, int | float]:
    """Read bounded cumulative CPU and I/O counters for one process."""

    try:
        stat_text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
        fields = stat_text.rsplit(") ", maxsplit=1)[1].split()
        user_ticks = int(fields[11])
        system_ticks = int(fields[12])
        threads = int(fields[17])
        io_values = {}
        for line in (proc_root / str(pid) / "io").read_text(
            encoding="utf-8"
        ).splitlines():
            key, separator, value = line.partition(":")
            if separator and value.strip().isdecimal():
                io_values[key] = int(value.strip())
        ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
    except (
        FileNotFoundError,
        PermissionError,
        ProcessLookupError,
        OSError,
        IndexError,
        ValueError,
    ):
        return {}
    return {
        "cpu_user_seconds": round(user_ticks / ticks_per_second, 3),
        "cpu_system_seconds": round(system_ticks / ticks_per_second, 3),
        "threads": threads,
        "rchar_bytes": io_values.get("rchar", 0),
        "read_syscalls": io_values.get("syscr", 0),
        "storage_read_bytes": io_values.get("read_bytes", 0),
    }


def first_visible_window(display: str, pattern: str, timeout: float) -> str | None:
    environment = os.environ.copy()
    environment["DISPLAY"] = display
    try:
        completed = subprocess.run(
            [
                "xdotool",
                "search",
                "--onlyvisible",
                "--name",
                pattern,
                "getwindowname",
                "%@",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in completed.stdout.splitlines():
        if line.strip():
            return line.strip()
    return None


def event_record(observed: datetime, anchor: datetime, **values: object) -> dict[str, object]:
    return {
        "observed_at": iso_time(observed),
        "seconds_after_runtime_launch": round((observed - anchor).total_seconds(), 3),
        **values,
    }


def update_window_stability(
    first_seen: datetime | None,
    first_title: str | None,
    observed: datetime,
    target_present: bool,
    title: str | None,
    required_seconds: float,
) -> tuple[datetime | None, str | None, bool]:
    if not target_present or title is None:
        return None, None, False
    if first_seen is None:
        return observed, title, False
    return (
        first_seen,
        first_title,
        (observed - first_seen).total_seconds() >= required_seconds,
    )


def attempt_record(
    number: int,
    status: str,
    session_start: datetime | None,
    runtime_launch: datetime | None,
    events: dict[str, dict[str, object]],
) -> dict[str, object]:
    return {
        "attempt": number,
        "status": status,
        "steam_session_at": iso_time(session_start) if session_start else None,
        "runtime_launch_at": iso_time(runtime_launch) if runtime_launch else None,
        "seconds_session_to_runtime_launch": (
            round((runtime_launch - session_start).total_seconds(), 3)
            if session_start and runtime_launch
            else None
        ),
        "events": dict(events),
    }


def atomic_json(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def measure(arguments: argparse.Namespace) -> tuple[int, dict[str, object]]:
    console = LogFollower(arguments.console_log)
    compat = LogFollower(arguments.compat_log)
    dxvk = (
        DxvkMilestoneFollower(arguments.dxvk_log_root)
        if arguments.dxvk_log_root is not None
        else None
    )
    started = utc_now()
    deadline = time.monotonic() + arguments.timeout
    runtime_launch = None
    session_start = None
    session_marker = None
    events: dict[str, dict[str, object]] = {}
    attempts: list[dict[str, object]] = []
    status = "timeout"
    window_first_seen = None
    window_first_title = None

    while time.monotonic() < deadline:
        for line in compat.read():
            if f"StartSession: appID {arguments.appid} " not in line:
                continue
            observed_session = parse_log_time(line) or utc_now()
            if session_marker is not None and line != session_marker:
                attempts.append(
                    attempt_record(
                        len(attempts) + 1,
                        "superseded_by_retry",
                        session_start,
                        runtime_launch,
                        events,
                    )
                )
                runtime_launch = None
                events = {}
                window_first_seen = None
                window_first_title = None
            session_start = observed_session
            session_marker = line
        for line in console.read():
            if (
                runtime_launch is None
                and f"Game process added : AppID {arguments.appid} " in line
            ):
                runtime_launch = parse_log_time(line) or utc_now()

        if runtime_launch is not None:
            observed = utc_now()
            current_stages = stage_processes(
                process_snapshot(arguments.proc_root), arguments.process_name
            )
            for stage, process in current_stages.items():
                if stage not in events:
                    metrics = (
                        process_metrics(arguments.proc_root, process.pid)
                        if stage == "target_process"
                        else {}
                    )
                    events[stage] = event_record(
                        observed,
                        runtime_launch,
                        pid=process.pid,
                        process_name=process.name,
                        executable=process.executable,
                        **({"metrics": metrics} if metrics else {}),
                    )
            target = current_stages.get("target_process")
            if target is not None:
                for stage, module_path in mapped_module_events(
                    arguments.proc_root, target.pid
                ).items():
                    if stage not in events:
                        metrics = process_metrics(arguments.proc_root, target.pid)
                        events[stage] = event_record(
                            utc_now(),
                            runtime_launch,
                            pid=target.pid,
                            module=module_path,
                            **({"metrics": metrics} if metrics else {}),
                        )
            if dxvk is not None:
                for stage, path, line in dxvk.read():
                    if stage not in events:
                        metrics = (
                            process_metrics(arguments.proc_root, target.pid)
                            if target is not None
                            else {}
                        )
                        events[stage] = event_record(
                            utc_now(),
                            runtime_launch,
                            log=str(path),
                            marker=line,
                            **({"metrics": metrics} if metrics else {}),
                        )
            title = None
            if "target_process" in current_stages:
                title = first_visible_window(
                    arguments.display,
                    arguments.window_regex,
                    min(5.0, max(0.25, arguments.poll)),
                )
            observed = utc_now()
            window_first_seen, window_first_title, window_stable = (
                update_window_stability(
                    window_first_seen,
                    window_first_title,
                    observed,
                    "target_process" in current_stages,
                    title,
                    arguments.window_stable_seconds,
                )
            )
            if window_stable:
                metrics = (
                    process_metrics(arguments.proc_root, target.pid)
                    if target is not None
                    else {}
                )
                events["game_window"] = event_record(
                    window_first_seen,
                    runtime_launch,
                    title=window_first_title,
                    stable_seconds=arguments.window_stable_seconds,
                    **(
                        {
                            "metrics_at_stability_confirmation": metrics,
                            "metrics_observed_at": iso_time(utc_now()),
                        }
                        if metrics
                        else {}
                    ),
                )
                status = "complete"
                break
        time.sleep(arguments.poll)

    finished = utc_now()
    if session_start is not None or runtime_launch is not None or events:
        attempts.append(
            attempt_record(
                len(attempts) + 1,
                status,
                session_start,
                runtime_launch,
                events,
            )
        )
    report: dict[str, object] = {
        "schema_version": 2,
        "status": status,
        "appid": arguments.appid,
        "process_name": arguments.process_name,
        "window_regex": arguments.window_regex,
        "display": arguments.display,
        "dxvk_log_root": (
            str(arguments.dxvk_log_root)
            if arguments.dxvk_log_root is not None
            else None
        ),
        "poll_seconds": arguments.poll,
        "window_stable_seconds": arguments.window_stable_seconds,
        "timer_started_at": iso_time(started),
        "timer_finished_at": iso_time(finished),
        "steam_session_at": iso_time(session_start) if session_start else None,
        "runtime_launch_at": iso_time(runtime_launch) if runtime_launch else None,
        "seconds_session_to_runtime_launch": (
            round((runtime_launch - session_start).total_seconds(), 3)
            if session_start and runtime_launch
            else None
        ),
        "events": events,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "notes": (
            "Steam log timestamps have one-second resolution. Process events are "
            "first observations at the configured polling interval. "
            "A game window is complete only after the target and matching visible "
            "window remain continuously present for window_stable_seconds. "
            "Optional DXVK milestones are external first-observation times and "
            "do not instrument the game process. Graphics-module events are "
            "external observations of the verified target PID's proc maps. "
            "Cumulative target metrics come from proc stat/io; game-window "
            "metrics are sampled at stability confirmation, not first sighting. "
            "A later StartSession for the same AppID closes the incomplete attempt "
            "and resets process/window attribution for the retry."
        ),
    }
    return (0 if status == "complete" else 3), report


def main() -> int:
    base = Path(os.environ.get("STEAM_ARM64_BASE", Path.home() / "steam-arm64"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(
        description="Start this timer immediately before clicking Play in Steam."
    )
    parser.add_argument("--appid", required=True, type=int)
    parser.add_argument("--process-name", required=True)
    parser.add_argument("--window-regex", required=True)
    parser.add_argument("--display", default=":0")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--window-stable-seconds", type=float, default=30.0)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument(
        "--dxvk-log-root",
        type=Path,
        help="watch new dxvk-direct-* directories for startup milestones",
    )
    parser.add_argument(
        "--console-log", type=Path, default=base / "client/logs/console_log.txt"
    )
    parser.add_argument(
        "--compat-log", type=Path, default=base / "client/logs/compat_log.txt"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base / f"logs/launch-timing-{stamp}.json",
    )
    arguments = parser.parse_args()
    if arguments.appid <= 0:
        parser.error("--appid must be positive")
    if not 0.25 <= arguments.poll <= 10.0:
        parser.error("--poll must be between 0.25 and 10 seconds")
    if not 1.0 <= arguments.timeout <= 3600.0:
        parser.error("--timeout must be between 1 and 3600 seconds")
    if not 1.0 <= arguments.window_stable_seconds <= 120.0:
        parser.error("--window-stable-seconds must be between 1 and 120 seconds")
    if not arguments.process_name or not arguments.window_regex:
        parser.error("process and window names must not be empty")

    result, report = measure(arguments)
    atomic_json(arguments.output, report)
    print(arguments.output)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
