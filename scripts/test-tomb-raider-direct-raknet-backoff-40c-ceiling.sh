#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}
launcher=${TOMB_RAIDER_RAKNET_BACKOFF_BENCHMARK_LAUNCHER:-$HOME/start-tombraider-direct-raknet-backoff-benchmark}

[[ -f $benchmark_runner && ! -L $benchmark_runner && -x $benchmark_runner ]] || {
    printf 'test-tomb-raider-direct-raknet-backoff-40c-ceiling: benchmark runner is unavailable or unsafe: %s\n' \
        "$benchmark_runner" >&2
    exit 1
}
[[ -f $launcher && ! -L $launcher && -x $launcher ]] || {
    printf 'test-tomb-raider-direct-raknet-backoff-40c-ceiling: launcher is unavailable or unsafe: %s\n' \
        "$launcher" >&2
    exit 1
}

exec "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --startup-topology full \
    --launcher "$launcher" \
    --start-temperature-ceiling-c 40 \
    "$@"
