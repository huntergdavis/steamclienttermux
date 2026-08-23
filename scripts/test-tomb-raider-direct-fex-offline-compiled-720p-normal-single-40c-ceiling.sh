#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}
benchmark_python=${TOMB_RAIDER_BENCHMARK_PYTHON:-/data/data/com.termux/files/usr/bin/python3}

if [[ ! -f "$benchmark_runner" || -L "$benchmark_runner" || ! -x "$benchmark_runner" ]]; then
    printf '720p Normal benchmark runner is unavailable or unsafe: %s\n' "$benchmark_runner" >&2
    exit 1
fi
benchmark_python=$(readlink -f -- "$benchmark_python") || {
    printf 'Termux benchmark Python could not be resolved\n' >&2
    exit 1
}
if [[ ! -f "$benchmark_python" || -L "$benchmark_python" || ! -x "$benchmark_python" ]]; then
    printf 'Termux benchmark Python is unavailable or unsafe: %s\n' "$benchmark_python" >&2
    exit 1
fi

# The foreground controller recognizes this legacy token as the point where
# Termux:X11 may safely take over Android top-app ownership.
printf 'Starting Tomb Raider BVB probe: workload=glibc-fex-offline-720p-normal-benchmark\n'
exec "$benchmark_python" "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --game-profile 720p-normal \
    --fex-code-cache compiled \
    --startup-topology full \
    --start-temperature-ceiling-c 40 \
    --warmups 0 \
    --runs 1 \
    "$@"
