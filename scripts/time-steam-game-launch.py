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
    started = utc_now()
    deadline = time.monotonic() + arguments.timeout
    runtime_launch = None
    session_start = None
    session_marker = None
    events: dict[str, dict[str, object]] = {}
    attempts: list[dict[str, object]] = []
    status = "timeout"

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
            for stage, process in stage_processes(
                process_snapshot(arguments.proc_root), arguments.process_name
            ).items():
                if stage not in events:
                    events[stage] = event_record(
                        observed,
                        runtime_launch,
                        pid=process.pid,
                        process_name=process.name,
                        executable=process.executable,
                    )
            if "target_process" in events and "game_window" not in events:
                title = first_visible_window(
                    arguments.display,
                    arguments.window_regex,
                    min(5.0, max(0.25, arguments.poll)),
                )
                if title is not None:
                    observed = utc_now()
                    events["game_window"] = event_record(
                        observed, runtime_launch, title=title
                    )
            if "target_process" in events and "game_window" in events:
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
        "poll_seconds": arguments.poll,
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
            "Steam log timestamps have one-second resolution. Process and window "
            "events are first observations at the configured polling interval. "
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
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
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
    if not arguments.process_name or not arguments.window_regex:
        parser.error("process and window names must not be empty")

    result, report = measure(arguments)
    atomic_json(arguments.output, report)
    print(arguments.output)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
