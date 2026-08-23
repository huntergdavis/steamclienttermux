#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

exec "$HOME/steam-arm64/compat-bin/run-tombraider-native-benchmark.py" \
    --backend direct \
    --profile safe \
    --fex-code-cache on \
    --startup-topology full \
    --start-temperature-ceiling-c 40 \
    "$@"
