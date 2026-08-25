#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
default_python=/data/data/com.termux/files/usr/bin/python3
python=${NO_MANS_SKY_DIRECT_PYTHON:-$default_python}
dispatcher=${NO_MANS_SKY_DIRECT_DISPATCHER:-$base/compat-bin/pressure-vessel-direct-dispatch.py}
launcher=${NO_MANS_SKY_DIRECT_LAUNCHER:-$HOME/start-steam.sh}
prepare=${NO_MANS_SKY_DIRECT_PREPARE:-$base/compat-bin/prepare-proton-direct-wine.py}
tool_check=$base/compat-bin/prepare-no-mans-sky-proton.py
summary_tool=${NO_MANS_SKY_SUMMARIZER:-$base/compat-bin/summarize-mangohud-csv.py}
summary_start=${NO_MANS_SKY_SUMMARY_START_SECONDS:-60}
prefix=$base/removable-library-compatdata/275850/pfx
socket=$base/run/native-runtime-dispatch/dispatch.sock
stamp=$(date -u +%Y%m%dT%H%M%SZ)
server_log=$base/logs/no-mans-sky-direct-$stamp-$$.log
launcher_log=$base/logs/no-mans-sky-launcher-$stamp-$$.log
request_timeout=${NO_MANS_SKY_DIRECT_REQUEST_TIMEOUT:-300}
mangohud=${NO_MANS_SKY_MANGOHUD:-0}
xinput=${NO_MANS_SKY_XINPUT:-1}
mangohud_dir=
mangohud_config=
summary_tmp=
server_pid=

fail() {
    printf 'start-no-mans-sky-direct: %s\n' "$*" >&2
    exit 1
}

stop_server() {
    local pid=${server_pid:-} attempt
    if [[ $pid =~ ^[0-9]+$ && -d /proc/$pid ]]; then
        kill -TERM "$pid" 2>/dev/null || true
        for attempt in $(seq 1 100); do
            [[ -d /proc/$pid ]] || break
            sleep 0.05
        done
        if [[ -d /proc/$pid ]]; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
        wait "$pid" 2>/dev/null || true
    fi
    server_pid=
    if [[ -S $socket && ! -L $socket &&
          $(stat -c %u -- "$socket") == $(id -u) &&
          $(stat -c %a -- "$socket") == 600 ]]; then
        unlink -- "$socket"
    fi
}

cleanup() {
    stop_server
    if [[ -n ${summary_tmp:-} && -f $summary_tmp && ! -L $summary_tmp ]]; then
        rm -f -- "$summary_tmp"
    fi
}
trap cleanup EXIT HUP INT TERM

[[ -d $base/run/native-runtime-dispatch &&
   ! -L $base/run/native-runtime-dispatch &&
   -d $base/logs && ! -L $base/logs ]] ||
    fail 'Steam run or log directory is unavailable'
[[ -x $python && (! -L $python || $python == "$default_python") ]] ||
    fail "Termux Python is unavailable: $python"
[[ -f $dispatcher && ! -L $dispatcher ]] ||
    fail "direct dispatcher is unavailable: $dispatcher"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "Steam AppID launcher is unavailable: $launcher"
[[ -x $prepare && ! -L $prepare ]] ||
    fail "Proton preparation tool is unavailable: $prepare"
[[ -f $tool_check && ! -L $tool_check ]] ||
    fail "contained NMS Proton validator is unavailable: $tool_check"
[[ -d $prefix && ! -L $prefix ]] ||
    fail "No Man's Sky Proton prefix is unavailable: $prefix"
[[ ! -e $socket && ! -L $socket ]] ||
    fail "another direct dispatcher owns the socket: $socket"
[[ $request_timeout =~ ^[0-9]+$ ]] &&
    (( request_timeout >= 1 && request_timeout <= 900 )) ||
    fail 'NO_MANS_SKY_DIRECT_REQUEST_TIMEOUT must be 1..900 seconds'
[[ $mangohud == 0 || $mangohud == 1 ]] ||
    fail 'NO_MANS_SKY_MANGOHUD must be 0 or 1'
[[ $xinput == 0 || $xinput == 1 ]] ||
    fail 'NO_MANS_SKY_XINPUT must be 0 or 1'

if [[ $mangohud == 1 ]]; then
    [[ -x $summary_tool && ! -L $summary_tool ]] ||
        fail "MangoHud summary tool is unavailable: $summary_tool"
    mangohud_dir=$base/logs/no-mans-sky-fps-$stamp-$$
    mkdir -m 700 -- "$mangohud_dir" ||
        fail "cannot create MangoHud output directory: $mangohud_dir"
    mangohud_config=$mangohud_dir/MangoHud.conf
    (set -o noclobber
        printf '%s\n' \
            'legacy_layout=0' \
            'cpu_stats=0' \
            'gpu_stats=0' \
            'battery=0' \
            'device_battery=' \
            'throttling_status=0' \
            'fps' \
            'fps_only=1' \
            'frametime=0' \
            'position=top-left' \
            'fps_metrics=avg,0.01,0.001' \
            'autostart_log=1' \
            'log_duration=1800' \
            'log_interval=100' \
            "output_folder=$mangohud_dir" \
            'benchmark_percentiles=97,AVG,1,0.1' \
            'log_versioning' >"$mangohud_config") ||
        fail "cannot create MangoHud config: $mangohud_config"
    chmod 600 "$mangohud_config"
fi

"$python" "$tool_check" check --base "$base"

"$python" "$prepare" prepare --base "$base" --wine-prefix "$prefix" \
    --window-background '0 0 0' --wine-app NMS.exe \
    --mouse-warp-override disable

(set -o noclobber; : >"$server_log") 2>/dev/null ||
    fail "cannot create server log: $server_log"
(set -o noclobber; : >"$launcher_log") 2>/dev/null ||
    fail "cannot create launcher log: $launcher_log"
chmod 600 "$server_log" "$launcher_log"

env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    STEAM_ARM64_DIRECT_CHILD_PRELOAD=full \
    STEAM_ARM64_DIRECT_FEX_PROFILE=safe \
    STEAM_ARM64_DIRECT_NMS_MANGOHUD=$mangohud \
    STEAM_ARM64_DIRECT_NMS_MANGOHUD_CONFIG=$mangohud_config \
    STEAM_ARM64_DIRECT_NMS_XINPUT=$xinput \
    "$python" "$dispatcher" serve --base "$base" --mode no-mans-sky \
    >"$server_log" 2>&1 &
server_pid=$!
for _ in $(seq 1 100); do
    [[ -S $socket ]] && break
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.1
done
if [[ ! -S $socket ]]; then
    sed -n '1,80p' "$server_log" >&2 || true
    fail 'direct dispatcher did not become ready'
fi

set +e
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    STEAM_ARM64_BWRAP_DIRECT=1 \
    STEAM_BACKGROUND=1 \
    STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-180} \
    STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-300} \
    STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300} \
    "$launcher" --appid 275850 >"$launcher_log" 2>&1
launcher_status=$?
if (( launcher_status != 0 )); then
    stop_server
    server_status=125
else
    request_seen=0
    for _ in $(seq 1 "$request_timeout"); do
        if grep -q '^REQUEST_RECEIVED=1 ' "$server_log"; then
            request_seen=1
            break
        fi
        kill -0 "$server_pid" 2>/dev/null || break
        sleep 1
    done
    if (( request_seen == 0 )); then
        printf 'start-no-mans-sky-direct: Steam accepted AppID 275850 but did not dispatch it within %s seconds\n' \
            "$request_timeout" >&2
        sed -n '1,80p' "$server_log" >&2 || true
        stop_server
        server_status=124
    else
        wait "$server_pid"
        server_status=$?
        server_pid=
    fi
fi
set -e

printf 'No Man\047s Sky direct dispatch complete: launcher=%s server=%s server_log=%s launcher_log=%s\n' \
    "$launcher_status" "$server_status" "$server_log" "$launcher_log"
if [[ $mangohud == 1 ]]; then
    printf 'No Man\047s Sky FPS log directory: %s\n' "$mangohud_dir"
    if (( launcher_status == 0 && server_status == 0 )); then
        mapfile -t csv_files < <(
            find "$mangohud_dir" -mindepth 1 -maxdepth 1 -type f -name '*.csv' -print
        )
        ((${#csv_files[@]} == 1)) ||
            fail "expected exactly one MangoHud CSV, found ${#csv_files[@]}"
        [[ ! -L ${csv_files[0]} ]] || fail 'MangoHud CSV is an unsafe link'
        summary_tmp=$(mktemp "$mangohud_dir/.summary.XXXXXX") ||
            fail 'cannot create temporary FPS summary'
        chmod 600 "$summary_tmp"
        "$summary_tool" "${csv_files[0]}" --start-seconds "$summary_start" \
            >"$summary_tmp" || fail 'MangoHud CSV summary failed'
        mv -- "$summary_tmp" "$mangohud_dir/summary.json"
        summary_tmp=
        printf 'No Man\047s Sky FPS summary: %s\n' "$mangohud_dir/summary.json"
    fi
fi
(( launcher_status == 0 )) || exit "$launcher_status"
exit "$server_status"
