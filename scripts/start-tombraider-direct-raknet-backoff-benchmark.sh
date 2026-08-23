#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER:-$HOME/start-tombraider-direct-benchmark}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-direct-raknet-backoff-benchmark: launcher is unavailable: %s\n' \
        "$launcher" >&2
    exit 1
}

export STEAM_ARM64_BVB_VULKAN=0
export TOMB_RAIDER_RAKNET_RECV_SLEEP_US=1000
exec "$launcher" "$@"
