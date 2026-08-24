#!/usr/bin/env python3
"""Launch a reviewed Steam AppID through its optimized direct profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat


PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
LAUNCHER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def fail(message: str) -> None:
    raise SystemExit(f"start-steam-game: {message}")


def regular_file(path: Path, label: str, *, executable: bool = False) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is unavailable: {path}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"{label} must be a regular non-symlink file: {path}")
    if executable and not os.access(path, os.X_OK):
        fail(f"{label} is not executable: {path}")
    return path


def load_profile(path: Path, appid: int, mode: str) -> tuple[str, str, dict[str, str]]:
    regular_file(path, "game profile manifest")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"game profile manifest is invalid: {error}")
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        fail("game profile manifest schema is unsupported")
    games = payload.get("games")
    if not isinstance(games, dict):
        fail("game profile manifest has no games object")
    profile = games.get(str(appid))
    if not isinstance(profile, dict):
        supported = ", ".join(sorted(games, key=lambda item: int(item)))
        fail(f"AppID {appid} has no optimized profile (supported: {supported or 'none'})")
    name = profile.get("name")
    launcher = profile.get("launcher")
    modes = profile.get("modes")
    if not isinstance(name, str) or not name or len(name) > 128:
        fail(f"AppID {appid} has an invalid name")
    if not isinstance(launcher, str) or LAUNCHER_NAME.fullmatch(launcher) is None:
        fail(f"AppID {appid} has an invalid launcher name")
    if not isinstance(modes, dict) or mode not in modes:
        available = ", ".join(sorted(modes)) if isinstance(modes, dict) else "none"
        fail(f"AppID {appid} does not support mode {mode!r} (available: {available})")
    environment = modes[mode]
    if not isinstance(environment, dict) or len(environment) > 32:
        fail(f"AppID {appid} mode {mode!r} has an invalid environment")
    validated: dict[str, str] = {}
    for key, value in environment.items():
        if (
            not isinstance(key, str)
            or ENVIRONMENT_NAME.fullmatch(key) is None
            or not isinstance(value, str)
            or len(value) > 1024
            or "\0" in value
        ):
            fail(f"AppID {appid} mode {mode!r} contains an invalid environment entry")
        validated[key] = value
    return name, launcher, validated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch a Steam AppID through a reviewed optimized profile."
    )
    parser.add_argument("appid", type=int)
    parser.add_argument("--mode", default="play")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    if arguments.appid <= 0:
        parser.error("appid must be positive")
    if PROFILE_NAME.fullmatch(arguments.mode) is None:
        parser.error("--mode must be a lowercase profile name")

    home = Path(os.environ.get("STEAM_ARM64_HOME", Path.home()))
    base = Path(os.environ.get("STEAM_ARM64_BASE", home / "steam-arm64"))
    manifest = Path(
        os.environ.get(
            "STEAM_ARM64_GAME_PROFILES", base / "config/game-launch-profiles.json"
        )
    )
    name, launcher_name, additions = load_profile(
        manifest, arguments.appid, arguments.mode
    )
    launcher = regular_file(home / launcher_name, "optimized game launcher", executable=True)
    report = {
        "appid": arguments.appid,
        "name": name,
        "mode": arguments.mode,
        "launcher": str(launcher),
        "environment": additions,
    }
    if arguments.dry_run:
        print(json.dumps(report, sort_keys=True))
        return 0

    environment = dict(os.environ)
    environment.update(additions)
    print(
        f"start-steam-game: AppID {arguments.appid} ({name}), "
        f"mode={arguments.mode}, launcher={launcher}"
    )
    os.execve(launcher, [str(launcher)], environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
