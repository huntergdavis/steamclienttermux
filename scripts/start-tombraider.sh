#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

steam_start="${STEAM_START_SCRIPT:-$HOME/start-steam.sh}"
[[ -x "$steam_start" ]] || {
    printf 'start-tombraider: Steam launcher is unavailable: %s\n' \
        "$steam_start" >&2
    exit 1
}

# TombRaider.exe itself advertises both -nolauncher and -benchmark. Skip the
# graphics setup dialog by default; any additional arguments are preserved, so
# `~/start-tombraider.sh -benchmark` starts its built-in benchmark directly.
export STEAM_BACKGROUND=1
exec "$steam_start" --appid 203160 -- -nolauncher "$@"
