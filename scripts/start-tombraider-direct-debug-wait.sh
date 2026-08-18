#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${TOMB_RAIDER_DIRECT_DEBUG_LAUNCHER:-$HOME/start-tombraider-direct-lean}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-direct-debug-wait: launcher is unavailable: %s\n' \
        "$launcher" >&2
    exit 1
}

export STEAM_ARM64_DIRECT_FEX_STARTUP_SLEEP=${STEAM_ARM64_DIRECT_FEX_STARTUP_SLEEP:-30}
exec "$launcher" "$@"
