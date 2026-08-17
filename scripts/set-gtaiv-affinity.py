#!/usr/bin/env python3

"""Continuously apply the measured Tab S8+ GTA IV CPU partition."""

import argparse
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import time


APP_ID = b"12210"
MASKS = {
    "game": "4-7",
    "wine": "4-5",
    "service": "6",
    "tracer": "7",
}


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
    return compatdata in {
        encoded_base + b"/removable-library/steamapps/compatdata/" + APP_ID,
        encoded_base + b"/removable-library-compatdata/" + APP_ID,
    }


def classify_process(comm, arguments, steam_base):
    if not arguments:
        return None
    executable = arguments[0].lower()
    command = b"\0".join(arguments)
    if comm == "GTAIV.exe" and executable.endswith(b"\\gtaiv.exe"):
        return "game"
    if executable.endswith(b"\\playgtaiv.exe"):
        return "wine"
    if executable.endswith(b"\\rockstar games\\launcher\\launcher.exe"):
        return "wine"
    if executable.endswith(
        b"\\rockstar games\\social club\\socialclubhelper.exe"
    ):
        return "wine"
    if executable.endswith(b"\\rockstar games\\launcher\\rockstarservice.exe"):
        return "service"
    if comm == "wineserver":
        expected = os.fsencode(
            steam_base
            / "client/steamapps/common/Proton 11.0 (ARM64)/files/bin-arm64/wineserver"
        )
        if arguments and arguments[0] == expected:
            return "wine"
    if comm == "proot":
        expected = os.fsencode(steam_base / "src/proot-production/src/proot")
        if (
            arguments
            and arguments[0] == expected
            and b"--kill-on-exit" in arguments
            and b"Grand Theft Auto IV/GTAIV/PlayGTAIV.exe" in command
        ):
            return "tracer"
    return None


def find_targets(proc_root=Path("/proc"), steam_base=Path.home() / "steam-arm64"):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            arguments = [
                item for item in (entry / "cmdline").read_bytes().split(b"\0") if item
            ]
            environment = parse_environment((entry / "environ").read_bytes())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if not validate_environment(environment, steam_base):
            continue
        role = classify_process(comm, arguments, steam_base)
        if role is not None:
            matches.append((int(entry.name), entry, comm, role))
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


def ensure_affinity(pid, process_dir, mask, runner=subprocess.run):
    threads = read_threads(process_dir)
    if all(current == mask for _comm, current in threads.values()):
        return True
    runner(
        ["taskset", "-apc", mask, str(pid)],
        check=True,
        text=True,
        capture_output=True,
    )
    threads = read_threads(process_dir)
    return all(current == mask for _comm, current in threads.values())


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


def matching_window(display, runner=subprocess.run):
    environment = os.environ.copy()
    environment["DISPLAY"] = display
    try:
        completed = runner(
            ["xdotool", "search", "--onlyvisible", "--class", "^steam_app_12210$"],
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


def watch(arguments, runner=subprocess.run):
    proc_root = Path(arguments.proc_root)
    steam_base = Path(arguments.steam_base)
    deadline = time.monotonic() + arguments.wait_seconds
    known = {}
    seen_app = False
    seen_game = False
    idle_since = None
    stable_since = None
    reported_ready = False

    while time.monotonic() < deadline:
        targets = find_targets(proc_root, steam_base)
        game_targets = [target for target in targets if target[3] == "game"]
        if len(game_targets) > 1:
            raise RuntimeError(
                f"expected at most one verified GTAIV.exe, found {len(game_targets)}"
            )
        if targets:
            seen_app = True
            idle_since = None
        elif seen_app:
            if idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= arguments.exit_idle_seconds:
                print("GTA IV affinity guard: AppID 12210 process tree exited", flush=True)
                return 0

        roles = {role for _pid, _process_dir, _comm, role in targets}
        ready = {"game", "wine", "service", "tracer"}.issubset(roles)
        current_pids = set()
        for pid, process_dir, comm, role in targets:
            current_pids.add(pid)
            if known.get(pid) != (comm, role):
                print(
                    f"GTA IV affinity guard: attached {comm} PID {pid} -> CPUs {MASKS[role]}",
                    flush=True,
                )
                known[pid] = (comm, role)
            try:
                validate_top_app(process_dir)
                ready = ensure_affinity(pid, process_dir, MASKS[role], runner) and ready
            except (RuntimeError, subprocess.CalledProcessError):
                if process_dir.exists():
                    raise
                ready = False
        known = {pid: value for pid, value in known.items() if pid in current_pids}

        if game_targets:
            seen_game = True
        window_ready = matching_window(arguments.display, runner) if seen_game else False
        if ready and window_ready:
            if stable_since is None:
                stable_since = time.monotonic()
            elif (
                not reported_ready
                and time.monotonic() - stable_since >= arguments.stable_seconds
            ):
                pid, process_dir, _comm, _role = game_targets[0]
                print(
                    f"GTA IV performance state: ready; PID {pid}, "
                    f"{len(read_threads(process_dir))} threads on CPUs 4-7; "
                    "Rockstar/Wine 4-5, service 6, tracer 7",
                    flush=True,
                )
                reported_ready = True
        else:
            stable_since = None
        time.sleep(arguments.poll_seconds)

    raise RuntimeError(
        f"GTA IV affinity guard exceeded {arguments.wait_seconds:g} seconds"
    )


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sys-cpu-root", default="/sys/devices/system/cpu", help=argparse.SUPPRESS
    )
    parser.add_argument("--steam-base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--display", default=":0")
    parser.add_argument("--wait-seconds", type=float, default=7200.0)
    parser.add_argument("--stable-seconds", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--exit-idle-seconds", type=float, default=120.0)
    parser.add_argument("--lock-file", type=Path)
    return parser


def main():
    arguments = build_parser().parse_args()
    try:
        if arguments.watch and arguments.check:
            raise RuntimeError("--watch and --check are mutually exclusive")
        if not 1 <= arguments.wait_seconds <= 21600:
            raise RuntimeError("--wait-seconds must be between 1 and 21600")
        if not 1 <= arguments.stable_seconds <= 120:
            raise RuntimeError("--stable-seconds must be between 1 and 120")
        if not 0.25 <= arguments.poll_seconds <= 10:
            raise RuntimeError("--poll-seconds must be between 0.25 and 10")
        if not 10 <= arguments.exit_idle_seconds <= 600:
            raise RuntimeError("--exit-idle-seconds must be between 10 and 600")
        validate_tab_s8_plus_layout(read_cpu_layout(Path(arguments.sys_cpu_root)))
        if arguments.lock_file is not None:
            lock_handle = acquire_lock(arguments.lock_file)
            if lock_handle is None:
                print("GTA IV affinity guard: already active")
                return 0
        targets = find_targets(Path(arguments.proc_root), Path(arguments.steam_base))
        if arguments.check:
            if not targets:
                raise RuntimeError("no verified AppID 12210 processes found")
            for _pid, process_dir, _comm, role in targets:
                validate_top_app(process_dir)
                threads = read_threads(process_dir)
                wrong = [tid for tid, (_comm, mask) in threads.items() if mask != MASKS[role]]
                if wrong:
                    raise RuntimeError(
                        f"{process_dir.name} retains unexpected thread masks: {wrong}"
                    )
            print(f"GTA IV affinity: verified {len(targets)} processes")
            return 0
        if arguments.watch:
            return watch(arguments)
        raise RuntimeError("specify --watch or --check")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"set-gtaiv-affinity: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
