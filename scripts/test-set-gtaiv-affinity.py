#!/usr/bin/env python3

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile


TOOL = Path(__file__).with_name("set-gtaiv-affinity.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("set_gtaiv_affinity", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_process(root, pid, comm, command, environment, masks):
    process = root / str(pid)
    process.mkdir()
    (process / "comm").write_text(f"{comm}\n")
    (process / "cmdline").write_bytes(b"\0".join(command) + b"\0")
    (process / "environ").write_bytes(
        b"\0".join(key + b"=" + value for key, value in environment.items()) + b"\0"
    )
    (process / "cgroup").write_text("4:cpuset:/top-app\n2:cpu:/top-app\n")
    for tid, mask in masks.items():
        task = process / "task" / str(tid)
        task.mkdir(parents=True)
        (task / "comm").write_text(f"{comm}\n")
        (task / "status").write_text(
            f"Name:\t{comm}\nCpus_allowed_list:\t{mask}\n"
        )
    return process


def add_cpu(root, number, capacity, maximum):
    cpu = root / f"cpu{number}"
    (cpu / "cpufreq").mkdir(parents=True)
    (cpu / "cpu_capacity").write_text(f"{capacity}\n")
    (cpu / "cpufreq/cpuinfo_max_freq").write_text(f"{maximum}\n")


def main():
    module = load_tool()
    with tempfile.TemporaryDirectory(prefix="set-gtaiv-affinity.") as directory:
        temporary = Path(directory)
        proc_root = temporary / "proc"
        proc_root.mkdir()
        base = Path("/base")
        environment = {
            b"STEAM_COMPAT_APP_ID": b"12210",
            b"SteamGameId": b"12210",
            b"STEAM_COMPAT_DATA_PATH": b"/base/removable-library-compatdata/12210",
        }
        assert module.validate_environment(environment, base)
        assert not module.validate_environment(
            {**environment, b"STEAM_COMPAT_APP_ID": b"203160"}, base
        )

        game = add_process(
            proc_root,
            100,
            "GTAIV.exe",
            [b"Z:\\games\\GTAIV.exe", b"-useSteam"],
            environment,
            {100: "4-7", 101: "4-7"},
        )
        service = add_process(
            proc_root,
            200,
            "RockstarService",
            [b"C:\\Program Files\\Rockstar Games\\Launcher\\RockstarService.exe"],
            environment,
            {200: "6"},
        )
        tracer = add_process(
            proc_root,
            300,
            "proot",
            [
                b"/base/src/proot-production/src/proot",
                b"--kill-on-exit",
                b"Grand Theft Auto IV/GTAIV/PlayGTAIV.exe",
            ],
            environment,
            {300: "7"},
        )
        add_process(
            proc_root,
            400,
            "GTAIV.exe",
            [b"Z:\\games\\GTAIV.exe"],
            {**environment, b"STEAM_COMPAT_DATA_PATH": b"/decoy/12210"},
            {400: "0-7"},
        )
        assert module.find_targets(proc_root, base) == [
            (100, game, "GTAIV.exe", "game"),
            (200, service, "RockstarService", "service"),
            (300, tracer, "proot", "tracer"),
        ]

        module.validate_top_app(game)
        assert module.ensure_affinity(100, game, "4-7")
        status = game / "task/101/status"
        status.write_text("Name:\tGTAIV.exe\nCpus_allowed_list:\t0-7\n")
        calls = []

        def runner(arguments, **kwargs):
            calls.append((arguments, kwargs))
            status.write_text("Name:\tGTAIV.exe\nCpus_allowed_list:\t4-7\n")
            return SimpleNamespace(stdout="", stderr="")

        assert module.ensure_affinity(100, game, "4-7", runner)
        assert calls[0][0] == ["taskset", "-apc", "4-7", "100"]
        assert module.matching_window(
            ":0", lambda *_args, **_kwargs: SimpleNamespace(stdout="42\n")
        )

        cpu_root = temporary / "cpu"
        cpu_root.mkdir()
        for cpu in range(8):
            add_cpu(cpu_root, cpu, 512 if cpu < 4 else 1024 + cpu, 1800000 + cpu)
        module.validate_tab_s8_plus_layout(module.read_cpu_layout(cpu_root))

    print("GTA IV affinity tests: PASS")


if __name__ == "__main__":
    main()
