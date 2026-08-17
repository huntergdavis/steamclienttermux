#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

# RunCommandService does not inherit Termux's interactive termux-exec preload,
# so it cannot resolve the Python tool's /usr/bin/env shebang.  Keep this
# Android-executable broker on an absolute Termux shebang and invoke Python by
# its absolute path.
python=${TOMB_RAIDER_BENCHMARK_PYTHON:-/data/data/com.termux/files/usr/bin/python3}
runner=${TOMB_RAIDER_BENCHMARK_RUNNER:-$HOME/steam-arm64/compat-bin/run-tombraider-native-benchmark.py}

[[ -x $python ]] || {
    printf 'run-tombraider-native-benchmark: Python is unavailable: %s\n' "$python" >&2
    exit 1
}
[[ -f $runner && ! -L $runner ]] || {
    printf 'run-tombraider-native-benchmark: runner is unavailable or unsafe: %s\n' \
        "$runner" >&2
    exit 1
}

exec "$python" "$runner" "$@"
