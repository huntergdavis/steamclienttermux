#!/usr/bin/env python3

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "set-superflight-affinity.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("set_superflight_affinity", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_process(proc_root, pid, comm, environment, masks):
    process = proc_root / str(pid)
    process.mkdir()
    (process / "comm").write_text(comm + "\n")
    encoded = b"\0".join(key + b"=" + value for key, value in environment.items()) + b"\0"
    (process / "environ").write_bytes(encoded)
    for thread, mask in masks.items():
        thread_dir = process / "task" / str(thread)
        thread_dir.mkdir(parents=True)
        (thread_dir / "status").write_text(
            f"Name:\t{comm}\nState:\tS (sleeping)\nCpus_allowed_list:\t{mask}\n"
        )
    return process


def add_cpu(sys_root, number, capacity, maximum):
    cpu = sys_root / f"cpu{number}"
    (cpu / "cpufreq").mkdir(parents=True)
    (cpu / "cpu_capacity").write_text(f"{capacity}\n")
    (cpu / "cpufreq/cpuinfo_max_freq").write_text(f"{maximum}\n")


def test_discovery_and_masks(module, temporary):
    proc_root = temporary / "proc"
    proc_root.mkdir()
    valid_environment = {
        b"STEAM_COMPAT_APP_ID": b"732430",
        b"SteamAppId": b"732430",
        b"STEAM_COMPAT_DATA_PATH": b"/x/steamapps/compatdata/732430",
    }
    valid = add_process(
        proc_root, 15964, "superflight.exe", valid_environment, {15964: "4-7", 15965: "4-7"}
    )
    add_process(proc_root, 2, "superflight.exe", {**valid_environment, b"SteamAppId": b"1"}, {2: "0-7"})
    add_process(proc_root, 3, "other.exe", valid_environment, {3: "0-7"})
    assert module.find_game_processes(proc_root) == [(15964, valid)]
    assert module.read_thread_masks(valid) == {15964: "4-7", 15965: "4-7"}


def test_layout(module, temporary):
    sys_root = temporary / "sys-cpu"
    for number in range(8):
        if number < 4:
            add_cpu(sys_root, number, 261, 1785600)
        else:
            add_cpu(sys_root, number, 805 if number < 7 else 1024, 2496000)
    layout = module.read_cpu_layout(sys_root)
    module.validate_tab_s8_plus_layout(layout)
    layout[4] = (200, 2496000)
    try:
        module.validate_tab_s8_plus_layout(layout)
    except RuntimeError as error:
        assert "higher-capacity cluster" in str(error)
    else:
        raise AssertionError("invalid CPU cluster split was accepted")


def test_command(module):
    calls = []

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(stdout="", stderr="")

    module.apply_affinity(15964, runner=runner)
    assert calls == [
        (
            ["taskset", "-apc", "4-7", "15964"],
            {"check": True, "text": True, "capture_output": True},
        )
    ]


def main():
    module = load_tool()
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_discovery_and_masks(module, temporary)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_layout(module, temporary)
    test_command(module)
    print("Superflight affinity tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
