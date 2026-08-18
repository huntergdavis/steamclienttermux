#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}

[[ -f $benchmark_runner && ! -L $benchmark_runner && -x $benchmark_runner ]] || {
    printf 'test-tomb-raider-direct-safe-full-topology-cef-hold-pair-40c-ceiling: benchmark runner is unavailable or unsafe: %s\n' \
        "$benchmark_runner" >&2
    exit 1
}

exec "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --startup-topology full \
    --runs 2 \
    --steam-cef-hold-recorded-passes 2 \
    --start-temperature-ceiling-c 40 \
    "$@"
