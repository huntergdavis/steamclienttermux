#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

python=${TOMB_RAIDER_FOREGROUND_PYTHON:-/data/data/com.termux/files/usr/bin/python3}
tool=${TOMB_RAIDER_FOREGROUND_TOOL:-$HOME/steam-arm64/compat-bin/run-tombraider-bvb-foreground.py}

[[ -x $python ]] || {
    printf 'start-tombraider-bvb-foreground: Python is unavailable: %s\n' "$python" >&2
    exit 1
}
[[ -x $tool && ! -L $tool ]] || {
    printf 'start-tombraider-bvb-foreground: controller is unavailable or unsafe: %s\n' \
        "$tool" >&2
    exit 1
}

exec "$python" "$tool" "$@"
