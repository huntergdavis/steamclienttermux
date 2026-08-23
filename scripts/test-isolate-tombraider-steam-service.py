#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import subprocess
import tempfile


TOOL = Path(__file__).with_name("isolate-tombraider-steam-service.py")
AFFINITY = Path(__file__).with_name("set-tombraider-affinity.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proc_entry(root, pid, name, ppid, start, cmdline, cpus="0-3", cgroup=True):
    entry = root / str(pid)
    entry.mkdir(parents=True, exist_ok=True)
    fields = ["S", str(ppid)] + ["0"] * 48
    fields[19] = str(start)
    (entry / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
    (entry / "cmdline").write_bytes(b"\0".join(cmdline) + b"\0")
    (entry / "comm").write_text(f"{name}\n")
    (entry / "status").write_text(f"Name:\t{name}\nCpus_allowed_list:\t{cpus}\n")
    if cgroup:
        (entry / "cgroup").write_text("4:cpuset:/top-app\n2:cpu:/top-app\n")
    return entry


def main():
    tool = load(TOOL, "isolate_steam_service")
    affinity = load(AFFINITY, "affinity")
    assert tool.parse_cpu_list("0-3,5,7-8") == (0, 1, 2, 3, 5, 7, 8)
    assert tool.format_cpu_list((0, 1, 2, 3, 5, 7, 8)) == "0-3,5,7-8"
    assert tool.allowed_cpu_list("Name:\tt\nCpus_allowed_list:\t0-3\n") == "0-3"
    for invalid in ("", "-1", "3-1", "1,,2", "x"):
        try:
            tool.parse_cpu_list(invalid)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid CPU list accepted: {invalid!r}")

    with tempfile.TemporaryDirectory(prefix="isolate-steam-service.") as directory:
        root = Path(directory)
        proc = root / "proc"
        proc.mkdir()
        base = root / "steam-arm64"
        steam = base / "client/steamrtarm64/steam"
        steam_entry = proc_entry(proc, 10, "steam", 1, 100, [str(steam).encode()])
        task = steam_entry / "task"
        proc_entry(task, 10, "steam", 1, 100, [str(steam).encode()])
        service = proc_entry(
            task,
            20,
            tool.SERVICE_COMM,
            10,
            200,
            [str(steam).encode()],
        )
        proc_entry(task, 21, "steam", 10, 210, [str(steam).encode()])
        steam_pid, _entry = tool.find_exact_steam(affinity, base, proc)
        assert steam_pid == 10
        record = tool.find_exact_service_thread(steam_pid, proc)
        assert record["tid"] == 20
        assert record["start_ticks"] == 200
        assert record["cpus"] == "0-3"
        assert tool.same_thread(service, record)
        (service / "comm").write_text("changed\n")
        assert not tool.same_thread(service, record)
        (service / "comm").write_text(f"{tool.SERVICE_COMM}\n")

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "pid 20 affinity: 0-3\n")

        tool.set_thread_cpus(20, "0", runner)
        tool.set_thread_cpus(20, "0-3", runner)
        assert [call[0] for call in calls] == [
            ["taskset", "-pc", "0", "20"],
            ["taskset", "-pc", "0-3", "20"],
        ]

        proc_entry(
            task,
            22,
            tool.SERVICE_COMM,
            10,
            220,
            [str(steam).encode()],
        )
        try:
            tool.find_exact_service_thread(steam_pid, proc)
        except RuntimeError as error:
            assert "expected one exact" in str(error)
        else:
            raise AssertionError("multiple service threads were accepted")

    print("Steam service CPU isolation tests: PASS")


if __name__ == "__main__":
    main()
