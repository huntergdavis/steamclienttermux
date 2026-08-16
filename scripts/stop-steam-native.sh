#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

native_launcher=${STEAM_ARM64_NATIVE_LAUNCHER:-$HOME/bin/steam-arm-native}
stop_script=${STEAM_STOP_SCRIPT:-$HOME/stop-steam.sh}

[[ -x $native_launcher ]] || {
    printf 'stop-steam-native: launcher is unavailable: %s\n' \
        "$native_launcher" >&2
    exit 1
}
[[ -x $stop_script ]] || {
    printf 'stop-steam-native: session wrapper is unavailable: %s\n' \
        "$stop_script" >&2
    exit 1
}

export STEAM_ARM64_LAUNCHER=$native_launcher
exec "$stop_script" "$@"
