#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
service=$base/bvb/bin/bvb-bridge-service
driver=$base/bvb/driver/libvulkan_freedreno.so
manifest=$base/bvb/icd.d/bvb_icd.aarch64.json
launcher=${TOMB_RAIDER_BVB_LAUNCHER:-$HOME/start-tombraider-direct-lean}
activity_launcher=${BVB_ACTIVITY_LAUNCHER:-am}
activity_component=${BVB_VISIBLE_HOST_COMPONENT:-io.github.huntergdavis.bvb.visiblehost/.VisibleHostActivity}
package_manager=${BVB_PACKAGE_MANAGER:-pm}
app_process=${BVB_APP_PROCESS:-/system/bin/app_process}
frame_client_class=io.github.huntergdavis.bvb.visiblehost.FrameTransportClient
run_dir=$base/run/bvb
log_dir=$base/logs
stamp=$(date -u +%Y%m%dT%H%M%SZ)
run_id=$stamp-$$
socket=$run_dir/tombraider-probe-$run_id.sock
frame_setup_socket=bvb-frame-$run_id
service_log=$log_dir/tombraider-bvb-service-$run_id.log
launcher_log=$log_dir/tombraider-bvb-launcher-$run_id.log
frame_client_log=$log_dir/tombraider-bvb-frame-client-$run_id.log
frame_result=$log_dir/tombraider-bvb-frame-$run_id.json
start_gate=$run_dir/tombraider-start-$run_id.gate
start_gate_waiting=$start_gate.waiting
start_gate_launcher_ready=$start_gate.launcher-ready
service_pid=
launcher_pid=
frame_client_pid=
activity_token=
activity_port=
helper_apk=
direct_diagnostics=${TOMB_RAIDER_DIRECT_DIAGNOSTICS:-0}

fail() {
    printf 'start-tombraider-bvb-probe: %s\n' "$*" >&2
    exit 1
}

process_is_running() {
    local pid="$1" stat_line remainder state
    [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/stat ]] || return 1
    IFS= read -r stat_line <"/proc/$pid/stat" || return 1
    remainder=${stat_line##*) }
    [[ $remainder != "$stat_line" ]] || return 1
    state=${remainder%% *}
    [[ $state != Z && $state != X ]]
}

cleanup() {
    if [[ -n ${launcher_pid:-} ]] && kill -0 "$launcher_pid" 2>/dev/null; then
        kill -TERM "$launcher_pid" 2>/dev/null || true
        wait "$launcher_pid" 2>/dev/null || true
    fi
    if [[ -n ${frame_client_pid:-} ]] &&
       kill -0 "$frame_client_pid" 2>/dev/null; then
        kill -TERM "$frame_client_pid" 2>/dev/null || true
        wait "$frame_client_pid" 2>/dev/null || true
    fi
    if [[ -n ${service_pid:-} ]] && kill -0 "$service_pid" 2>/dev/null; then
        kill -TERM "$service_pid" 2>/dev/null || true
        wait "$service_pid" 2>/dev/null || true
    fi
    if [[ -S $socket ]]; then
        unlink -- "$socket"
    fi
    for marker in "$start_gate" "$start_gate_waiting" \
        "$start_gate_launcher_ready"; do
        if [[ -f $marker && ! -L $marker ]]; then
            unlink -- "$marker"
        fi
    done
}
trap cleanup EXIT HUP INT TERM

[[ -d $base && ! -L $base && -d $log_dir && ! -L $log_dir ]] ||
    fail "Steam base or log directory is unavailable below $base"
[[ -x $service && ! -L $service ]] ||
    fail "installed Bionic bridge service is unavailable: $service"
[[ -r $driver && -f $driver && ! -L $driver ]] ||
    fail "private Turnip Vulkan driver is unavailable: $driver"
[[ -f $manifest && ! -L $manifest ]] ||
    fail "installed BVB ICD manifest is unavailable: $manifest"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "Tomb Raider direct launcher is unavailable: $launcher"
[[ $direct_diagnostics =~ ^[01]$ ]] ||
    fail 'TOMB_RAIDER_DIRECT_DIAGNOSTICS must be 0 or 1'
command -v "$activity_launcher" >/dev/null 2>&1 ||
    fail "Android Activity launcher is unavailable: $activity_launcher"
command -v "$package_manager" >/dev/null 2>&1 ||
    fail "Android package manager is unavailable: $package_manager"
[[ $app_process == /* && -x $app_process && ! -L $app_process ]] ||
    fail "Android app_process is unavailable or unsafe: $app_process"
for command_name in grep od sed seq tail tr; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done
mkdir -p "$run_dir"
[[ -d $run_dir && ! -L $run_dir ]] || fail "unsafe BVB run directory: $run_dir"
chmod 700 "$run_dir"

: >"$service_log"
: >"$launcher_log"
: >"$frame_client_log"
: >"$frame_result"
activity_token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
[[ $activity_token =~ ^[0-9a-f]{64}$ ]] ||
    fail 'could not generate a 256-bit Activity capability'
"$service" --socket "$socket" --loader "$driver" --activity-port 0 \
    --activity-token "$activity_token" \
    --activity-frame-socket "$frame_setup_socket" >"$service_log" 2>&1 &
service_pid=$!
for _ in $(seq 1 100); do
    activity_port=$(sed -n \
        's/.*activity_port=\([0-9][0-9]*\)$/\1/p' "$service_log" | tail -1)
    [[ -S $socket && $activity_port =~ ^[1-9][0-9]*$ &&
       $activity_port -le 65535 ]] && break
    kill -0 "$service_pid" 2>/dev/null || break
    sleep 0.05
done
[[ -S $socket && $activity_port =~ ^[1-9][0-9]*$ &&
   $activity_port -le 65535 ]] || {
    sed -n '1,80p' "$service_log" >&2 || true
    fail 'BVB service did not publish its socket and Activity ingress'
}

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock >/dev/null 2>&1 || true
fi
printf 'Preparing Tomb Raider BVB foreground handoff: socket=%s service_log=%s launcher_log=%s\n' \
    "$socket" "$service_log" "$launcher_log"
STEAM_ARM64_BVB_VULKAN=1 \
BVB_BRIDGE_SOCKET="$socket" \
BVB_ICD_DIAGNOSTICS=1 \
TOMB_RAIDER_DIRECT_DIAGNOSTICS="$direct_diagnostics" \
STEAM_ARM64_DIRECT_START_GATE="$start_gate" \
"$launcher" "$@" >"$launcher_log" 2>&1 &
launcher_pid=$!
for _ in $(seq 1 6000); do
    [[ -f $start_gate_waiting && ! -L $start_gate_waiting &&
       -f $start_gate_launcher_ready && ! -L $start_gate_launcher_ready ]] &&
        break
    process_is_running "$launcher_pid" || break
    sleep 0.05
done
if [[ ! -f $start_gate_waiting || -L $start_gate_waiting ||
      ! -f $start_gate_launcher_ready || -L $start_gate_launcher_ready ]]; then
    if process_is_running "$launcher_pid"; then
        sed -n '1,160p' "$launcher_log" >&2 || true
        fail 'Steam foreground handoff timed out before launch acknowledgement'
    fi
    set +e
    wait "$launcher_pid"
    launcher_status=$?
    set -e
    launcher_pid=
    sed -n '1,160p' "$launcher_log" >&2 || true
    fail "Steam foreground launch failed before Activity handoff: status=$launcher_status"
fi

"$activity_launcher" start -S -W -n "$activity_component" \
    --ei bvb_activity_port "$activity_port" \
    --es bvb_activity_token "$activity_token" >/dev/null
for _ in $(seq 1 200); do
    grep -Eq 'activity_event=11 .*width=[1-9][0-9]* height=[1-9][0-9]*' \
        "$service_log" && break
    kill -0 "$service_pid" 2>/dev/null || break
    sleep 0.05
done
grep -Eq 'activity_event=11 .*width=[1-9][0-9]* height=[1-9][0-9]*' \
    "$service_log" || {
    sed -n '1,120p' "$service_log" >&2 || true
    fail 'installed BVB Activity did not report a ready Vulkan renderer'
}
helper_apk=$("$package_manager" path "${activity_component%%/*}" 2>/dev/null |
    sed -n 's/^package://p' | sed -n '1p')
[[ $helper_apk == /* && -f $helper_apk && -r $helper_apk && ! -L $helper_apk ]] ||
    fail 'could not resolve a readable installed BVB Activity APK'
env -u LD_LIBRARY_PATH -u LD_PRELOAD CLASSPATH="$helper_apk" \
    "$app_process" -Xnoimage-dex2oat / "$frame_client_class" \
    "$activity_token" "$frame_result" "$frame_setup_socket" \
    >"$frame_client_log" 2>&1 &
frame_client_pid=$!
for _ in $(seq 1 200); do
    grep -Fq "@$frame_setup_socket" /proc/net/unix && break
    process_is_running "$frame_client_pid" || break
    sleep 0.05
done
grep -Fq "@$frame_setup_socket" /proc/net/unix || {
    sed -n '1,80p' "$frame_client_log" >&2 || true
    fail 'Activity frame setup relay did not publish its same-UID socket'
}
(set -o noclobber; : >"$start_gate") 2>/dev/null ||
    fail 'could not release the private direct-launch gate'

printf 'Starting Tomb Raider BVB probe: socket=%s activity_port=%s service_log=%s launcher_log=%s\n' \
    "$socket" "$activity_port" "$service_log" "$launcher_log"
set +e
wait "$launcher_pid"
launcher_status=$?
set -e
launcher_pid=

if [[ -n $frame_client_pid ]] && ! process_is_running "$frame_client_pid"; then
    wait "$frame_client_pid" 2>/dev/null || true
    frame_client_pid=
fi

if kill -0 "$service_pid" 2>/dev/null; then
    kill -TERM "$service_pid" 2>/dev/null || true
fi
wait "$service_pid" 2>/dev/null || true
service_pid=
printf 'Tomb Raider BVB probe complete: status=%s service_log=%s launcher_log=%s\n' \
    "$launcher_status" "$service_log" "$launcher_log"
if [[ -s $frame_result ]]; then
    printf 'Tomb Raider BVB frame setup: result=%s log=%s\n' \
        "$(sed -n '1p' "$frame_result")" "$frame_client_log"
fi
exit "$launcher_status"
