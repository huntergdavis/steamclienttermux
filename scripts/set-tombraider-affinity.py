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
CPU_COUNT_PATTERN = re.compile(
    rb"\[MultiCore\] CPU count: logical = ([0-9]+), cores = ([0-9]+), "
    rb"physical = ([0-9]+)"
)
CPU_TOPOLOGY_PATTERN = re.compile(rb"([0-9]+):([0-9]+(?:,[0-9]+)*)")


def parse_environment(data):
    environment = {}
    for item in data.split(b"\0"):
        key, separator, value = item.partition(b"=")
        if separator:
            environment[key] = value
    return environment


def validate_environment(environment, steam_base):
    if environment.get(b"STEAM_COMPAT_APP_ID") != APP_ID:
        return False
    for key in (b"SteamAppId", b"SteamGameId"):
        if key in environment and environment[key] != APP_ID:
            return False
    compatdata = environment.get(b"STEAM_COMPAT_DATA_PATH", b"").rstrip(b"/")
    encoded_base = os.fsencode(steam_base)
    expected = {
        encoded_base + b"/removable-library/steamapps/compatdata/" + APP_ID,
        encoded_base + b"/removable-library-compatdata/" + APP_ID,
    }
    return compatdata in expected


def find_game_processes(
    proc_root=Path("/proc"), steam_base=Path.home() / "steam-arm64"
):
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
        if validate_environment(environment, steam_base):
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


def format_cpu_mask(cpu_ids):
    ranges = []
    start = previous = None
    for cpu in sorted(cpu_ids):
        if start is None:
            start = previous = cpu
        elif cpu == previous + 1:
            previous = cpu
        else:
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = cpu
    if start is not None:
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def discovery_cpu_mask(environment):
    values = {
        environment.get(key)
        for key in (b"WINE_CPU_TOPOLOGY", b"PROTON_CPU_TOPOLOGY")
        if environment.get(key) is not None
    }
    if len(values) != 1:
        raise RuntimeError("game has missing or inconsistent CPU topology variables")
    value = values.pop()
    match = CPU_TOPOLOGY_PATTERN.fullmatch(value)
    if match is None:
        raise RuntimeError(f"game has malformed CPU topology: {value!r}")
    count = int(match.group(1))
    cpu_ids = [int(item) for item in match.group(2).split(b",")]
    if (
        count != len(cpu_ids)
        or count < 2
        or len(set(cpu_ids)) != count
        or any(cpu not in range(1, 8) for cpu in cpu_ids)
    ):
        raise RuntimeError(f"game has unsafe CPU topology: {value!r}")
    return format_cpu_mask(cpu_ids)


def find_auxiliary_processes(
    proc_root=Path("/proc"), steam_base=Path.home() / "steam-arm64"
):
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
        if environment is not None and validate_environment(environment, steam_base):
            matches.append((int(entry.name), entry, comm))
    return sorted(matches)


def command_targets(arguments, expected, steam_base):
    if not arguments:
        return False
    if arguments[0] == expected:
        return True

    loader = Path(os.fsdecode(arguments[0]))
    loader_root = steam_base.parent / ".local/share/tgcompat/glibc"
    try:
        relative = loader.relative_to(loader_root)
    except ValueError:
        return False
    if len(relative.parts) != 3:
        return False
    if relative.parts[1:] != ("lib", "ld-linux-aarch64.so.1"):
        return False
    if not relative.parts[0]:
        return False

    has_argv0 = any(
        arguments[index] == b"--argv0" and arguments[index + 1] == expected
        for index in range(len(arguments) - 1)
    )
    return has_argv0 and expected in arguments[1:]


def find_steam_helpers(steam_base, proc_root=Path("/proc")):
    expected = os.fsencode(steam_base / "client/steamrtarm64/steamwebhelper")
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = [
                argument
                for argument in (entry / "cmdline").read_bytes().split(b"\0")
                if argument
            ]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if command_targets(arguments, expected, steam_base):
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
        return True
    except RuntimeError:
        apply_uniform_affinity(pid, mask, runner)
        try:
            verify_uniform_mask(process_dir, mask)
        except RuntimeError:
            # Auxiliary Wine and Steam helper threads can rewrite their masks
            # in the same interval as the main FEX process. Keep the guard
            # alive and retry this unstable sample on the next poll.
            return False
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
        try:
            verify_threads(threads, ready_for_isolation)
        except RuntimeError:
            # FEX and the game create threads and can update their masks while
            # taskset -a is walking /proc/PID/task. A residual valid-process
            # mismatch means the state is not stable yet; the watch loop will
            # reapply it on its next poll. Execution or identity failures still
            # propagate from apply_affinity and the process selectors.
            return False
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


def tomb_raider_log(steam_base):
    return (
        steam_base
        / "removable-library-compatdata/203160/pfx/drive_c/users/steamuser"
        / "Documents/Tomb Raider/Tomb Raider.log"
    )


def log_size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def fresh_cpu_count(path, offset):
    try:
        size = path.stat().st_size
        if size < offset:
            offset = 0
        with path.open("rb") as handle:
            handle.seek(offset)
            fresh = handle.read()
    except FileNotFoundError:
        return None, offset
    match = CPU_COUNT_PATTERN.search(fresh)
    if match is None:
        return None, offset
    return tuple(int(value) for value in match.groups()), offset + match.end()


def watch_for_ready_game(arguments, runner=subprocess.run):
    proc_root = Path(arguments.proc_root)
    steam_base = Path(arguments.steam_base)
    deadline = time.monotonic() + arguments.wait_seconds
    stable_since = None
    tracked_pid = None
    wait_for_cpu_log = getattr(arguments, "wait_for_cpu_log", False)
    topology_ready = not wait_for_cpu_log
    discovery_mask = None
    cpu_log = tomb_raider_log(steam_base)
    cpu_log_offset = log_size(cpu_log) if wait_for_cpu_log else 0

    while time.monotonic() < deadline:
        matches = find_game_processes(proc_root, steam_base)
        if len(matches) > 1:
            raise RuntimeError(
                "expected at most one verified App ID 203160 Tomb Raider process, "
                f"found {len(matches)}"
            )
        if not matches:
            tracked_pid = None
            discovery_mask = None
            stable_since = None
            time.sleep(arguments.poll_seconds)
            continue

        pid, process_dir = matches[0]
        if tracked_pid != pid:
            print(f"Tomb Raider PID {pid}: affinity guard detected game", flush=True)
            tracked_pid = pid
            discovery_mask = None
            if wait_for_cpu_log:
                environment = read_process_environment(process_dir)
                if environment is None:
                    time.sleep(arguments.poll_seconds)
                    continue
                discovery_mask = discovery_cpu_mask(environment)
                print(
                    f"Tomb Raider PID {pid}: holding startup topology on "
                    f"CPUs {discovery_mask}",
                    flush=True,
                )
            stable_since = None
        if not topology_ready:
            try:
                if not live_process_is_top_app(process_dir):
                    time.sleep(arguments.poll_seconds)
                    continue
                if discovery_mask is None:
                    raise RuntimeError("startup CPU topology mask is unavailable")
                if not ensure_uniform_affinity(
                    pid, process_dir, discovery_mask, runner
                ):
                    time.sleep(arguments.poll_seconds)
                    continue
            except (RuntimeError, subprocess.CalledProcessError):
                if not process_dir.exists():
                    tracked_pid = None
                    discovery_mask = None
                    stable_since = None
                    continue
                raise
            counts, cpu_log_offset = fresh_cpu_count(cpu_log, cpu_log_offset)
            if counts is None:
                time.sleep(arguments.poll_seconds)
                continue
            logical, cores, physical = counts
            if min(counts) <= 1:
                raise RuntimeError(
                    "Tomb Raider initialized with unusable CPU topology: "
                    f"logical={logical}, cores={cores}, physical={physical}"
                )
            topology_ready = True
            print(
                f"Tomb Raider PID {pid}: startup topology ready; "
                f"logical={logical}, cores={cores}, physical={physical}; "
                "affinity guard attached",
                flush=True,
            )
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

        helper_matches = find_steam_helpers(steam_base, proc_root)
        helpers_ready = bool(helper_matches)
        for helper_pid, helper_dir in helper_matches:
            if not helper_dir.exists():
                continue
            try:
                if live_process_is_top_app(helper_dir):
                    helpers_ready = ensure_uniform_affinity(
                        helper_pid, helper_dir, STEAM_HELPER_CPUS, runner
                    ) and helpers_ready
                else:
                    helpers_ready = False
            except (RuntimeError, subprocess.CalledProcessError):
                helpers_ready = False
                if helper_dir.exists():
                    raise

        auxiliary_matches = find_auxiliary_processes(proc_root, steam_base)
        auxiliary_ready = any(
            comm == "wineserver" for _pid, _directory, comm in auxiliary_matches
        )
        for auxiliary_pid, auxiliary_dir, _comm in auxiliary_matches:
            if not auxiliary_dir.exists():
                continue
            try:
                if live_process_is_top_app(auxiliary_dir):
                    auxiliary_ready = ensure_uniform_affinity(
                        auxiliary_pid, auxiliary_dir, AUXILIARY_CPUS, runner
                    ) and auxiliary_ready
                else:
                    auxiliary_ready = False
            except (RuntimeError, subprocess.CalledProcessError):
                auxiliary_ready = False
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
    parser.add_argument(
        "--wait-for-cpu-log",
        action="store_true",
        help="delay affinity until this launch reports a usable CPU topology",
    )
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
        steam_base = Path(arguments.steam_base)
        matches = find_game_processes(Path(arguments.proc_root), steam_base)
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
            auxiliaries = find_auxiliary_processes(
                Path(arguments.proc_root), steam_base
            )
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
