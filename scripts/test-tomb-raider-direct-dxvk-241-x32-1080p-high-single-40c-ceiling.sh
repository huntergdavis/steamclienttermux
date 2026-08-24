#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

benchmark_runner=${TOMB_RAIDER_BENCHMARK_COMMAND:-$HOME/run-tombraider-native-benchmark}
benchmark_python=${TOMB_RAIDER_BENCHMARK_PYTHON:-/data/data/com.termux/files/usr/bin/python3}

if [[ ! -f "$benchmark_runner" || -L "$benchmark_runner" || ! -x "$benchmark_runner" ]]; then
    printf '1080p High benchmark runner is unavailable or unsafe: %s\n' "$benchmark_runner" >&2
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

printf 'Starting Tomb Raider BVB probe: workload=glibc-dxvk-241-x32-1080p-high-benchmark\n'
"$benchmark_python" "$benchmark_runner" \
    --backend direct \
    --profile safe \
    --game-profile 1080p-high \
    --fex-code-cache compiled \
    --dxvk-variant dxvk-2.4.1-x32 \
    --startup-topology full \
    --start-temperature-ceiling-c 40 \
    --warmups 0 \
    --runs 1 \
    "$@"
