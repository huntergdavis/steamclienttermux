#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

trace_root=${STEAM_ARM64_TRACE_ROOT:-${PREFIX:?}/tmp}
start_script=${STEAM_NATIVE_START_SCRIPT:-$HOME/start-steam-native.sh}
trace_timeout=${STEAM_ARM64_TRACE_TIMEOUT:-120}
stamp=$(date +%Y%m%d-%H%M%S)
trace=$trace_root/native-steam-trace-$stamp.txt

command -v strace >/dev/null 2>&1 || {
    printf 'trace-steam-native: strace is unavailable\n' >&2
    exit 1
}
[[ -d $trace_root && ! -L $trace_root ]] || {
    printf 'trace-steam-native: unsafe trace directory: %s\n' "$trace_root" >&2
    exit 1
}
[[ -x $start_script && ! -L $start_script ]] || {
    printf 'trace-steam-native: launcher is unavailable or unsafe: %s\n' \
        "$start_script" >&2
    exit 1
}
[[ $trace_timeout =~ ^[1-9][0-9]*$ ]] || {
    printf 'trace-steam-native: invalid timeout: %s\n' "$trace_timeout" >&2
    exit 1
}

printf 'Tracing native Steam launch to %s\n' "$trace"
exec timeout --signal=TERM --kill-after=5 "$trace_timeout" \
    strace -f -tt -s 256 -yy -o "$trace" "$start_script" "$@"
