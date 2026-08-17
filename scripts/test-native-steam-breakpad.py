#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "crash_dir=$runtime_dir/dumps" in source
    assert '"$runtime_dir" "$crash_dir"' in source
    assert 'BREAKPAD_DUMP_LOCATION="$crash_dir"' in source
    assert "! -L $crash_dir" in source
    assert "tmp_shim=${STEAM_ARM64_TMP_SHIM:-" in source
    assert "preload=$tmp_shim:$exec_shim:$termux_exec_hook" in source
    assert 'STEAM_ARM64_TMP_ROOT="$PREFIX/tmp"' in source
    print("native Steam Breakpad path tests: PASS")


if __name__ == "__main__":
    main()
