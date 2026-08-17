#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER:-$HOME/start-tombraider-direct-dispatch}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-direct-lean: launcher is unavailable: %s\n' \
        "$launcher" >&2
    exit 1
}

export TOMB_RAIDER_DIRECT_CHILD_PRELOAD=lean
exec "$launcher" "$@"
