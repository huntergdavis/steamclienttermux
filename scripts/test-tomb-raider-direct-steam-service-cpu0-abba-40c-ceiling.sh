#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}

[[ -f $benchmark_runner && ! -L $benchmark_runner && -x $benchmark_runner ]] || {
    printf 'test-tomb-raider-direct-steam-service-cpu0-abba-40c-ceiling: benchmark runner is unavailable or unsafe: %s\n' \
        "$benchmark_runner" >&2
    exit 1
}

exec "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --startup-topology full \
    --runs 4 \
    --steam-service-isolation-recorded-passes 2,3 \
    --start-temperature-ceiling-c 40 \
    "$@"
