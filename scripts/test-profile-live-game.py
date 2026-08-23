#!/usr/bin/env python3

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "profile-live-game.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("profile_live_game", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_stat(pid, name, user_ticks, system_ticks, start_ticks, processor):
    # Fields following comm start at proc stat field 3 (state). Only the fields
    # parsed by the profiler need meaningful values.
    fields = ["S"] + ["0"] * 49
    fields[11] = str(user_ticks)
    fields[12] = str(system_ticks)
    fields[19] = str(start_ticks)
    fields[36] = str(processor)
    return f"{pid} ({name}) " + " ".join(fields)


def main():
    module = load_tool()
    parsed = module.parse_stat(fake_stat(42, "name with spaces", 100, 25, 900, 7))
    assert parsed == {
        "pid": 42,
        "name": "name with spaces",
        "ticks": 125,
        "start_ticks": 900,
        "processor": 7,
    }

    before = {
        42: {"pid": 42, "name": "game", "ticks": 100, "start_ticks": 10, "processor": 4},
        43: {"pid": 43, "name": "reused", "ticks": 100, "start_ticks": 11, "processor": 1},
    }
    after = {
        42: {"pid": 42, "name": "game", "ticks": 150, "start_ticks": 10, "processor": 7},
        43: {"pid": 43, "name": "reused", "ticks": 500, "start_ticks": 12, "processor": 2},
    }
    rows = module.delta_rows(before, after, elapsed=2.0, clock_ticks=100)
    assert rows == [{"pid": 42, "name": "game", "cpu_percent": 25.0, "processor": 7}]

    thread_before = {
        52: {
            "pid": 52,
            "owner_pid": 42,
            "name": "render",
            "ticks": 20,
            "start_ticks": 15,
            "processor": 4,
        }
    }
    thread_after = {
        52: {
            "pid": 52,
            "owner_pid": 42,
            "name": "render",
            "ticks": 80,
            "start_ticks": 15,
            "processor": 6,
        }
    }
    assert module.delta_rows(
        thread_before, thread_after, elapsed=2.0, clock_ticks=100
    ) == [
        {
            "pid": 52,
            "owner_pid": 42,
            "name": "render",
            "cpu_percent": 30.0,
            "processor": 6,
        }
    ]

    try:
        module.parse_stat("malformed")
    except ValueError:
        pass
    else:
        raise AssertionError("malformed stat record was accepted")

    print("Live game profiler tests: PASS")


if __name__ == "__main__":
    main()
