#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
steam=$base/client/steamrtarm64/steam
start_script=${STEAM_NATIVE_START_SCRIPT:-$HOME/start-steam-native.sh}
wait_seconds=${STEAM_ARM64_GDB_WAIT:-180}
stamp=$(date +%Y%m%d-%H%M%S)
log=$base/logs/native-steam-gdb-$stamp.log
launch_log=$base/logs/native-steam-gdb-launch-$stamp.log
pid_file=$base/run/native-steam/debug-pid-$stamp

command -v gdb >/dev/null 2>&1 || {
    printf 'capture-native-steam-backtrace: gdb is unavailable\n' >&2
    exit 1
}
[[ -x $steam && ! -L $steam ]] || {
    printf 'capture-native-steam-backtrace: Steam is unavailable or unsafe: %s\n' \
        "$steam" >&2
    exit 1
}
[[ -x $start_script && ! -L $start_script ]] || {
    printf 'capture-native-steam-backtrace: launcher is unavailable or unsafe: %s\n' \
        "$start_script" >&2
    exit 1
}
[[ $wait_seconds =~ ^[1-9][0-9]*$ ]] || {
    printf 'capture-native-steam-backtrace: invalid wait: %s\n' \
        "$wait_seconds" >&2
    exit 1
}
mkdir -p "$base/logs"
[[ -d $base/logs && ! -L $base/logs ]] || {
    printf 'capture-native-steam-backtrace: unsafe log directory: %s\n' \
        "$base/logs" >&2
    exit 1
}
if pgrep -f "^$steam( |$)" >/dev/null 2>&1; then
    printf 'capture-native-steam-backtrace: Steam is already running\n' >&2
    exit 1
fi

printf 'Launching native Steam; launcher log: %s; backtrace log: %s\n' \
    "$launch_log" "$log"
[[ ! -e $pid_file && ! -L $pid_file ]] || {
    printf 'capture-native-steam-backtrace: debugger PID file exists: %s\n' \
        "$pid_file" >&2
    exit 1
}
nohup env STEAM_ARM64_DEBUG_PID_FILE="$pid_file" \
    "$start_script" "$@" >"$launch_log" 2>&1 </dev/null &
launcher_pid=$!

printf 'Waiting up to %ss for native Steam PID %s to produce\n' \
    "$wait_seconds" "$launcher_pid"
deadline=$((SECONDS + wait_seconds))
pid=
while (( SECONDS < deadline )); do
    if [[ -f $pid_file && ! -L $pid_file ]]; then
        read -r pid <"$pid_file"
        [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/status ]] && break
        printf 'capture-native-steam-backtrace: invalid debugger PID file: %s\n' \
            "$pid_file" >&2
        exit 1
    fi
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        printf 'capture-native-steam-backtrace: launcher exited before Steam; inspect %s\n' \
            "$launch_log" >&2
        exit 1
    fi
    sleep 0.02
done
[[ $pid =~ ^[1-9][0-9]*$ ]] || {
    printf 'capture-native-steam-backtrace: Steam did not appear\n' >&2
    exit 1
}

exec gdb -q -nx -batch \
    -ex 'set pagination off' \
    -ex 'set debuginfod enabled off' \
    -ex 'set print thread-events off' \
    -ex 'handle SIGSTOP nostop noprint nopass' \
    -ex 'handle SIGPIPE nostop noprint pass' \
    -ex 'handle SIGCHLD nostop noprint pass' \
    -ex 'continue' \
    -ex 'info threads' \
    -ex 'thread apply all backtrace' \
    -ex 'info registers' \
    -ex 'x/12i $pc-16' \
    -p "$pid" >"$log" 2>&1
