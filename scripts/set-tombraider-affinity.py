#!/usr/bin/env python3

"""Apply the comparison-matched Tab S8+ Tomb Raider CPU affinity."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


APP_ID = b"203160"
GAME_COMM = "TombRaider.exe"
TARGET_CPUS = "1-7"
RAKNET_COMM = "Raknet-RecvFrom"
RAKNET_CPU = "1"


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


def read_threads(process_dir):
    threads = {}
    for status in (process_dir / "task").glob("[0-9]*/status"):
        try:
            contents = status.read_text()
            comm = (status.parent / "comm").read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        match = re.search(r"^Cpus_allowed_list:\s*(\S+)\s*$", contents, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing Cpus_allowed_list in {status}")
        threads[int(status.parent.name)] = (comm, match.group(1))
    if not threads:
        raise RuntimeError(f"no readable threads under {process_dir / 'task'}")
    return threads


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


def validate_tab_s8_plus_layout(layout):
    if set(layout) != set(range(8)):
        raise RuntimeError(f"expected CPU IDs 0-7, found {sorted(layout)}")
    efficiency = [layout[cpu] for cpu in range(4)]
    performance = [layout[cpu] for cpu in range(4, 8)]
    if min(capacity for capacity, _maximum in performance) <= max(
        capacity for capacity, _maximum in efficiency
    ):
        raise RuntimeError("CPUs 4-7 are not a distinct higher-capacity cluster")
    if layout[7][0] != max(capacity for capacity, _maximum in layout.values()):
        raise RuntimeError("CPU 7 is not the measured prime core")


def run_taskset(arguments, runner=subprocess.run):
    return runner(arguments, check=True, text=True, capture_output=True)


def expected_mask(comm, isolate_raknet):
    if isolate_raknet and comm == RAKNET_COMM:
        return RAKNET_CPU
    return TARGET_CPUS


def verify_threads(threads, isolate_raknet):
    if isolate_raknet:
        raknet = [tid for tid, (comm, _mask) in threads.items() if comm == RAKNET_COMM]
        if len(raknet) != 1:
            raise RuntimeError(
                f"expected exactly one {RAKNET_COMM} thread, found {len(raknet)}"
            )
    wrong = {
        tid: (comm, mask, expected_mask(comm, isolate_raknet))
        for tid, (comm, mask) in threads.items()
        if mask != expected_mask(comm, isolate_raknet)
    }
    if wrong:
        raise RuntimeError(f"threads retain unexpected masks: {wrong}")


def apply_affinity(pid, process_dir, isolate_raknet, runner=subprocess.run):
    results = [run_taskset(["taskset", "-apc", TARGET_CPUS, str(pid)], runner)]
    if isolate_raknet:
        threads = read_threads(process_dir)
        raknet = [tid for tid, (comm, _mask) in threads.items() if comm == RAKNET_COMM]
        if len(raknet) != 1:
            raise RuntimeError(
                f"expected exactly one {RAKNET_COMM} thread, found {len(raknet)}"
            )
        results.append(
            run_taskset(["taskset", "-pc", RAKNET_CPU, str(raknet[0])], runner)
        )
    return results


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--raknet-cpu1",
        action="store_true",
        help="add the separately measured busy-loop isolation",
    )
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sys-cpu-root", default="/sys/devices/system/cpu", help=argparse.SUPPRESS
    )
    return parser


def main():
    arguments = build_parser().parse_args()
    try:
        layout = read_cpu_layout(Path(arguments.sys_cpu_root))
        validate_tab_s8_plus_layout(layout)
        matches = find_game_processes(Path(arguments.proc_root))
        if len(matches) != 1:
            raise RuntimeError(
                "expected exactly one verified App ID 203160 Tomb Raider process, "
                f"found {len(matches)}"
            )
        pid, process_dir = matches[0]
        before = read_threads(process_dir)
        print(f"Tomb Raider PID {pid}: {len(before)} threads")
        if arguments.check:
            verify_threads(before, arguments.raknet_cpu1)
            print("Tomb Raider affinity: verified")
            return 0
        for result in apply_affinity(
            pid, process_dir, arguments.raknet_cpu1
        ):
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        after = read_threads(process_dir)
        verify_threads(after, arguments.raknet_cpu1)
        suffix = "; RakNet on CPU 1" if arguments.raknet_cpu1 else ""
        print(f"Tomb Raider: all {len(after)} threads use CPUs 1-7{suffix}")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"set-tombraider-affinity: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
