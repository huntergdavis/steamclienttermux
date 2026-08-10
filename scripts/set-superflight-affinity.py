#!/usr/bin/env python3

"""Validate or apply the confirmed Tab S9+ Superflight CPU affinity."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


APP_ID = b"732430"
GAME_COMM = "superflight.exe"
TARGET_CPUS = "4-7"


def parse_environment(data):
    environment = {}
    for item in data.split(b"\0"):
        key, separator, value = item.partition(b"=")
        if separator:
            environment[key] = value
    return environment


def validate_environment(environment):
    if environment.get(b"STEAM_COMPAT_APP_ID") != APP_ID:
        return False
    for key in (b"SteamAppId", b"SteamGameId"):
        if key in environment and environment[key] != APP_ID:
            return False
    compatdata = environment.get(b"STEAM_COMPAT_DATA_PATH", b"").rstrip(b"/")
    return compatdata.endswith(b"/steamapps/compatdata/" + APP_ID)


def find_game_processes(proc_root=Path("/proc")):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            if comm != GAME_COMM:
                continue
            environment = parse_environment((entry / "environ").read_bytes())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if validate_environment(environment):
            matches.append((int(entry.name), entry))
    return sorted(matches)


def read_thread_masks(process_dir):
    masks = {}
    for status in (process_dir / "task").glob("[0-9]*/status"):
        try:
            contents = status.read_text()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        match = re.search(r"^Cpus_allowed_list:\s*(\S+)\s*$", contents, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing Cpus_allowed_list in {status}")
        masks[int(status.parent.name)] = match.group(1)
    if not masks:
        raise RuntimeError(f"no readable threads under {process_dir / 'task'}")
    return masks


def read_cpu_layout(sys_cpu_root=Path("/sys/devices/system/cpu")):
    layout = {}
    for cpu in sys_cpu_root.glob("cpu[0-9]*"):
        match = re.fullmatch(r"cpu([0-9]+)", cpu.name)
        if not match:
            continue
        try:
            capacity = int((cpu / "cpu_capacity").read_text().strip())
            maximum = int((cpu / "cpufreq/cpuinfo_max_freq").read_text().strip())
        except (FileNotFoundError, PermissionError, ValueError):
            continue
        layout[int(match.group(1))] = (capacity, maximum)
    return layout


def validate_tab_s9_plus_layout(layout):
    if set(layout) != set(range(8)):
        raise RuntimeError(f"expected CPU IDs 0-7, found {sorted(layout)}")
    efficiency = [layout[cpu] for cpu in range(4)]
    performance = [layout[cpu] for cpu in range(4, 8)]
    if min(capacity for capacity, _maximum in performance) <= max(
        capacity for capacity, _maximum in efficiency
    ):
        raise RuntimeError("CPUs 4-7 are not a distinct higher-capacity cluster")


def apply_affinity(pid, runner=subprocess.run):
    return runner(
        ["taskset", "-apc", TARGET_CPUS, str(pid)],
        check=True,
        text=True,
        capture_output=True,
    )


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="report current masks without changing them",
    )
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sys-cpu-root", default="/sys/devices/system/cpu", help=argparse.SUPPRESS
    )
    return parser


def main():
    args = build_parser().parse_args()
    try:
        layout = read_cpu_layout(Path(args.sys_cpu_root))
        validate_tab_s9_plus_layout(layout)
        matches = find_game_processes(Path(args.proc_root))
        if len(matches) != 1:
            raise RuntimeError(
                "expected exactly one verified App ID 732430 Superflight process, "
                f"found {len(matches)}"
            )
        pid, process_dir = matches[0]
        before = read_thread_masks(process_dir)
        before_values = sorted(set(before.values()))
        print(f"Superflight PID {pid}: {len(before)} threads; masks {before_values}")
        if args.check:
            return 0 if before_values == [TARGET_CPUS] else 1

        result = apply_affinity(pid)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        after = read_thread_masks(process_dir)
        wrong = {thread: mask for thread, mask in after.items() if mask != TARGET_CPUS}
        if wrong:
            raise RuntimeError(f"threads retain unexpected masks after taskset: {wrong}")
        print(f"Superflight PID {pid}: all {len(after)} threads use CPUs {TARGET_CPUS}")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"set-superflight-affinity: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
