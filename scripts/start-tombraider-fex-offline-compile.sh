#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
python=${TOMB_RAIDER_DIRECT_PYTHON:-/data/data/com.termux/files/usr/bin/python3}
prepare=${TOMB_RAIDER_FEX_OFFLINE_PREPARE:-$base/compat-bin/prepare-tombraider-fex-offline-cache.py}
launcher=${TOMB_RAIDER_FEX_OFFLINE_LAUNCHER:-$HOME/start-tombraider-direct-dispatch}

[[ $# == 0 ]] || {
    printf '%s\n' 'start-tombraider-fex-offline-compile: this gate takes no arguments' >&2
    exit 1
}
[[ -f $prepare && ! -L $prepare ]] || {
    printf 'start-tombraider-fex-offline-compile: preparation tool is unavailable: %s\n' "$prepare" >&2
    exit 1
}
[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-tombraider-fex-offline-compile: launcher is unavailable: %s\n' "$launcher" >&2
    exit 1
}

if [[ -f $base/cache/fex-code-cache/tombraider-203160-offline-7efb8f8e/result.json &&
      ! -L $base/cache/fex-code-cache/tombraider-203160-offline-7efb8f8e/result.json ]]; then
    "$python" "$prepare" refresh --base "$base"
else
    "$python" "$prepare" prepare --base "$base"
fi
set +e
TOMB_RAIDER_DIRECT_MODE=fex-offline-compile \
TOMB_RAIDER_DIRECT_CHILD_PRELOAD=full \
TOMB_RAIDER_RAKNET_RECV_SLEEP_US=0 \
TOMB_RAIDER_FEX_CODE_CACHE=on \
    "$launcher"
status=$?
set -e
(( status == 0 )) || exit "$status"
"$python" "$prepare" verify --base "$base"
