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


def add_process(
    proc_root,
    pid,
    comm,
    environment,
    threads,
    command=None,
    cpuset="/top-app",
    cpu="/top-app",
):
    process = proc_root / str(pid)
    process.mkdir()
    (process / "comm").write_text(comm + "\n")
    encoded = b"\0".join(key + b"=" + value for key, value in environment.items()) + b"\0"
    (process / "environ").write_bytes(encoded)
    (process / "cmdline").write_bytes((command or comm).encode() + b"\0")
    (process / "cgroup").write_text(f"2:cpu:{cpu}\n3:cpuset:{cpuset}\n")
    for tid, (thread_comm, mask) in threads.items():
        task = process / "task" / str(tid)
        task.mkdir(parents=True)
        (task / "comm").write_text(thread_comm + "\n")
        (task / "stat").write_text(
            f"{tid} ({thread_comm}) S " + " ".join(["0"] * 16) + "\n"
        )
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
            b"STEAM_COMPAT_DATA_PATH": (
                b"/base/removable-library/steamapps/compatdata/203160"
            ),
        }
        native_environment = {
            **environment,
            b"STEAM_COMPAT_DATA_PATH": (
                b"/base/removable-library-compatdata/203160"
            ),
        }
        topology_environment = {
            **native_environment,
            b"PROTON_CPU_TOPOLOGY": b"6:0,1,2,3,4,6",
            b"WINE_CPU_TOPOLOGY": b"6:0,1,2,3,4,6",
        }
        decoy_environment = {
            **environment,
            b"STEAM_COMPAT_DATA_PATH": (
                b"/decoy/removable-library-compatdata/203160"
            ),
        }
        assert module.validate_environment(environment, Path("/base"))
        assert module.validate_environment(native_environment, Path("/base"))
        assert not module.validate_environment(decoy_environment, Path("/base"))
        assert module.discovery_cpu_mask(topology_environment) == "0-4,6"
        assert module.format_cpu_mask({1, 2, 3, 5, 7}) == "1-3,5,7"
        for invalid_topology in (
            {},
            {b"WINE_CPU_TOPOLOGY": b"1:1"},
            {b"WINE_CPU_TOPOLOGY": b"2:1,1"},
            {b"WINE_CPU_TOPOLOGY": b"2:0,8"},
            {
                b"PROTON_CPU_TOPOLOGY": b"2:1,2",
                b"WINE_CPU_TOPOLOGY": b"2:1,3",
            },
        ):
            try:
                module.discovery_cpu_mask(invalid_topology)
            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    f"unsafe discovery topology was accepted: {invalid_topology}"
                )
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
        assert module.find_game_processes(proc_root, Path("/base")) == [
            (27038, process)
        ]
        module.validate_top_app(process)
        threads = module.read_threads(process)
        module.verify_threads(threads, isolate_raknet=True)
        assert module.converge_game_affinity(27038, process, True)
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
        calls.clear()
        module.apply_affinity(27038, process, True, 19, runner=runner)
        assert [call[0] for call in calls] == [
            ["taskset", "-apc", "1-7", "27038"],
            ["taskset", "-pc", "1", "28142"],
            ["renice", "-n", "19", "-p", "28142"],
        ]
        raknet_stat = process / "task/28142/stat"
        assert module.read_thread_nice(process, 28142) == 0
        assert not module.ensure_thread_nice(process, 28142, 19, runner=runner)
        raknet_stat.write_text(
            "28142 (Raknet-RecvFrom) S " + " ".join(["0"] * 15 + ["19"]) + "\n"
        )
        assert module.read_thread_nice(process, 28142) == 19
        assert module.ensure_thread_nice(process, 28142, 19, runner=runner)

        # A game/FEX mask rewrite racing taskset is an unstable sample, not a
        # fatal guard error. A later poll can converge it normally.
        main_status = process / "task/27038/status"
        main_status.write_text(
            "Name:\tTombRaider.exe\nState:\tS (sleeping)\n"
            "Cpus_allowed_list:\t1-6\n"
        )
        retry_calls = []

        def retry_runner(arguments, **kwargs):
            retry_calls.append((arguments, kwargs))
            return SimpleNamespace(stdout="", stderr="")

        assert not module.converge_game_affinity(
            27038, process, True, runner=retry_runner
        )
        assert retry_calls
        main_status.write_text(
            "Name:\tTombRaider.exe\nState:\tS (sleeping)\n"
            "Cpus_allowed_list:\t1-7\n"
        )
        assert module.converge_game_affinity(
            27038, process, True, runner=retry_runner
        )

        auxiliary = add_process(
            proc_root,
            30000,
            "wineserver",
            environment,
            {30000: ("wineserver", "1-7")},
        )
        assert module.find_auxiliary_processes(proc_root, Path("/base")) == [
            (30000, auxiliary, "wineserver")
        ]
        auxiliary_status = auxiliary / "task/30000/status"
        auxiliary_status.write_text(
            "Name:\twineserver\nState:\tS (sleeping)\n"
            "Cpus_allowed_list:\t1-6\n"
        )
        assert not module.ensure_uniform_affinity(
            30000, auxiliary, "1-7", runner=retry_runner
        )
        auxiliary_status.write_text(
            "Name:\twineserver\nState:\tS (sleeping)\n"
            "Cpus_allowed_list:\t1-7\n"
        )
        assert module.ensure_uniform_affinity(
            30000, auxiliary, "1-7", runner=retry_runner
        )
        helper = add_process(
            proc_root,
            30001,
            "steamwebhelper",
            {},
            {30001: ("steamwebhelper", "0")},
            command="/base/client/steamrtarm64/steamwebhelper",
        )
        native_helper = add_process(
            proc_root,
            30003,
            "steamwebhelper",
            {},
            {30003: ("steamwebhelper", "0")},
            command=(
                "/.local/share/tgcompat/glibc/candidate/"
                "lib/ld-linux-aarch64.so.1\0--inhibit-cache\0--argv0\0"
                "/base/client/steamrtarm64/steamwebhelper\0"
                "/base/client/steamrtarm64/steamwebhelper"
            ),
        )
        add_process(
            proc_root,
            30004,
            "steamwebhelper",
            {},
            {30004: ("steamwebhelper", "0")},
            command=(
                "/tmp/candidate/lib/ld-linux-aarch64.so.1\0--argv0\0"
                "/base/client/steamrtarm64/steamwebhelper\0"
                "/base/client/steamrtarm64/steamwebhelper"
            ),
        )
        add_process(
            proc_root,
            30005,
            "steamwebhelper",
            {},
            {30005: ("steamwebhelper", "0")},
            command=(
                "/.local/share/tgcompat/glibc/candidate/"
                "lib/ld-linux-aarch64.so.1\0--argv0\0/wrong\0"
                "/base/client/steamrtarm64/steamwebhelper"
            ),
        )
        assert module.find_steam_helpers(Path("/base"), proc_root) == [
            (30001, helper),
            (30003, native_helper),
        ]
        module.verify_uniform_mask(helper, "0")

        background = add_process(
            proc_root,
            30002,
            "background-test",
            environment,
            {30002: ("TombRaider.exe", "0-3")},
            cpuset="/moderate",
            cpu="/background",
        )
        try:
            module.validate_top_app(background)
        except RuntimeError:
            pass
        else:
            raise AssertionError("background process passed top-app validation")

        window_runner = lambda *_args, **_kwargs: SimpleNamespace(stdout="42\n")
        assert module.matching_window(":0", "^Tomb Raider$", window_runner)

        cpu_log = temporary / "Tomb Raider.log"
        cpu_log.write_bytes(
            b"old [MultiCore] CPU count: logical = 1, cores = 1, physical = 1\n"
        )
        cpu_log_offset = module.log_size(cpu_log)
        assert module.fresh_cpu_count(cpu_log, cpu_log_offset) == (
            None,
            cpu_log_offset,
        )
        with cpu_log.open("ab") as handle:
            handle.write(b"new [MultiCore] CPU count: logical = 7, cores = ")
        assert module.fresh_cpu_count(cpu_log, cpu_log_offset) == (
            None,
            cpu_log_offset,
        )
        with cpu_log.open("ab") as handle:
            handle.write(b"7, physical = 7\n")
        counts, advanced_offset = module.fresh_cpu_count(cpu_log, cpu_log_offset)
        assert counts == (7, 7, 7)
        assert advanced_offset > cpu_log_offset

        arguments = SimpleNamespace(
            proc_root=str(proc_root),
            steam_base="/base",
            wait_seconds=1.0,
            stable_seconds=0.0,
            poll_seconds=0.0,
            raknet_cpu1=True,
            raknet_nice=None,
            display=":0",
            window_regex="^Tomb Raider$",
            wait_for_cpu_log=False,
        )
        assert module.watch_for_ready_game(arguments, runner=window_runner) == 0

        # Direct startup affinity is inherited before exec. The finite guard
        # must not race Tomb Raider's per-CPU SetThreadAffinityMask probe by
        # issuing taskset or renice before it consumes the fresh topology log.
        encoded_topology = (
            b"\0".join(
                key + b"=" + value for key, value in topology_environment.items()
            )
            + b"\0"
        )
        (process / "environ").write_bytes(encoded_topology)
        cpu_log.write_bytes(
            b"[MultiCore] CPU count: logical = 6, cores = 6, physical = 6\n"
        )
        module.tomb_raider_log = lambda _steam_base: cpu_log
        module.log_size = lambda _path: 0
        topology_calls = []

        def topology_runner(command, **_kwargs):
            topology_calls.append(command)
            return SimpleNamespace(stdout="42\n", stderr="")

        arguments.wait_for_cpu_log = True
        assert module.watch_for_ready_game(arguments, runner=topology_runner) == 0
        assert topology_calls
        assert all(call[0] == "xdotool" for call in topology_calls)

        lock_path = temporary / "affinity.lock"
        first_lock = module.acquire_lock(lock_path)
        assert first_lock is not None
        assert module.acquire_lock(lock_path) is None
        first_lock.close()

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
