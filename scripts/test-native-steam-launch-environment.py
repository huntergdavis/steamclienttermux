#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "dbus-daemon bash grep; do" in source
    assert 'if ! bash "$session_tool" status' in source
    assert 'bash "$session_tool" start' in source
    assert '\n    "$session_tool" start\n' not in source
    assert 'cd "$client_root"' in source
    assert 'debug_pid_file=${STEAM_ARM64_DEBUG_PID_FILE:-}' in source
    assert 'debug_prefix=(run_stopped_for_debugger "$debug_pid_file")' in source
    assert '"${debug_prefix[@]}" env -u GLIBC_LD_LIBRARY_PATH' in source
    assert 'set +e' in source
    assert 'SSL_CERT_FILE="$ssl_cert_file"' in source
    assert 'SSL_CERT_DIR="$ssl_cert_dir"' in source
    assert 'FONTCONFIG_FILE="$fontconfig_file"' in source
    assert 'FONTCONFIG_PATH="$fontconfig_path"' in source
    assert 'FONTCONFIG_SYSROOT="$linux_root"' in source
    assert 'STEAM_ARM64_LINUX_ROOT="$linux_root"' in source
    assert 'TGCOMPAT_PROC_SELF_EXE="$client/steam"' in source
    assert 'robust_shim=${TGCOMPAT_ROBUST_SHIM:-' in source
    assert "grep -aFq 'TGCOMPAT_ROBUST_LIST'" in source
    assert 'TGCOMPAT_ROBUST_LIST=1' in source
    assert "preload=$tmp_shim:$robust_shim:$exec_shim:$termux_exec_hook" in source
    assert "grep -aFq 'TGCOMPAT_PROC_SELF_EXE'" in source
    print("native Steam launch-environment tests: PASS")


if __name__ == "__main__":
    main()
