#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
dispatcher=${TOMB_RAIDER_DIRECT_DISPATCHER:-$base/compat-bin/pressure-vessel-direct-dispatch.py}
default_python=/data/data/com.termux/files/usr/bin/python3
python=${TOMB_RAIDER_DIRECT_PYTHON:-$default_python}
launcher=${TOMB_RAIDER_DIRECT_LAUNCHER:-$HOME/start-steam-native.sh}
mode=${TOMB_RAIDER_DIRECT_MODE:-proton-entry-smoke}
socket=$base/run/native-runtime-dispatch/dispatch.sock
state=$base/run/tombraider-direct-dispatch.state

fail() {
    printf 'start-tombraider-direct-dispatch: %s\n' "$*" >&2
    exit 1
}

[[ $mode == proton-entry-smoke ]] ||
    fail "unsupported direct-dispatch mode: $mode"
[[ -d $base/run && ! -L $base/run && -d $base/logs && ! -L $base/logs ]] ||
    fail "Steam run or log directory is unavailable below $base"
[[ -x $python && (! -L $python || $python == "$default_python") ]] ||
    fail "Termux Python is unavailable: $python"
[[ -f $dispatcher && ! -L $dispatcher ]] ||
    fail "direct dispatcher is unavailable: $dispatcher"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "native Steam launcher is unavailable: $launcher"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
server_log=$base/logs/tombraider-direct-$mode-$stamp.log
server_pid=
cleanup() {
    if [[ -n ${server_pid:-} ]] && kill -0 "$server_pid" 2>/dev/null; then
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM

"$python" "$dispatcher" serve --base "$base" --mode "$mode" \
    >"$server_log" 2>&1 &
server_pid=$!
for _ in $(seq 1 100); do
    [[ -S $socket ]] && break
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.1
done
[[ -S $socket && -n $server_pid ]] || {
    sed -n '1,80p' "$server_log" >&2 || true
    fail 'direct dispatcher did not create its socket'
}

printf 'pid=%s\nmode=%s\nserver_pid=%s\nserver_log=%s\nstatus=launching\n' \
    "$$" "$mode" "$server_pid" "$server_log" >"$state"

set +e
STEAM_ARM64_BWRAP_DIRECT=1 \
STEAM_BACKGROUND=1 \
STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-180} \
STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-300} \
STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300} \
"$launcher" --appid 203160 -- -nolauncher
launcher_status=$?
wait "$server_pid"
server_status=$?
set -e
server_pid=

printf 'pid=%s\nmode=%s\nserver_log=%s\nstatus=complete\nlauncher_status=%s\nserver_status=%s\n' \
    "$$" "$mode" "$server_log" "$launcher_status" "$server_status" >"$state"
printf 'Tomb Raider direct dispatch completed: mode=%s launcher=%s server=%s log=%s\n' \
    "$mode" "$launcher_status" "$server_status" "$server_log"
exit "$launcher_status"
