#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
dispatcher=${TOMB_RAIDER_DIRECT_DISPATCHER:-$base/compat-bin/pressure-vessel-direct-dispatch.py}
default_python=/data/data/com.termux/files/usr/bin/python3
python=${TOMB_RAIDER_DIRECT_PYTHON:-$default_python}
launcher=${TOMB_RAIDER_DIRECT_LAUNCHER:-$HOME/start-steam-native.sh}
prepare=${TOMB_RAIDER_DIRECT_PREPARE:-$base/compat-bin/prepare-proton-direct-wine.py}
affinity=${TOMB_RAIDER_DIRECT_AFFINITY:-$base/compat-bin/set-tombraider-affinity.py}
mode=${TOMB_RAIDER_DIRECT_MODE:-tombraider}
diagnostics=${TOMB_RAIDER_DIRECT_DIAGNOSTICS:-0}
child_preload=${TOMB_RAIDER_DIRECT_CHILD_PRELOAD:-full}
raknet_nice=${TOMB_RAIDER_RAKNET_NICE:-}
socket=$base/run/native-runtime-dispatch/dispatch.sock
state=$base/run/tombraider-direct-dispatch.state

fail() {
    printf 'start-tombraider-direct-dispatch: %s\n' "$*" >&2
    exit 1
}

[[ $mode == proton-entry-smoke || $mode == proton-cmd-smoke ||
    $mode == proton-arm64-cmd-smoke || $mode == tombraider ||
    $mode == tombraider-benchmark || $mode == tombraider-diagnostic ]] ||
    fail "unsupported direct-dispatch mode: $mode"
[[ $diagnostics == 0 || $diagnostics == 1 ]] ||
    fail 'TOMB_RAIDER_DIRECT_DIAGNOSTICS must be 0 or 1'
[[ $child_preload == full || $child_preload == lean ||
    $child_preload == lean-tmp-only || $child_preload == lean-debug-wait ]] ||
    fail 'TOMB_RAIDER_DIRECT_CHILD_PRELOAD must be full, lean, lean-tmp-only, or lean-debug-wait'
if [[ -n $raknet_nice ]]; then
    [[ $raknet_nice =~ ^[0-9]+$ ]] && (( raknet_nice <= 19 )) ||
        fail 'TOMB_RAIDER_RAKNET_NICE must be an integer from 0 through 19'
fi
[[ -d $base/run && ! -L $base/run && -d $base/logs && ! -L $base/logs ]] ||
    fail "Steam run or log directory is unavailable below $base"
[[ -x $python && (! -L $python || $python == "$default_python") ]] ||
    fail "Termux Python is unavailable: $python"
[[ -f $dispatcher && ! -L $dispatcher ]] ||
    fail "direct dispatcher is unavailable: $dispatcher"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "native Steam launcher is unavailable: $launcher"
[[ -x $prepare && ! -L $prepare ]] ||
    fail "Proton direct Wine preparation tool is unavailable: $prepare"
if [[ $mode == tombraider || $mode == tombraider-benchmark ||
    $mode == tombraider-diagnostic ]]; then
    [[ -f $affinity && ! -L $affinity ]] ||
        fail "Tomb Raider affinity guard is unavailable: $affinity"
fi

"$python" "$prepare" prepare --base "$base"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
server_log=$base/logs/tombraider-direct-$mode-$child_preload-$stamp.log
launcher_log=$base/logs/tombraider-direct-launcher-$mode-$child_preload-$stamp.log
server_pid=
affinity_pid=
affinity_log=
cleanup() {
    if [[ -n ${affinity_pid:-} ]] && kill -0 "$affinity_pid" 2>/dev/null; then
        kill -TERM "$affinity_pid" 2>/dev/null || true
        wait "$affinity_pid" 2>/dev/null || true
    fi
    if [[ -n ${server_pid:-} ]] && kill -0 "$server_pid" 2>/dev/null; then
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM

STEAM_ARM64_DIRECT_DIAGNOSTICS=$diagnostics \
STEAM_ARM64_DIRECT_CHILD_PRELOAD=$child_preload \
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

if [[ $mode == tombraider || $mode == tombraider-benchmark ||
    $mode == tombraider-diagnostic ]]; then
    affinity_log=$base/logs/tombraider-direct-affinity-$stamp.log
    affinity_arguments=(--watch --raknet-cpu1 --steam-base "$base")
    if [[ -n $raknet_nice ]]; then
        affinity_arguments+=(--raknet-nice "$raknet_nice")
    fi
    "$python" "$affinity" "${affinity_arguments[@]}" \
        --wait-for-cpu-log \
        --poll-seconds 0.25 \
        --lock-file "$base/runtime/tomb-raider-affinity.lock" \
        >"$affinity_log" 2>&1 &
    affinity_pid=$!
fi

printf 'pid=%s\nmode=%s\nchild_preload=%s\nserver_pid=%s\nserver_log=%s\nlauncher_log=%s\naffinity_log=%s\nstatus=launching\n' \
    "$$" "$mode" "$child_preload" "$server_pid" "$server_log" \
    "$launcher_log" "$affinity_log" >"$state"

set +e
game_arguments=(-nolauncher)
if [[ $mode == tombraider-benchmark ]]; then
    game_arguments+=(-benchmark)
fi
STEAM_ARM64_BWRAP_DIRECT=1 \
STEAM_BACKGROUND=1 \
STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-180} \
STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-300} \
STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300} \
"$launcher" --appid 203160 -- "${game_arguments[@]}" >"$launcher_log" 2>&1
launcher_status=$?
if (( launcher_status != 0 )) && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
fi
wait "$server_pid"
server_status=$?
set -e
server_pid=
if [[ -n ${affinity_pid:-} ]] && kill -0 "$affinity_pid" 2>/dev/null; then
    kill -TERM "$affinity_pid" 2>/dev/null || true
    wait "$affinity_pid" 2>/dev/null || true
fi
affinity_pid=

printf 'pid=%s\nmode=%s\nchild_preload=%s\nserver_log=%s\nlauncher_log=%s\naffinity_log=%s\nstatus=complete\nlauncher_status=%s\nserver_status=%s\n' \
    "$$" "$mode" "$child_preload" "$server_log" "$launcher_log" \
    "$affinity_log" "$launcher_status" "$server_status" >"$state"
printf 'Tomb Raider direct dispatch completed: mode=%s child_preload=%s launcher=%s server=%s server_log=%s launcher_log=%s\n' \
    "$mode" "$child_preload" "$launcher_status" "$server_status" \
    "$server_log" "$launcher_log"
if (( launcher_status != 0 )); then
    exit "$launcher_status"
fi
exit "$server_status"
