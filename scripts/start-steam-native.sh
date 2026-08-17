#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

native_launcher=${STEAM_ARM64_NATIVE_LAUNCHER:-$HOME/bin/steam-arm-native}
start_script=${STEAM_START_SCRIPT:-$HOME/start-steam.sh}
base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
webhelper_patch=$base/patch-steamwebhelper-native.sh

[[ -x $native_launcher ]] || {
    printf 'start-steam-native: launcher is unavailable: %s\n' \
        "$native_launcher" >&2
    exit 1
}
[[ -x $start_script ]] || {
    printf 'start-steam-native: session wrapper is unavailable: %s\n' \
        "$start_script" >&2
    exit 1
}
[[ -x $webhelper_patch ]] || {
    printf 'start-steam-native: webhelper patch is unavailable: %s\n' \
        "$webhelper_patch" >&2
    exit 1
}

"$webhelper_patch"

export STEAM_ARM64_LAUNCHER=$native_launcher
exec "$start_script" "$@"
