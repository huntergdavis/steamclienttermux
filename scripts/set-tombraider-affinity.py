#!/usr/bin/env python3

"""Apply the comparison-matched Tab S8+ Tomb Raider CPU affinity."""

import argparse
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import time


APP_ID = b"203160"
GAME_COMM = "TombRaider.exe"
TARGET_CPUS = "1-7"
RAKNET_COMM = "Raknet-RecvFrom"
RAKNET_CPU = "1"
STEAM_HELPER_CPUS = "0"
AUXILIARY_CPUS = TARGET_CPUS
AUXILIARY_COMMS = {"wineserver", "explorer.exe"}


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


def read_cgroup_class(process_dir, controller):
    try:
        contents = (process_dir / "cgroup").read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError) as error:
        raise RuntimeError(f"unable to read cgroups for {process_dir}") from error
    for line in contents.splitlines():
        _hierarchy, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, path = remainder.partition(":")
        if separator and controller in controllers.split(","):
            return path
    raise RuntimeError(f"missing {controller} cgroup for {process_dir}")


def validate_top_app(process_dir):
    placements = {
        controller: read_cgroup_class(process_dir, controller)
        for controller in ("cpuset", "cpu")
    }
    wrong = {
        controller: path
        for controller, path in placements.items()
        if path != "/top-app"
    }
    if wrong:
        raise RuntimeError(
            f"{process_dir.name} is outside Android top-app cgroups: {wrong}"
        )


def live_process_is_top_app(process_dir):
    try:
        validate_top_app(process_dir)
    except RuntimeError:
        if not process_dir.exists():
            return False
        raise
    return True


def read_process_environment(entry):
    try:
        return parse_environment((entry / "environ").read_bytes())
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def find_auxiliary_processes(proc_root=Path("/proc")):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm not in AUXILIARY_COMMS:
            continue
        environment = read_process_environment(entry)
        if environment is not None and validate_environment(environment):
            matches.append((int(entry.name), entry, comm))
    return sorted(matches)


def find_steam_helpers(steam_base, proc_root=Path("/proc")):
    expected = str(steam_base / "client/steamrtarm64/steamwebhelper")
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().split(b"\0", 1)[0]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if command.decode("utf-8", "replace") == expected:
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


def verify_uniform_mask(process_dir, mask):
    threads = read_threads(process_dir)
    wrong = {
        tid: (comm, current)
        for tid, (comm, current) in threads.items()
        if current != mask
    }
    if wrong:
        raise RuntimeError(f"threads retain masks other than {mask}: {wrong}")


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


def apply_uniform_affinity(pid, mask, runner=subprocess.run):
    return run_taskset(["taskset", "-apc", mask, str(pid)], runner)


def ensure_uniform_affinity(pid, process_dir, mask, runner=subprocess.run):
    try:
        verify_uniform_mask(process_dir, mask)
        return False
    except RuntimeError:
        apply_uniform_affinity(pid, mask, runner)
        verify_uniform_mask(process_dir, mask)
        return True


def converge_game_affinity(pid, process_dir, isolate_raknet, runner=subprocess.run):
    threads = read_threads(process_dir)
    raknet_count = sum(comm == RAKNET_COMM for comm, _mask in threads.values())
    if raknet_count > 1:
        raise RuntimeError(
            f"expected at most one {RAKNET_COMM} thread, found {raknet_count}"
        )
    ready_for_isolation = isolate_raknet and raknet_count == 1
    try:
        verify_threads(threads, ready_for_isolation)
    except RuntimeError:
        apply_affinity(pid, process_dir, ready_for_isolation, runner)
        threads = read_threads(process_dir)
        verify_threads(threads, ready_for_isolation)
    return not isolate_raknet or ready_for_isolation


def matching_window(display, pattern, runner=subprocess.run):
    environment = os.environ.copy()
    environment["DISPLAY"] = display
    try:
        completed = runner(
            ["xdotool", "search", "--onlyvisible", "--name", pattern],
            check=False,
            text=True,
            capture_output=True,
            timeout=5,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return False
    return any(line.isdigit() for line in completed.stdout.splitlines())


def acquire_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def watch_for_ready_game(arguments, runner=subprocess.run):
    proc_root = Path(arguments.proc_root)
    steam_base = Path(arguments.steam_base)
    deadline = time.monotonic() + arguments.wait_seconds
    stable_since = None
    tracked_pid = None

    while time.monotonic() < deadline:
        helper_matches = find_steam_helpers(steam_base, proc_root)
        helpers_ready = bool(helper_matches)
        for helper_pid, helper_dir in helper_matches:
            if not helper_dir.exists():
                continue
            try:
                if live_process_is_top_app(helper_dir):
                    ensure_uniform_affinity(
                        helper_pid, helper_dir, STEAM_HELPER_CPUS, runner
                    )
            except (RuntimeError, subprocess.CalledProcessError):
                if helper_dir.exists():
                    raise

        matches = find_game_processes(proc_root)
        if len(matches) > 1:
            raise RuntimeError(
                "expected at most one verified App ID 203160 Tomb Raider process, "
                f"found {len(matches)}"
            )
        if not matches:
            tracked_pid = None
            stable_since = None
            time.sleep(arguments.poll_seconds)
            continue

        pid, process_dir = matches[0]
        if tracked_pid != pid:
            print(f"Tomb Raider PID {pid}: affinity guard attached", flush=True)
            tracked_pid = pid
            stable_since = None
        try:
            if not live_process_is_top_app(process_dir):
                continue
            game_ready = converge_game_affinity(
                pid, process_dir, arguments.raknet_cpu1, runner
            )
        except (RuntimeError, subprocess.CalledProcessError):
            if not process_dir.exists():
                tracked_pid = None
                stable_since = None
                continue
            raise

        auxiliary_matches = find_auxiliary_processes(proc_root)
        auxiliary_ready = any(
            comm == "wineserver" for _pid, _directory, comm in auxiliary_matches
        )
        for auxiliary_pid, auxiliary_dir, _comm in auxiliary_matches:
            if not auxiliary_dir.exists():
                continue
            try:
                if live_process_is_top_app(auxiliary_dir):
                    ensure_uniform_affinity(
                        auxiliary_pid, auxiliary_dir, AUXILIARY_CPUS, runner
                    )
            except (RuntimeError, subprocess.CalledProcessError):
                if auxiliary_dir.exists():
                    raise

        window_ready = matching_window(arguments.display, arguments.window_regex, runner)
        if game_ready and window_ready and auxiliary_ready and helpers_ready:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= arguments.stable_seconds:
                threads = read_threads(process_dir)
                verify_threads(threads, arguments.raknet_cpu1)
                print(
                    f"Tomb Raider performance state: ready; PID {pid}, "
                    f"{len(threads)} threads, CPUs 1-7"
                    + (", RakNet CPU 1" if arguments.raknet_cpu1 else "")
                    + ", Steam helpers CPU 0",
                    flush=True,
                )
                return 0
        else:
            stable_since = None
        time.sleep(arguments.poll_seconds)

    raise RuntimeError(
        f"Tomb Raider did not reach a stable performance state in "
        f"{arguments.wait_seconds:g} seconds"
    )


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--raknet-cpu1",
        action="store_true",
        help="add the separately measured busy-loop isolation",
    )
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sys-cpu-root", default="/sys/devices/system/cpu", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--steam-base", default=str(Path.home() / "steam-arm64")
    )
    parser.add_argument("--display", default=":0")
    parser.add_argument("--window-regex", default="^Tomb Raider$")
    parser.add_argument("--wait-seconds", type=float, default=7200.0)
    parser.add_argument("--stable-seconds", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--lock-file", type=Path)
    return parser


def main():
    arguments = build_parser().parse_args()
    try:
        if arguments.check and arguments.watch:
            raise RuntimeError("--check and --watch are mutually exclusive")
        if not 1 <= arguments.wait_seconds <= 21600:
            raise RuntimeError("--wait-seconds must be between 1 and 21600")
        if not 1 <= arguments.stable_seconds <= 120:
            raise RuntimeError("--stable-seconds must be between 1 and 120")
        if not 0.25 <= arguments.poll_seconds <= 10:
            raise RuntimeError("--poll-seconds must be between 0.25 and 10")
        layout = read_cpu_layout(Path(arguments.sys_cpu_root))
        validate_tab_s8_plus_layout(layout)
        if arguments.watch:
            lock_handle = None
            if arguments.lock_file is not None:
                lock_handle = acquire_lock(arguments.lock_file)
                if lock_handle is None:
                    print("Tomb Raider affinity guard: already active")
                    return 0
            return watch_for_ready_game(arguments)
        matches = find_game_processes(Path(arguments.proc_root))
        if len(matches) != 1:
            raise RuntimeError(
                "expected exactly one verified App ID 203160 Tomb Raider process, "
                f"found {len(matches)}"
            )
        pid, process_dir = matches[0]
        validate_top_app(process_dir)
        before = read_threads(process_dir)
        print(f"Tomb Raider PID {pid}: {len(before)} threads")
        if arguments.check:
            verify_threads(before, arguments.raknet_cpu1)
            auxiliaries = find_auxiliary_processes(Path(arguments.proc_root))
            if not any(comm == "wineserver" for _pid, _path, comm in auxiliaries):
                raise RuntimeError("no verified App ID 203160 wineserver found")
            for _auxiliary_pid, auxiliary_dir, _comm in auxiliaries:
                validate_top_app(auxiliary_dir)
                verify_uniform_mask(auxiliary_dir, AUXILIARY_CPUS)
            helpers = find_steam_helpers(
                Path(arguments.steam_base), Path(arguments.proc_root)
            )
            if not helpers:
                raise RuntimeError("no Steam web helpers found")
            for _helper_pid, helper_dir in helpers:
                validate_top_app(helper_dir)
                verify_uniform_mask(helper_dir, STEAM_HELPER_CPUS)
            print(
                "Tomb Raider affinity: verified; Wine CPUs 1-7, "
                f"{len(helpers)} Steam helpers CPU 0"
            )
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
