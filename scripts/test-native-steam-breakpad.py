#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "crash_dir=$runtime_dir/dumps" in source
    assert '"$runtime_dir" "$crash_dir"' in source
    assert 'BREAKPAD_DUMP_LOCATION="$crash_dir"' in source
    assert "! -L $crash_dir" in source
    print("native Steam Breakpad path tests: PASS")


if __name__ == "__main__":
    main()
