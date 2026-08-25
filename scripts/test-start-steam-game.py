#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts/start-steam-game.py"
WRAPPER = ROOT / "scripts/start-tombraider.sh"
MANIFEST = ROOT / "config/game-launch-profiles.json"
INSTALLER = ROOT / "scripts/install-project-files.sh"


def run(tool: Path, *arguments: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(tool), *arguments],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-game-profile.") as directory:
        root = Path(directory)
        home = root / "home"
        base = home / "steam-arm64"
        (base / "config").mkdir(parents=True)
        manifest = base / "config/game-launch-profiles.json"
        manifest.write_bytes(MANIFEST.read_bytes())
        launcher = home / "start-tombraider-direct-dispatch"
        launcher.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"${TOMB_RAIDER_DIRECT_MODE-<absent>}\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        environment = {
            **os.environ,
            "STEAM_ARM64_HOME": str(home),
            "STEAM_ARM64_BASE": str(base),
        }

        checked = run(TOOL, "203160", "--dry-run", environment=environment)
        assert checked.returncode == 0, checked.stderr
        report = json.loads(checked.stdout)
        assert report == {
            "appid": 203160,
            "arguments": [],
            "environment": {},
            "launcher": str(launcher),
            "mode": "play",
            "name": "Tomb Raider (2013)",
            "route": "optimized",
        }

        played = run(TOOL, "203160", environment=environment)
        assert played.returncode == 0, played.stderr
        assert played.stdout.splitlines()[-1] == "<absent>"

        benchmarked = run(
            TOOL, "203160", "--mode", "benchmark", environment=environment
        )
        assert benchmarked.returncode == 0, benchmarked.stderr
        assert benchmarked.stdout.splitlines()[-1] == "tombraider-benchmark"

        generic = home / "start-steam.sh"
        generic.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$STEAM_BACKGROUND|$*\"\n",
            encoding="utf-8",
        )
        generic.chmod(0o700)
        unknown_check = run(TOOL, "999999", "--dry-run", environment=environment)
        assert unknown_check.returncode == 0, unknown_check.stderr
        assert json.loads(unknown_check.stdout) == {
            "appid": 999999,
            "arguments": ["--appid", "999999"],
            "environment": {"STEAM_BACKGROUND": "1"},
            "launcher": str(generic),
            "mode": "play",
            "name": "Steam AppID 999999",
            "route": "generic",
        }
        unknown = run(TOOL, "999999", environment=environment)
        assert unknown.returncode == 0, unknown.stderr
        assert unknown.stdout.splitlines()[-1] == "1|--appid 999999"
        unsupported_mode = run(
            TOOL, "999999", "--mode", "benchmark", environment=environment
        )
        assert unsupported_mode.returncode != 0
        assert "has no optimized 'benchmark' mode" in unsupported_mode.stderr

        launcher.unlink()
        launcher.symlink_to(TOOL)
        linked = run(TOOL, "203160", environment=environment)
        assert linked.returncode != 0
        assert "regular non-symlink" in linked.stderr

        wrapper_home = root / "wrapper-home"
        wrapper_home.mkdir()
        game_result = root / "game-result"
        stock_result = root / "stock-result"
        game = wrapper_home / "game"
        game.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$GAME_RESULT\"\n",
            encoding="utf-8",
        )
        game.chmod(0o700)
        stock = wrapper_home / "stock"
        stock.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$STOCK_RESULT\"\n",
            encoding="utf-8",
        )
        stock.chmod(0o700)
        wrapper_environment = {
            **os.environ,
            "STEAM_GAME_START_SCRIPT": str(game),
            "STEAM_START_SCRIPT": str(stock),
            "GAME_RESULT": str(game_result),
            "STOCK_RESULT": str(stock_result),
        }
        assert run(Path("/bin/bash"), str(WRAPPER), environment=wrapper_environment).returncode == 0
        assert game_result.read_text().strip() == "203160"
        assert run(
            Path("/bin/bash"), str(WRAPPER), "-benchmark", environment=wrapper_environment
        ).returncode == 0
        assert game_result.read_text().strip() == "203160 --mode benchmark"
        assert run(
            Path("/bin/bash"),
            str(WRAPPER),
            "--stock",
            "-benchmark",
            environment=wrapper_environment,
        ).returncode == 0
        assert stock_result.read_text().strip() == "--appid 203160 -- -nolauncher -benchmark"
        assert run(
            Path("/bin/bash"), str(WRAPPER), "unexpected", environment=wrapper_environment
        ).returncode == 2

    installer = INSTALLER.read_text(encoding="utf-8")
    assert '"$HOME/start-steam-game" 700' in installer
    assert '"$base/config/game-launch-profiles.json" 600' in installer
    print("PASS: AppID launcher uses generic fallback and reviewed optimizations")


if __name__ == "__main__":
    main()
