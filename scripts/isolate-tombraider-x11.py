#!/usr/bin/env python3

"""Experimentally isolate the exact Termux:X11 process while Tomb Raider runs."""

import argparse
import importlib.util
import os
from pathlib import Path
import signal
import sys
import time


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
    if len(fields) <= 36:
        raise RuntimeError("malformed process stat record")
    try:
        return {
            "state": fields[0],
            "ppid": int(fields[1]),
            "start_ticks": int(fields[19]),
            "processor": int(fields[36]),
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


def is_exact_x11(entry, display):
    arguments = command_arguments(entry)
    return (
        len(arguments) >= 3
        and Path(os.fsdecode(arguments[0])).name == "termux-x11"
        and arguments[1] == b"com.termux.x11"
        and arguments[2] == os.fsencode(display)
    )


def find_exact_x11(affinity, proc_root, display):
    matches = []
    for entry in proc_root.iterdir():
        if entry.name.isdecimal() and is_exact_x11(entry, display):
            matches.append((int(entry.name), entry))
    if len(matches) != 1:
        raise RuntimeError(f"expected one exact Termux:X11 process, found {matches}")
    affinity.validate_top_app(matches[0][1])
    return matches[0]


def thread_entries(process_entry):
    try:
        entries = [
            entry
            for entry in (process_entry / "task").iterdir()
            if entry.name.isdecimal()
        ]
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError) as error:
        raise RuntimeError(f"cannot enumerate X11 threads for {process_entry.name}") from error
    if not entries:
        raise RuntimeError(f"X11 process {process_entry.name} has no threads")
    return sorted(entries, key=lambda entry: int(entry.name))


def capture_and_isolate_threads(process_entry, records, cpu, get_affinity, set_affinity):
    current = []
    for entry in thread_entries(process_entry):
        tid = int(entry.name)
        record = process_record(entry)
        previous = records.get(tid)
        if previous is not None and previous["start_ticks"] != record["start_ticks"]:
            raise RuntimeError(f"X11 thread identity changed for TID {tid}")
        if previous is None:
            records[tid] = {
                "start_ticks": record["start_ticks"],
                "affinity": frozenset(get_affinity(tid)),
            }
            if not records[tid]["affinity"]:
                raise RuntimeError(f"X11 thread {tid} has an empty original affinity")
        set_affinity(tid, {cpu})
        if set(get_affinity(tid)) != {cpu}:
            raise RuntimeError(f"X11 thread {tid} did not converge to CPU {cpu}")
        current.append(tid)
    return current


def restore_threads(process_entry, process_start, records, get_affinity, set_affinity):
    try:
        if process_record(process_entry)["start_ticks"] != process_start:
            return []
    except RuntimeError:
        return []
    restored = []
    for tid, expected in sorted(records.items()):
        entry = process_entry / "task" / str(tid)
        try:
            current = process_record(entry)
        except RuntimeError:
            if entry.exists():
                raise
            continue
        if current["start_ticks"] != expected["start_ticks"]:
            continue
        try:
            set_affinity(tid, set(expected["affinity"]))
            if set(get_affinity(tid)) != set(expected["affinity"]):
                raise RuntimeError(
                    f"X11 thread {tid} did not restore its original affinity"
                )
        except ProcessLookupError:
            continue
        restored.append(tid)
    return restored


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
    parser.add_argument("--display", default=":0")
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--wait-seconds", type=float, default=600)
    parser.add_argument("--delay-seconds", type=float, default=25)
    parser.add_argument("--isolation-timeout-seconds", type=float, default=300)
    parser.add_argument("--acknowledge-experimental", action="store_true")
    arguments = parser.parse_args()
    if not arguments.acknowledge_experimental:
        parser.error("--acknowledge-experimental is required")
    if not 0 <= arguments.cpu <= 7:
        parser.error("--cpu must be from 0 through 7")
    if not 0 <= arguments.delay_seconds <= 60:
        parser.error("--delay-seconds must be from 0 through 60")
    if not 1 <= arguments.wait_seconds <= 1800:
        parser.error("--wait-seconds must be from 1 through 1800")
    if not 1 <= arguments.isolation_timeout_seconds <= 900:
        parser.error("--isolation-timeout-seconds must be from 1 through 900")

    steam_base = Path(arguments.steam_base).resolve()
    proc_root = Path("/proc")
    affinity = load_affinity_tool(Path(__file__).with_name("set-tombraider-affinity.py"))
    records = {}
    x11_entry = None
    x11_start = None
    return_code = 0

    def stop_requested(signum, _frame):
        raise StopRequested(f"received signal {signum}")

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_requested)

    try:
        _x11_pid, x11_entry = find_exact_x11(affinity, proc_root, arguments.display)
        x11_start = process_record(x11_entry)["start_ticks"]
        game_pid, game_start = wait_for_game(
            affinity, steam_base, proc_root, arguments.wait_seconds
        )
        time.sleep(arguments.delay_seconds)
        if not game_identity_alive(affinity, steam_base, game_pid, game_start, proc_root):
            raise RuntimeError("game exited before X11 isolation")
        current_pid, current_entry = find_exact_x11(affinity, proc_root, arguments.display)
        if (
            current_entry != x11_entry
            or process_record(current_entry)["start_ticks"] != x11_start
        ):
            raise RuntimeError("Termux:X11 identity changed before isolation")
        tids = capture_and_isolate_threads(
            x11_entry,
            records,
            arguments.cpu,
            os.sched_getaffinity,
            os.sched_setaffinity,
        )
        print(
            f"Termux X11 experimental isolation: active; pid={current_pid}; "
            f"cpu={arguments.cpu}; tids=" + ",".join(str(tid) for tid in tids),
            flush=True,
        )
        deadline = time.monotonic() + arguments.isolation_timeout_seconds
        while game_identity_alive(affinity, steam_base, game_pid, game_start, proc_root):
            if time.monotonic() >= deadline:
                raise RuntimeError("X11 isolation timed out while game remained active")
            current_pid, current_entry = find_exact_x11(
                affinity, proc_root, arguments.display
            )
            if (
                current_entry != x11_entry
                or process_record(current_entry)["start_ticks"] != x11_start
            ):
                raise RuntimeError("Termux:X11 identity changed during isolation")
            capture_and_isolate_threads(
                x11_entry,
                records,
                arguments.cpu,
                os.sched_getaffinity,
                os.sched_setaffinity,
            )
            time.sleep(0.25)
        print("Termux X11 experimental isolation: game exited", flush=True)
    except (OSError, RuntimeError, StopRequested) as error:
        print(f"isolate-tombraider-x11: {error}", file=sys.stderr)
        return_code = 2
    finally:
        try:
            restored = (
                restore_threads(
                    x11_entry,
                    x11_start,
                    records,
                    os.sched_getaffinity,
                    os.sched_setaffinity,
                )
                if x11_entry is not None and x11_start is not None
                else []
            )
        except (OSError, RuntimeError) as error:
            print(f"isolate-tombraider-x11: restore failed: {error}", file=sys.stderr)
            restored = []
            return_code = 2
        if records:
            print(
                "Termux X11 experimental isolation: restored; tids="
                + ",".join(str(tid) for tid in restored),
                flush=True,
            )
            if restored != sorted(records):
                print(
                    "isolate-tombraider-x11: not every isolated thread survived for restore",
                    file=sys.stderr,
                )
                return_code = 2
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
