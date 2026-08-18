#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER:-$HOME/start-tombraider-direct-dispatch}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-direct-diagnostic: launcher is unavailable: %s\n' \
        "$launcher" >&2
    exit 1
}

export TOMB_RAIDER_DIRECT_MODE=tombraider-diagnostic
export TOMB_RAIDER_DIRECT_CHILD_PRELOAD=lean
export STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-60}
export STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-60}
export STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-120}
exec "$launcher" "$@"
