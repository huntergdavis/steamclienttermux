#!/usr/bin/env python3

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "set-tombraider-affinity.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("set_tombraider_affinity", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_process(proc_root, pid, comm, environment, threads):
    process = proc_root / str(pid)
    process.mkdir()
    (process / "comm").write_text(comm + "\n")
    encoded = b"\0".join(key + b"=" + value for key, value in environment.items()) + b"\0"
    (process / "environ").write_bytes(encoded)
    for tid, (thread_comm, mask) in threads.items():
        task = process / "task" / str(tid)
        task.mkdir(parents=True)
        (task / "comm").write_text(thread_comm + "\n")
        (task / "status").write_text(
            f"Name:\t{thread_comm}\nState:\tS (sleeping)\nCpus_allowed_list:\t{mask}\n"
        )
    return process


def add_cpu(root, number, capacity, maximum):
    cpu = root / f"cpu{number}"
    (cpu / "cpufreq").mkdir(parents=True)
    (cpu / "cpu_capacity").write_text(f"{capacity}\n")
    (cpu / "cpufreq/cpuinfo_max_freq").write_text(f"{maximum}\n")


def main():
    module = load_tool()
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        proc_root = temporary / "proc"
        proc_root.mkdir()
        environment = {
            b"STEAM_COMPAT_APP_ID": b"203160",
            b"SteamAppId": b"203160",
            b"STEAM_COMPAT_DATA_PATH": b"/x/steamapps/compatdata/203160",
        }
        process = add_process(
            proc_root,
            27038,
            "TombRaider.exe",
            environment,
            {27038: ("TombRaider.exe", "1-7"), 28142: ("Raknet-RecvFrom", "1")},
        )
        add_process(
            proc_root,
            2,
            "TombRaider.exe",
            {**environment, b"SteamAppId": b"1"},
            {2: ("TombRaider.exe", "0-7")},
        )
        assert module.find_game_processes(proc_root) == [(27038, process)]
        threads = module.read_threads(process)
        module.verify_threads(threads, isolate_raknet=True)
        try:
            module.verify_threads(threads, isolate_raknet=False)
        except RuntimeError:
            pass
        else:
            raise AssertionError("RakNet override was accepted as the plain profile")

        calls = []

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            return SimpleNamespace(stdout="", stderr="")

        module.apply_affinity(27038, process, True, runner=runner)
        assert [call[0] for call in calls] == [
            ["taskset", "-apc", "1-7", "27038"],
            ["taskset", "-pc", "1", "28142"],
        ]

    with tempfile.TemporaryDirectory() as directory:
        cpu_root = Path(directory)
        for cpu in range(8):
            add_cpu(
                cpu_root,
                cpu,
                261 if cpu < 4 else (1024 if cpu == 7 else 805),
                1785600 if cpu < 4 else (2995200 if cpu == 7 else 2496000),
            )
        module.validate_tab_s8_plus_layout(module.read_cpu_layout(cpu_root))

    print("Tomb Raider affinity tests: PASS")


if __name__ == "__main__":
    main()
