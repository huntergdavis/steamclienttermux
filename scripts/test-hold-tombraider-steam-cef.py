#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile


TOOL = Path(__file__).with_name("hold-tombraider-steam-cef.py")
AFFINITY = Path(__file__).with_name("set-tombraider-affinity.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proc_entry(root, pid, name, ppid, start, cmdline, cgroup=True):
    entry = root / str(pid)
    entry.mkdir()
    fields = ["S", str(ppid)] + ["0"] * 48
    fields[19] = str(start)
    (entry / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
    (entry / "cmdline").write_bytes(b"\0".join(cmdline) + b"\0")
    if cgroup:
        (entry / "cgroup").write_text("4:cpuset:/top-app\n2:cpu:/top-app\n")
    return entry


def main():
    tool = load(TOOL, "hold_cef")
    affinity = load(AFFINITY, "affinity")
    parsed = tool.parse_process_stat(
        "42 (name with spaces) S 7 " + "0 " * 17 + "900 " + "0 " * 10
    )
    assert parsed == {"state": "S", "ppid": 7, "start_ticks": 900}
    try:
        tool.parse_process_stat("malformed")
    except RuntimeError:
        pass
    else:
        raise AssertionError("malformed stat was accepted")

    with tempfile.TemporaryDirectory(prefix="hold-cef.") as directory:
        root = Path(directory)
        proc = root / "proc"
        proc.mkdir()
        base = root / "steam-arm64"
        steam = base / "client/steamrtarm64/steam"
        helper = base / "client/steamrtarm64/steamwebhelper"
        loader = root / ".local/share/tgcompat/glibc/hash/lib/ld-linux-aarch64.so.1"
        proc_entry(proc, 10, "steam", 1, 100, [str(steam).encode()])
        proc_entry(
            proc,
            20,
            "steamwebhelper",
            10,
            200,
            [str(loader).encode(), b"--argv0", str(helper).encode(), str(helper).encode()],
        )
        proc_entry(
            proc,
            21,
            "steamwebhelper",
            20,
            210,
            [str(loader).encode(), b"--argv0", str(helper).encode(), str(helper).encode()],
        )
        proc_entry(
            proc,
            22,
            "steamwebhelper",
            1,
            220,
            [
                str(loader).encode(),
                b"--argv0",
                str(helper).encode(),
                str(helper).encode(),
                b"--monitor-self-annotation=ptype=crashpad-handler",
                b"--type=crashpad-handler",
            ],
        )
        steam_pid, _entry = tool.find_exact_steam(affinity, base, proc)
        assert steam_pid == 10
        records = tool.validated_helpers(affinity, base, steam_pid, proc)
        assert {pid: row["start_ticks"] for pid, row in records.items()} == {
            20: 200,
            21: 210,
        }
        assert tool.is_crashpad_handler(proc / "22")
        assert tool.same_identities(records, records)
        changed = {pid: dict(row) for pid, row in records.items()}
        changed[21]["start_ticks"] = 211
        assert not tool.same_identities(records, changed)
        assert tool.pending_stopped_helpers(records, proc) == []
        stopped = (proc / "20/stat").read_text().replace(
            "(steamwebhelper) S", "(steamwebhelper) T"
        )
        (proc / "20/stat").write_text(stopped)
        assert tool.pending_stopped_helpers(records, proc) == [20]
        (proc / "20/stat").write_text(
            stopped.replace("(steamwebhelper) T", "(steamwebhelper) S")
        )
        (proc / "21/stat").write_text(
            "21 (steamwebhelper) S 99 " + "0 " * 17 + "210 " + "0 " * 10
        )
        try:
            tool.validated_helpers(affinity, base, steam_pid, proc)
        except RuntimeError as error:
            assert "not a descendant" in str(error)
        else:
            raise AssertionError("orphan helper was accepted")

    print("Steam CEF experimental hold tests: PASS")


if __name__ == "__main__":
    main()
