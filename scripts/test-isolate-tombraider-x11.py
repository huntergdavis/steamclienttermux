#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile


TOOL = Path(__file__).with_name("isolate-tombraider-x11.py")
AFFINITY = Path(__file__).with_name("set-tombraider-affinity.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proc_entry(root, pid, name, ppid, start, processor, cmdline, cgroup=True):
    entry = root / str(pid)
    entry.mkdir()
    fields = ["S", str(ppid)] + ["0"] * 48
    fields[19] = str(start)
    fields[36] = str(processor)
    (entry / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
    (entry / "cmdline").write_bytes(b"\0".join(cmdline) + b"\0")
    if cgroup:
        (entry / "cgroup").write_text("4:cpuset:/top-app\n2:cpu:/top-app\n")
    return entry


def task_entry(process, tid, name, start, processor):
    task = process / "task" / str(tid)
    task.mkdir(parents=True)
    fields = ["S", process.name] + ["0"] * 48
    fields[19] = str(start)
    fields[36] = str(processor)
    (task / "stat").write_text(f"{tid} ({name}) " + " ".join(fields))
    return task


def main():
    tool = load(TOOL, "isolate_x11")
    affinity = load(AFFINITY, "affinity")
    parsed = tool.parse_process_stat(
        "42 (name with spaces) S 7 " + "0 " * 17 + "900 " + "0 " * 16 + "3 " + "0 " * 10
    )
    assert parsed == {"state": "S", "ppid": 7, "start_ticks": 900, "processor": 3}
    assert tool.parse_cpu_set("0,1") == (0, 1)
    for invalid in ("", "-1", "8", "1,0", "0,0", "zero"):
        try:
            tool.parse_cpu_set(invalid)
        except tool.argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError("invalid X11 CPU set was accepted")

    with tempfile.TemporaryDirectory(prefix="isolate-x11.") as directory:
        proc = Path(directory) / "proc"
        proc.mkdir()
        x11 = proc_entry(
            proc,
            10,
            "main",
            1,
            100,
            2,
            [b"termux-x11 com.termux.x11 :0 -ac"],
        )
        task_entry(x11, 10, "main", 100, 2)
        task_entry(x11, 11, "Thread-1", 110, 3)
        pid, found = tool.find_exact_x11(affinity, proc, ":0")
        assert pid == 10 and found == x11
        assert tool.is_exact_x11(x11, ":0")

        masks = {10: {0, 1, 2, 3}, 11: {0, 1, 2, 3}}

        def get_affinity(tid):
            return masks[tid]

        def set_affinity(tid, cpus):
            masks[tid] = set(cpus)

        records = {}
        assert tool.capture_and_isolate_threads(
            x11, records, (0, 1), get_affinity, set_affinity
        ) == [10, 11]
        assert masks == {10: {0, 1}, 11: {0, 1}}
        assert records == {
            10: {"start_ticks": 100, "affinity": frozenset({0, 1, 2, 3})},
            11: {"start_ticks": 110, "affinity": frozenset({0, 1, 2, 3})},
        }
        task_entry(x11, 12, "new-thread", 120, 0)
        masks[12] = {0, 1}
        assert tool.capture_and_isolate_threads(
            x11, records, (0, 1), get_affinity, set_affinity
        ) == [10, 11, 12]
        assert tool.restore_threads(
            x11, 100, records, get_affinity, set_affinity
        ) == [10, 11, 12]
        assert masks == {
            10: {0, 1, 2, 3},
            11: {0, 1, 2, 3},
            12: {0, 1},
        }

        (x11 / "stat").write_text(
            (x11 / "stat").read_text().replace(" 100 ", " 101 ", 1)
        )
        assert tool.restore_threads(x11, 100, records, get_affinity, set_affinity) == []

    print("Termux X11 experimental isolation tests: PASS")


if __name__ == "__main__":
    main()
