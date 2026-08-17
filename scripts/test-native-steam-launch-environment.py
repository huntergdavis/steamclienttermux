#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "dbus-daemon bash; do" in source
    assert 'if ! bash "$session_tool" status' in source
    assert 'bash "$session_tool" start' in source
    assert '\n    "$session_tool" start\n' not in source
    print("native Steam launch-environment tests: PASS")


if __name__ == "__main__":
    main()
