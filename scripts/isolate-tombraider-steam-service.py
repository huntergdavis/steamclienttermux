#!/usr/bin/env python3

"""Temporarily isolate Steam's exact CServiceEng thread during Tomb Raider."""

import argparse
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


SERVICE_COMM = "IPC:CServiceEng"
TARGET_CPUS = "0"


class StopRequested(RuntimeError):
    pass


def load_affinity_tool(path):
    spec = importlib.util.spec_from_file_location("tombraider_affinity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_process_stat(text):
    closing = text.rfind(")")
    opening = text.find("(")
    fields = text[closing + 2 :].split() if closing > opening >= 0 else []
    if len(fields) <= 19:
        raise RuntimeError("malformed process stat record")
    try:
        return {
            "state": fields[0],
            "ppid": int(fields[1]),
            "start_ticks": int(fields[19]),
        }
    except ValueError as error:
        raise RuntimeError("malformed process stat values") from error


def process_record(entry):
    try:
        parsed = parse_process_stat((entry / "stat").read_text())
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError) as error:
        raise RuntimeError(f"cannot identify process {entry.name}") from error
    parsed["pid"] = int(entry.name)
    return parsed


def command_arguments(entry):
    try:
        return [item for item in (entry / "cmdline").read_bytes().split(b"\0") if item]
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return []


def find_exact_steam(affinity, steam_base, proc_root):
    expected = os.fsencode(steam_base / "client/steamrtarm64/steam")
    matches = []
    for entry in proc_root.iterdir():
        if entry.name.isdecimal() and affinity.command_targets(
            command_arguments(entry), expected, steam_base
        ):
            matches.append((int(entry.name), entry))
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact native Steam process, found {matches}")
    affinity.validate_top_app(matches[0][1])
    return matches[0]


def parse_cpu_list(value):
    cpus = set()
    for item in value.strip().split(","):
        if not item:
            raise RuntimeError(f"malformed CPU list: {value!r}")
        first, separator, last = item.partition("-")
        try:
            start = int(first)
            finish = int(last) if separator else start
        except ValueError as error:
            raise RuntimeError(f"malformed CPU list: {value!r}") from error
        if start < 0 or finish < start or finish > 255:
            raise RuntimeError(f"malformed CPU range: {item!r}")
        cpus.update(range(start, finish + 1))
    if not cpus:
        raise RuntimeError("CPU list is empty")
    return tuple(sorted(cpus))


def format_cpu_list(cpus):
    values = sorted(set(cpus))
    if not values:
        raise RuntimeError("CPU list is empty")
    ranges = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def allowed_cpu_list(status_text):
    rows = [
        line.split(":", 1)[1].strip()
        for line in status_text.splitlines()
        if line.startswith("Cpus_allowed_list:")
    ]
    if len(rows) != 1:
        raise RuntimeError("thread status has no unique Cpus_allowed_list")
    return format_cpu_list(parse_cpu_list(rows[0]))


def thread_record(entry):
    parsed = process_record(entry)
    try:
        parsed["comm"] = (entry / "comm").read_text().strip()
        parsed["cpus"] = allowed_cpu_list((entry / "status").read_text())
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError) as error:
        raise RuntimeError(f"cannot inspect thread {entry.name}") from error
    parsed["tid"] = parsed.pop("pid")
    return parsed


def find_exact_service_thread(steam_pid, proc_root):
    task_root = proc_root / str(steam_pid) / "task"
    matches = []
    try:
        entries = list(task_root.iterdir())
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError) as error:
        raise RuntimeError(f"cannot enumerate Steam threads for PID {steam_pid}") from error
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            if (entry / "comm").read_text().strip() == SERVICE_COMM:
                matches.append(thread_record(entry))
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one exact {SERVICE_COMM} Steam thread, found "
            f"{[record['tid'] for record in matches]}"
        )
    return matches[0]


def same_process(entry, expected):
    try:
        current = process_record(entry)
    except RuntimeError:
        return False
    return current["start_ticks"] == expected["start_ticks"]


def same_thread(entry, expected):
    try:
        current = thread_record(entry)
    except RuntimeError:
        return False
    return (
        current["start_ticks"] == expected["start_ticks"]
        and current["comm"] == SERVICE_COMM
    )


def set_thread_cpus(tid, cpus, runner=subprocess.run):
    completed = runner(
        ["taskset", "-pc", cpus, str(tid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"taskset failed for thread {tid}: {completed.stdout.strip()}"
        )


def game_identity_alive(affinity, steam_base, pid, start_ticks, proc_root):
    matches = dict(affinity.find_game_processes(proc_root, steam_base))
    entry = matches.get(pid)
    if entry is None:
        return False
    return process_record(entry)["start_ticks"] == start_ticks


def wait_for_game(affinity, steam_base, proc_root, timeout, monotonic=time.monotonic):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        matches = affinity.find_game_processes(proc_root, steam_base)
        if len(matches) > 1:
            raise RuntimeError(f"multiple exact Tomb Raider processes found: {matches}")
        if matches:
            pid, entry = matches[0]
            affinity.validate_top_app(entry)
            return pid, process_record(entry)["start_ticks"]
        time.sleep(0.25)
    raise RuntimeError("timed out waiting for exact Tomb Raider process")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steam-base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--wait-seconds", type=float, default=600)
    parser.add_argument("--isolation-timeout-seconds", type=float, default=300)
    parser.add_argument("--acknowledge-experimental", action="store_true")
    arguments = parser.parse_args()
    if not arguments.acknowledge_experimental:
        parser.error("--acknowledge-experimental is required")
    if not 1 <= arguments.wait_seconds <= 1800:
        parser.error("--wait-seconds must be from 1 through 1800")
    if not 1 <= arguments.isolation_timeout_seconds <= 900:
        parser.error("--isolation-timeout-seconds must be from 1 through 900")

    steam_base = Path(arguments.steam_base).resolve()
    proc_root = Path("/proc")
    affinity_path = Path(__file__).with_name("set-tombraider-affinity.py")
    steam_record = None
    service_record = None
    isolated = False
    return_code = 0

    def stop_requested(signum, _frame):
        raise StopRequested(f"received signal {signum}")

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_requested)

    try:
        affinity = load_affinity_tool(affinity_path)
        steam_pid, steam_entry = find_exact_steam(affinity, steam_base, proc_root)
        steam_record = process_record(steam_entry)
        game_pid, game_start = wait_for_game(
            affinity, steam_base, proc_root, arguments.wait_seconds
        )
        if not game_identity_alive(
            affinity, steam_base, game_pid, game_start, proc_root
        ):
            raise RuntimeError("game exited before Steam service isolation")
        service_record = find_exact_service_thread(steam_pid, proc_root)
        original_cpus = service_record["cpus"]
        if 0 not in parse_cpu_list(original_cpus):
            raise RuntimeError(
                f"target CPU 0 is outside original service mask {original_cpus}"
            )
        if original_cpus == TARGET_CPUS:
            raise RuntimeError("Steam service thread is already isolated on CPU 0")
        service_entry = proc_root / str(steam_pid) / "task" / str(service_record["tid"])
        set_thread_cpus(service_record["tid"], TARGET_CPUS)
        isolated = True
        current = thread_record(service_entry)
        if not same_thread(service_entry, service_record) or current["cpus"] != TARGET_CPUS:
            raise RuntimeError("Steam service thread did not enter the target CPU mask")
        print(
            "Steam service CPU isolation: active; "
            f"steam_pid={steam_pid}; tid={service_record['tid']}; "
            f"cpus={TARGET_CPUS}; original_cpus={original_cpus}",
            flush=True,
        )
        deadline = time.monotonic() + arguments.isolation_timeout_seconds
        while game_identity_alive(
            affinity, steam_base, game_pid, game_start, proc_root
        ):
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Steam service isolation timed out while game remained active"
                )
            if not same_process(proc_root / str(steam_pid), steam_record):
                raise RuntimeError("native Steam identity changed during isolation")
            if not same_thread(service_entry, service_record):
                raise RuntimeError("Steam service thread identity changed during isolation")
            if thread_record(service_entry)["cpus"] != TARGET_CPUS:
                raise RuntimeError("Steam service thread escaped the target CPU mask")
            time.sleep(0.25)
        print("Steam service CPU isolation: game exited", flush=True)
    except (OSError, RuntimeError, StopRequested) as error:
        print(f"isolate-tombraider-steam-service: {error}", file=sys.stderr)
        return_code = 2
    finally:
        if isolated and service_record is not None and steam_record is not None:
            service_entry = (
                proc_root
                / str(steam_record["pid"])
                / "task"
                / str(service_record["tid"])
            )
            try:
                if not same_thread(service_entry, service_record):
                    raise RuntimeError(
                        "cannot restore changed Steam service thread identity"
                    )
                set_thread_cpus(service_record["tid"], service_record["cpus"])
                restored = thread_record(service_entry)["cpus"]
                if restored != service_record["cpus"]:
                    raise RuntimeError(
                        f"restored CPU mask {restored} != {service_record['cpus']}"
                    )
                print(
                    "Steam service CPU isolation: restored; "
                    f"steam_pid={steam_record['pid']}; tid={service_record['tid']}; "
                    f"cpus={restored}",
                    flush=True,
                )
            except (OSError, RuntimeError) as error:
                print(
                    f"isolate-tombraider-steam-service: restore failed: {error}",
                    file=sys.stderr,
                )
                return_code = 2
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
