#!/usr/bin/env python3

"""Experimentally hold native Steam CEF during an excluded Tomb Raider run."""

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


def descends_from(pid, ancestor, proc_root):
    seen = set()
    current = pid
    for _ in range(32):
        if current == ancestor:
            return True
        if current <= 1 or current in seen:
            return False
        seen.add(current)
        try:
            current = process_record(proc_root / str(current))["ppid"]
        except RuntimeError:
            return False
    return False


def is_crashpad_handler(entry):
    arguments = command_arguments(entry)
    return (
        b"--type=crashpad-handler" in arguments
        and b"--monitor-self-annotation=ptype=crashpad-handler" in arguments
    )


def validated_helpers(affinity, steam_base, steam_pid, proc_root):
    helpers = affinity.find_steam_helpers(steam_base, proc_root)
    if not helpers:
        raise RuntimeError("no exact native Steam CEF helpers found")
    records = {}
    for pid, entry in helpers:
        affinity.validate_top_app(entry)
        if not descends_from(pid, steam_pid, proc_root):
            if is_crashpad_handler(entry):
                continue
            raise RuntimeError(f"Steam helper {pid} is not a descendant of {steam_pid}")
        records[pid] = process_record(entry)
    if not records:
        raise RuntimeError("no descendant native Steam CEF helpers found")
    return records


def same_identities(expected, current):
    return set(expected) == set(current) and all(
        expected[pid]["start_ticks"] == current[pid]["start_ticks"] for pid in expected
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


def resume_helpers(records, proc_root):
    resumed = []
    for pid, expected in records.items():
        try:
            current = process_record(proc_root / str(pid))
        except RuntimeError:
            continue
        if current["start_ticks"] != expected["start_ticks"]:
            continue
        os.kill(pid, signal.SIGCONT)
        resumed.append(pid)
    return resumed


def pending_stopped_helpers(records, proc_root):
    pending = []
    for pid, expected in records.items():
        try:
            current = process_record(proc_root / str(pid))
        except RuntimeError:
            continue
        if (
            current["start_ticks"] == expected["start_ticks"]
            and current["state"] == "T"
        ):
            pending.append(pid)
    return pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steam-base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--wait-seconds", type=float, default=600)
    parser.add_argument("--delay-seconds", type=float, default=25)
    parser.add_argument("--hold-timeout-seconds", type=float, default=300)
    parser.add_argument("--acknowledge-experimental", action="store_true")
    arguments = parser.parse_args()
    if not arguments.acknowledge_experimental:
        parser.error("--acknowledge-experimental is required")
    if not 0 <= arguments.delay_seconds <= 60:
        parser.error("--delay-seconds must be from 0 through 60")
    if not 1 <= arguments.wait_seconds <= 1800:
        parser.error("--wait-seconds must be from 1 through 1800")
    if not 1 <= arguments.hold_timeout_seconds <= 900:
        parser.error("--hold-timeout-seconds must be from 1 through 900")

    steam_base = Path(arguments.steam_base).resolve()
    proc_root = Path("/proc")
    affinity_path = Path(__file__).with_name("set-tombraider-affinity.py")
    held = {}

    def stop_requested(signum, _frame):
        raise StopRequested(f"received signal {signum}")

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop_requested)

    try:
        affinity = load_affinity_tool(affinity_path)
        steam_pid, _steam_entry = find_exact_steam(affinity, steam_base, proc_root)
        game_pid, game_start = wait_for_game(
            affinity, steam_base, proc_root, arguments.wait_seconds
        )
        time.sleep(arguments.delay_seconds)
        if not game_identity_alive(
            affinity, steam_base, game_pid, game_start, proc_root
        ):
            raise RuntimeError("game exited before CEF hold")
        held = validated_helpers(affinity, steam_base, steam_pid, proc_root)
        for pid in held:
            os.kill(pid, signal.SIGSTOP)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = validated_helpers(affinity, steam_base, steam_pid, proc_root)
            if same_identities(held, current) and all(
                record["state"] == "T" for record in current.values()
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("native Steam CEF helpers did not enter stopped state")
        print(
            "Steam CEF experimental hold: active; "
            + ",".join(str(pid) for pid in sorted(held)),
            flush=True,
        )
        hold_deadline = time.monotonic() + arguments.hold_timeout_seconds
        while game_identity_alive(
            affinity, steam_base, game_pid, game_start, proc_root
        ):
            if time.monotonic() >= hold_deadline:
                raise RuntimeError("CEF hold timed out while game remained active")
            current = validated_helpers(affinity, steam_base, steam_pid, proc_root)
            if not same_identities(held, current):
                raise RuntimeError("Steam CEF helper set changed during hold")
            if any(record["state"] != "T" for record in current.values()):
                raise RuntimeError("Steam CEF helper resumed during hold")
            time.sleep(0.25)
        print("Steam CEF experimental hold: game exited", flush=True)
    except (OSError, RuntimeError, StopRequested) as error:
        print(f"hold-tombraider-steam-cef: {error}", file=sys.stderr)
        return_code = 2
    else:
        return_code = 0
    finally:
        try:
            resumed = resume_helpers(held, proc_root)
            deadline = time.monotonic() + 5
            pending = pending_stopped_helpers(held, proc_root)
            while pending and time.monotonic() < deadline:
                time.sleep(0.1)
                pending = pending_stopped_helpers(held, proc_root)
            if pending:
                raise RuntimeError(f"CEF helpers remained stopped after resume: {pending}")
        except (OSError, RuntimeError) as error:
            print(f"hold-tombraider-steam-cef: resume failed: {error}", file=sys.stderr)
            resumed = []
            return_code = 2
        if held:
            print(
                "Steam CEF experimental hold: resumed "
                + ",".join(str(pid) for pid in sorted(resumed)),
                flush=True,
            )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
