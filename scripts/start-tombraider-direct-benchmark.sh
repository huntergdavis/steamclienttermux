#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER:-$HOME/start-tombraider-direct-dispatch}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-direct-benchmark: launcher is unavailable: %s\n' \
        "$launcher" >&2
    exit 1
}

export TOMB_RAIDER_DIRECT_MODE=tombraider-benchmark
export TOMB_RAIDER_DIRECT_CHILD_PRELOAD=lean
if [[ -n ${STEAM_ARM64_FEX_PROFILE:-} ]]; then
    export STEAM_ARM64_DIRECT_FEX_PROFILE=$STEAM_ARM64_FEX_PROFILE
fi
export STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-60}
export STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-60}
export STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300}
exec "$launcher" "$@"
