#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
service=$base/bvb/bin/bvb-bridge-service
manifest=$base/bvb/icd.d/bvb_icd.aarch64.json
launcher=${TOMB_RAIDER_BVB_LAUNCHER:-$HOME/start-tombraider-direct-lean}
activity_launcher=${BVB_ACTIVITY_LAUNCHER:-am}
activity_component=${BVB_VISIBLE_HOST_COMPONENT:-io.github.huntergdavis.bvb.visiblehost/.VisibleHostActivity}
run_dir=$base/run/bvb
log_dir=$base/logs
stamp=$(date -u +%Y%m%dT%H%M%SZ)
socket=$run_dir/tombraider-probe-$stamp-$$.sock
service_log=$log_dir/tombraider-bvb-service-$stamp.log
launcher_log=$log_dir/tombraider-bvb-launcher-$stamp.log
start_gate=$run_dir/tombraider-start-$stamp-$$.gate
start_gate_waiting=$start_gate.waiting
start_gate_launcher_ready=$start_gate.launcher-ready
service_pid=
launcher_pid=
activity_token=
activity_port=

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
[[ -f $manifest && ! -L $manifest ]] ||
    fail "installed BVB ICD manifest is unavailable: $manifest"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "Tomb Raider direct launcher is unavailable: $launcher"
command -v "$activity_launcher" >/dev/null 2>&1 ||
    fail "Android Activity launcher is unavailable: $activity_launcher"
for command_name in grep od sed seq tail tr; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done
mkdir -p "$run_dir"
[[ -d $run_dir && ! -L $run_dir ]] || fail "unsafe BVB run directory: $run_dir"
chmod 700 "$run_dir"

: >"$service_log"
: >"$launcher_log"
activity_token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
[[ $activity_token =~ ^[0-9a-f]{64}$ ]] ||
    fail 'could not generate a 256-bit Activity capability'
"$service" --socket "$socket" --activity-port 0 \
    --activity-token "$activity_token" >"$service_log" 2>&1 &
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
TOMB_RAIDER_DIRECT_DIAGNOSTICS=1 \
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
(set -o noclobber; : >"$start_gate") 2>/dev/null ||
    fail 'could not release the private direct-launch gate'

printf 'Starting Tomb Raider BVB probe: socket=%s activity_port=%s service_log=%s launcher_log=%s\n' \
    "$socket" "$activity_port" "$service_log" "$launcher_log"
set +e
wait "$launcher_pid"
launcher_status=$?
set -e
launcher_pid=

if kill -0 "$service_pid" 2>/dev/null; then
    kill -TERM "$service_pid" 2>/dev/null || true
fi
wait "$service_pid" 2>/dev/null || true
service_pid=
printf 'Tomb Raider BVB probe complete: status=%s service_log=%s launcher_log=%s\n' \
    "$launcher_status" "$service_log" "$launcher_log"
exit "$launcher_status"
