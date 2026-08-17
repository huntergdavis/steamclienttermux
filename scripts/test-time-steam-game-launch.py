#!/usr/bin/env python3

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "time-steam-game-launch.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("time_steam_game_launch", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    module = load_tool()
    parsed = module.parse_log_time(
        "[2026-08-16 16:47:22] Game process added : AppID 203160"
    )
    assert parsed == datetime(2026, 8, 16, 16, 47, 22, tzinfo=timezone.utc)
    assert module.parse_log_time("no timestamp") is None

    processes = [
        module.Process(1, "pressure-vessel", "/tmp/prooted", ("/x/pressure-vessel-wrap",)),
        module.Process(2, "python3", "/tmp/prooted", ("python3", "/x/proton")),
        module.Process(3, "wine", "/tmp/prooted", ("/x/wine",)),
        module.Process(4, "wineserver", "/tmp/prooted", ("/x/wineserver",)),
        module.Process(
            5,
            "truncated-name",
            "/tmp/prooted",
            (r"S:\common\Tomb Raider\TombRaider.exe",),
        ),
    ]
    stages = module.stage_processes(processes, "TombRaider.exe")
    assert {name: process.pid for name, process in stages.items()} == {
        "pressure_vessel": 1,
        "proton": 2,
        "wine": 3,
        "wineserver": 4,
        "target_process": 5,
    }

    event = module.event_record(
        datetime(2026, 8, 16, 16, 47, 27, 250000, tzinfo=timezone.utc),
        parsed,
        pid=5,
    )
    assert event == {
        "observed_at": "2026-08-16T16:47:27.250+00:00",
        "seconds_after_runtime_launch": 5.25,
        "pid": 5,
    }
    first_seen, title, stable = module.update_window_stability(
        None, None, parsed, True, "Tomb Raider", 10.0
    )
    assert (first_seen, title, stable) == (parsed, "Tomb Raider", False)
    later = datetime(2026, 8, 16, 16, 47, 32, tzinfo=timezone.utc)
    assert module.update_window_stability(
        first_seen, title, later, True, "Tomb Raider", 10.0
    ) == (first_seen, title, True)
    assert module.update_window_stability(
        first_seen, title, later, False, None, 10.0
    ) == (None, None, False)
    first_attempt = module.attempt_record(
        1,
        "superseded_by_retry",
        datetime(2026, 8, 17, 7, 8, 9, tzinfo=timezone.utc),
        datetime(2026, 8, 17, 7, 8, 27, tzinfo=timezone.utc),
        {"pressure_vessel": event},
    )
    assert first_attempt == {
        "attempt": 1,
        "status": "superseded_by_retry",
        "steam_session_at": "2026-08-17T07:08:09.000+00:00",
        "runtime_launch_at": "2026-08-17T07:08:27.000+00:00",
        "seconds_session_to_runtime_launch": 18.0,
        "events": {"pressure_vessel": event},
    }
    print("Steam game launch timer tests: PASS")


if __name__ == "__main__":
    main()
