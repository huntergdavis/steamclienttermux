#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}
[[ -f $benchmark_runner && ! -L $benchmark_runner && -x $benchmark_runner ]] || {
    printf 'test-tomb-raider-direct-fex-offline-compiled-single-40c-ceiling: benchmark runner is unavailable or unsafe: %s\n' \
        "$benchmark_runner" >&2
    exit 1
}
# The Android foreground controller was introduced by the BVB path and still
# keys X11 promotion off this bounded handoff token. Emit it before entering
# the generic glibc benchmark runner so Termux cannot remain foregrounded
# during the timed scene.
printf '%s\n' 'Starting Tomb Raider BVB probe: workload=glibc-fex-offline-benchmark'
exec "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --fex-code-cache compiled \
    --startup-topology full \
    --start-temperature-ceiling-c 40 \
    --warmups 0 \
    --runs 1 \
    "$@"
