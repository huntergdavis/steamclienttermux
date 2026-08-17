#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

steam_start="${STEAM_START_SCRIPT:-$HOME/start-steam-native.sh}"
[[ -x "$steam_start" ]] || {
    printf 'start-tombraider-native: native Steam launcher is unavailable: %s\n' \
        "$steam_start" >&2
    exit 1
}

# Keep the same direct, backgrounded Tomb Raider route as start-tombraider.sh,
# but select the no-PRoot Steam/CEF host. Additional game arguments are kept.
export STEAM_BACKGROUND=1
exec "$steam_start" --appid 203160 -- -nolauncher "$@"
