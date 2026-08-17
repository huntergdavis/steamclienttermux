#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "dbus-daemon bash; do" in source
    assert 'if ! bash "$session_tool" status' in source
    assert 'bash "$session_tool" start' in source
    assert '\n    "$session_tool" start\n' not in source
    assert 'cd "$client_root"\nset +e' in source
    assert 'SSL_CERT_FILE="$ssl_cert_file"' in source
    assert 'SSL_CERT_DIR="$ssl_cert_dir"' in source
    assert 'FONTCONFIG_FILE="$fontconfig_file"' in source
    assert 'FONTCONFIG_PATH="$fontconfig_path"' in source
    assert 'FONTCONFIG_SYSROOT="$linux_root"' in source
    print("native Steam launch-environment tests: PASS")


if __name__ == "__main__":
    main()
