#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).with_name("start-steam.sh")


def parse(*arguments, background=None):
    environment = os.environ.copy()
    environment["START_STEAM_PARSE_ONLY"] = "1"
    if background is not None:
        environment["STEAM_BACKGROUND"] = str(background)
    else:
        environment.pop("STEAM_BACKGROUND", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
    lines = result.stdout.splitlines()
    values = dict(line.split("=", 1) for line in lines[:3])
    values["args"] = [line.removeprefix("arg=") for line in lines[3:]]
    return values


def main():
    assert parse() == {"appid": "", "background": "0", "argc": "0", "args": []}
    assert parse("203160", "-nolauncher", "-benchmark") == {
        "appid": "203160",
        "background": "1",
        "argc": "5",
        "args": ["-silent", "-applaunch", "203160", "-nolauncher", "-benchmark"],
    }
    assert parse("--appid", "203160", "--", "-nolauncher") == {
        "appid": "203160",
        "background": "1",
        "argc": "4",
        "args": ["-silent", "-applaunch", "203160", "-nolauncher"],
    }
    assert parse("-console", "-applaunch", "12210", "-foo") == {
        "appid": "12210",
        "background": "0",
        "argc": "4",
        "args": ["-console", "-applaunch", "12210", "-foo"],
    }
    assert parse("-console", "-applaunch", "12210", background=1)["args"] == [
        "-silent",
        "-console",
        "-applaunch",
        "12210",
    ]
    assert parse("203160", "-silent")["args"] == [
        "-applaunch",
        "203160",
        "-silent",
    ]

    invalid = subprocess.run(
        ["bash", str(SCRIPT), "--appid", "bad"],
        env={**os.environ, "START_STEAM_PARSE_ONLY": "1"},
        text=True,
        capture_output=True,
    )
    assert invalid.returncode != 0
    assert "positive numeric Steam AppID" in invalid.stderr
    print("start-steam argument tests: ok")


if __name__ == "__main__":
    main()
