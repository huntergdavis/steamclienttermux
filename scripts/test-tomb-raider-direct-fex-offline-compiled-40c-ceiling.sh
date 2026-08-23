#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}
[[ -f $benchmark_runner && ! -L $benchmark_runner && -x $benchmark_runner ]] || {
    printf 'test-tomb-raider-direct-fex-offline-compiled-40c-ceiling: benchmark runner is unavailable or unsafe: %s\n' \
        "$benchmark_runner" >&2
    exit 1
}
exec "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --fex-code-cache compiled \
    --startup-topology full \
    --start-temperature-ceiling-c 40 \
    "$@"
