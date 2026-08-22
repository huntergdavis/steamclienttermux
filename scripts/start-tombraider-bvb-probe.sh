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
activity_adb_serial=${BVB_ACTIVITY_ADB_SERIAL:-}
adb_command=${BVB_ADB_COMMAND:-adb}
app_process=${BVB_APP_PROCESS:-/system/bin/app_process64}
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
activity_screenshot=$log_dir/tombraider-bvb-activity-$run_id.png
start_gate=$run_dir/tombraider-start-$run_id.gate
start_gate_waiting=$start_gate.waiting
start_gate_launcher_ready=$start_gate.launcher-ready
service_pid=
launcher_pid=
frame_client_pid=
activity_token=
activity_port=
helper_apk=
activity_package=${activity_component%%/*}
activity_version_code=
direct_diagnostics=${TOMB_RAIDER_DIRECT_DIAGNOSTICS:-0}
icd_diagnostics=${TOMB_RAIDER_BVB_ICD_DIAGNOSTICS:-0}
command_stream=${TOMB_RAIDER_BVB_COMMAND_STREAM:-strict}
mapped_memory=${TOMB_RAIDER_BVB_MAPPED_MEMORY:-strict}
first_rejection_diagnostic=${TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC-0}
frame_profile=${TOMB_RAIDER_BVB_FRAME_PROFILE:-0}
child_stop_ticks=${BVB_CHILD_STOP_TICKS:-100}
child_kill_ticks=${BVB_CHILD_KILL_TICKS:-20}
frame_finish_ticks=${BVB_FRAME_FINISH_TICKS:-200}
activity_started=0
cleanup_started=0
launcher_status=
frame_client_status=
service_status=
frame_result_summary=

fail() {
    printf 'start-tombraider-bvb-probe: %s\n' "$*" >&2
    exit 1
}

activity_manager() {
    if [[ -n $activity_adb_serial ]]; then
        "$adb_command" -s "$activity_adb_serial" shell am "$@"
    else
        "$activity_launcher" "$@"
    fi
}

package_manager_call() {
    if [[ -n $activity_adb_serial ]]; then
        "$adb_command" -s "$activity_adb_serial" shell pm "$@"
    else
        "$package_manager" "$@"
    fi
}

frame_setup_listener_visible() {
    if [[ -n $activity_adb_serial ]]; then
        "$adb_command" -s "$activity_adb_serial" shell cat /proc/net/unix \
            2>/dev/null | grep -Fq "@$frame_setup_socket"
    else
        grep -Fq "@$frame_setup_socket" /proc/net/unix
    fi
}

remove_stale_activity_tasks() {
    local task_dump task_id
    [[ -n $activity_adb_serial ]] || return 0
    task_dump=$("$adb_command" -s "$activity_adb_serial" shell \
        dumpsys activity recents 2>/dev/null) ||
        fail 'could not inspect BVB Activity tasks through paired ADB'
    while IFS= read -r task_id; do
        [[ $task_id =~ ^[1-9][0-9]{0,9}$ ]] ||
            fail "unsafe BVB Activity task ID: $task_id"
        activity_manager stack remove "$task_id" >/dev/null ||
            fail "could not remove stale BVB Activity task: $task_id"
    done < <(printf '%s\n' "$task_dump" |
        grep -F ":$activity_package}" |
        sed -n 's/.*#\([0-9][0-9]*\) type=.*/\1/p' |
        sort -nu)
}

prepare_adb_activity_fullscreen() {
    local display_dump task_dump focus_dump task_id display_width display_height
    local fullscreen_x fullscreen_y png_magic
    [[ -n $activity_adb_serial ]] || return 0

    display_dump=$("$adb_command" -s "$activity_adb_serial" shell \
        dumpsys window displays 2>/dev/null) ||
        fail 'could not inspect the current Android display through paired ADB'
    if [[ $display_dump =~ cur=([1-9][0-9]{2,4})x([1-9][0-9]{2,4}) ]]; then
        display_width=${BASH_REMATCH[1]}
        display_height=${BASH_REMATCH[2]}
    else
        fail 'could not resolve the current Android display extent'
    fi

    task_dump=$("$adb_command" -s "$activity_adb_serial" shell \
        dumpsys activity recents 2>/dev/null) ||
        fail 'could not inspect the launched BVB Activity task'
    task_id=$(printf '%s\n' "$task_dump" |
        grep -F ":$activity_package}" |
        sed -n 's/.*#\([0-9][0-9]*\) type=.*/\1/p' |
        sort -nu | tail -1)
    [[ $task_id =~ ^[1-9][0-9]{0,9}$ ]] ||
        fail 'could not resolve the launched BVB Activity task ID'

    activity_manager task resize "$task_id" 0 0 \
        "$display_width" "$display_height" >/dev/null ||
        fail "could not resize BVB Activity task $task_id"
    for _ in $(seq 1 200); do
        grep -Eq "activity_event=11 .*width=$display_width height=$display_height" \
            "$service_log" && break
        kill -0 "$service_pid" 2>/dev/null || break
        sleep 0.05
    done
    grep -Eq "activity_event=11 .*width=$display_width height=$display_height" \
        "$service_log" ||
        fail "BVB Activity did not adopt display extent ${display_width}x${display_height}"

    focus_dump=$("$adb_command" -s "$activity_adb_serial" shell \
        dumpsys window 2>/dev/null) ||
        fail 'could not inspect Android window focus through paired ADB'
    if ! printf '%s\n' "$focus_dump" | grep -F 'mCurrentFocus=' |
            grep -Fq "$activity_package"; then
        activity_manager start -W --activity-reorder-to-front \
            -n "$activity_component" \
            --ei bvb_activity_port "$activity_port" \
            --ei bvb_retain_external_renderer 1 \
            --es bvb_activity_token "$activity_token" >/dev/null ||
            fail 'could not reorder the authenticated BVB Activity to the foreground'
        sleep 0.25
        focus_dump=$("$adb_command" -s "$activity_adb_serial" shell \
            dumpsys window 2>/dev/null) ||
            fail 'could not recheck Android window focus through paired ADB'
    fi
    printf '%s\n' "$focus_dump" | grep -F 'mCurrentFocus=' |
        grep -Fq "$activity_package" ||
        fail 'BVB Activity did not own Android window focus before fullscreen input'

    fullscreen_x=$((display_width - 170))
    fullscreen_y=74
    (( fullscreen_x > 0 && fullscreen_y < display_height )) ||
        fail 'resolved display extent cannot safely address the fullscreen control'
    "$adb_command" -s "$activity_adb_serial" shell input tap \
        "$fullscreen_x" "$fullscreen_y" >/dev/null ||
        fail 'could not activate the Samsung fullscreen control'
    # Let the renderer replace the Android splash before recording the milestone.
    sleep 2

    (set -o noclobber; "$adb_command" -s "$activity_adb_serial" \
        exec-out screencap -p >"$activity_screenshot") 2>/dev/null ||
        fail "could not capture the BVB Activity milestone screenshot: $activity_screenshot"
    png_magic=$(od -An -N8 -tx1 "$activity_screenshot" | tr -d ' \n')
    [[ $png_magic == 89504e470d0a1a0a ]] ||
        fail "BVB Activity milestone screenshot is not PNG: $activity_screenshot"
    chmod 600 "$activity_screenshot"
    printf 'BVB Activity fullscreen ready: task=%s extent=%sx%s screenshot=%s\n' \
        "$task_id" "$display_width" "$display_height" "$activity_screenshot"
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

reap_child() {
    local pid="$1" status_name="$2" child_status
    if wait "$pid" 2>/dev/null; then
        child_status=0
    else
        child_status=$?
    fi
    printf -v "$status_name" '%s' "$child_status"
}

stop_child_bounded() {
    local pid="$1" status_name="$2" label="$3"
    [[ $pid =~ ^[1-9][0-9]*$ ]] || return 0
    if process_is_running "$pid"; then
        kill -TERM "$pid" 2>/dev/null || true
        for _ in $(seq 1 "$child_stop_ticks"); do
            process_is_running "$pid" || break
            sleep 0.05
        done
    fi
    if process_is_running "$pid"; then
        printf 'start-tombraider-bvb-probe: %s pid %s ignored TERM; sending KILL\n' \
            "$label" "$pid" >&2
        kill -KILL "$pid" 2>/dev/null || true
        for _ in $(seq 1 "$child_kill_ticks"); do
            process_is_running "$pid" || break
            sleep 0.05
        done
    fi
    if process_is_running "$pid"; then
        printf 'start-tombraider-bvb-probe: %s pid %s survived bounded cleanup\n' \
            "$label" "$pid" >&2
        printf -v "$status_name" '%s' 124
        return 1
    fi
    reap_child "$pid" "$status_name"
}

# Invoked by EXIT-trap cleanup.
# shellcheck disable=SC2329
wait_child_bounded() {
    local pid="$1" status_name="$2" label="$3" ticks="$4"
    [[ $pid =~ ^[1-9][0-9]*$ ]] || return 0
    for _ in $(seq 1 "$ticks"); do
        process_is_running "$pid" || break
        sleep 0.05
    done
    if process_is_running "$pid"; then
        stop_child_bounded "$pid" "$status_name" "$label"
        return 124
    fi
    reap_child "$pid" "$status_name"
}

validate_frame_result() {
    python3 - "$frame_result" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    document = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"invalid frame result JSON: {error}")
if not isinstance(document, dict):
    raise SystemExit("frame result must be one top-level JSON object")
if document.get("result") != "pass":
    raise SystemExit("frame result is not pass")
for name in ("image_count", "generation", "per_frame_java_calls", "per_frame_binder_calls"):
    if type(document.get(name)) is not int:
        raise SystemExit(f"frame result {name} must be an integer")
if not 2 <= document["image_count"] <= 4:
    raise SystemExit("frame result image_count must be in [2, 4]")
signed_generation = document["generation"]
if (signed_generation == 0 or
        signed_generation < -(1 << 63) or
        signed_generation > (1 << 63) - 1):
    raise SystemExit("frame result generation must be a nonzero signed 64-bit integer")
if document["per_frame_java_calls"] != 0 or document["per_frame_binder_calls"] != 0:
    raise SystemExit("frame result per-frame Java/Binder counts must both be zero")
document["generation"] = signed_generation & ((1 << 64) - 1)
print(json.dumps(document, sort_keys=True, separators=(",", ":")))
PY
}

# Invoked by the EXIT trap below.
# shellcheck disable=SC2329
cleanup() {
    local original_status=$? activity_cleanup_pid='' activity_cleanup_status=''
    [[ $cleanup_started -eq 0 ]] || return "$original_status"
    cleanup_started=1
    stop_child_bounded "${launcher_pid:-}" launcher_status launcher || true
    launcher_pid=
    stop_child_bounded "${frame_client_pid:-}" frame_client_status frame-client || true
    frame_client_pid=
    stop_child_bounded "${service_pid:-}" service_status bridge-service || true
    service_pid=
    if [[ $activity_started -eq 1 ]]; then
        activity_manager force-stop --user 0 "$activity_package" \
            >/dev/null 2>&1 &
        activity_cleanup_pid=$!
        if ! wait_child_bounded "$activity_cleanup_pid" activity_cleanup_status \
            activity-force-stop "$child_stop_ticks" ||
           [[ $activity_cleanup_status -ne 0 ]]; then
            printf 'start-tombraider-bvb-probe: Activity force-stop cleanup failed: status=%s\n' \
                "${activity_cleanup_status:-unknown}" >&2
        fi
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
    return "$original_status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

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
[[ $icd_diagnostics =~ ^[01]$ ]] ||
    fail 'TOMB_RAIDER_BVB_ICD_DIAGNOSTICS must be 0 or 1'
[[ $command_stream == strict || $command_stream == shared ]] ||
    fail 'TOMB_RAIDER_BVB_COMMAND_STREAM must be strict or shared'
[[ $mapped_memory == strict || $mapped_memory == shared ]] ||
    fail 'TOMB_RAIDER_BVB_MAPPED_MEMORY must be strict or shared'
[[ $first_rejection_diagnostic == 0 || $first_rejection_diagnostic == 1 ]] ||
    fail 'TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC must be 0 or 1'
[[ $frame_profile == 0 || $frame_profile == 1 ]] ||
    fail 'TOMB_RAIDER_BVB_FRAME_PROFILE must be 0 or 1'
# The effective ICD switch belongs only to the reconstructed Wine/DXVK
# environment. Do not let caller-supplied copies reach the Bionic service,
# Activity helper, direct launcher, Steam, or CEF.
unset BVB_COMMAND_STREAM STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM \
    TOMB_RAIDER_BVB_COMMAND_STREAM BVB_MAPPED_MEMORY \
    STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY TOMB_RAIDER_BVB_MAPPED_MEMORY \
    BVB_ICD_DIAGNOSTICS TOMB_RAIDER_BVB_ICD_DIAGNOSTICS \
    BVB_FRAME_PROFILE TOMB_RAIDER_BVB_FRAME_PROFILE \
    BVB_FIRST_REJECTION_DIAGNOSTIC \
    STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC \
    TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC
for tick_setting in child_stop_ticks child_kill_ticks frame_finish_ticks; do
    tick_value=${!tick_setting}
    [[ $tick_value =~ ^[1-9][0-9]*$ && $tick_value -le 6000 ]] ||
        fail "$tick_setting must be an integer in [1, 6000]"
done
if [[ -n $activity_adb_serial ]]; then
    [[ $activity_adb_serial =~ ^[A-Za-z0-9._:-]{1,128}$ ]] ||
        fail 'BVB_ACTIVITY_ADB_SERIAL has an unsafe value'
    command -v "$adb_command" >/dev/null 2>&1 ||
        fail "ADB command is unavailable: $adb_command"
    [[ $("$adb_command" -s "$activity_adb_serial" get-state 2>/dev/null) == device ]] ||
        fail "paired ADB device is unavailable: $activity_adb_serial"
else
    command -v "$activity_launcher" >/dev/null 2>&1 ||
        fail "Android Activity launcher is unavailable: $activity_launcher"
    command -v "$package_manager" >/dev/null 2>&1 ||
        fail "Android package manager is unavailable: $package_manager"
fi
[[ $app_process == /* && -x $app_process && ! -L $app_process ]] ||
    fail "Android app_process is unavailable or unsafe: $app_process"
for command_name in grep od python3 sed seq sort tail tr; do
    command -v "$command_name" >/dev/null 2>&1 ||
        fail "required command is unavailable: $command_name"
done
mkdir -p "$run_dir"
[[ -d $run_dir && ! -L $run_dir ]] || fail "unsafe BVB run directory: $run_dir"
chmod 700 "$run_dir"

if ! activity_package_output=$(package_manager_call list packages --show-versioncode \
    "$activity_package" 2>/dev/null); then
    fail "could not query BVB visible host package: $activity_package"
fi
activity_package_line=
while IFS= read -r package_line; do
    if [[ $package_line =~ ^package:([^[:space:]]+)[[:space:]]+versionCode:([0-9]+)$ ]] &&
       [[ ${BASH_REMATCH[1]} == "$activity_package" ]]; then
        [[ -z $activity_package_line ]] ||
            fail "multiple exact BVB visible host package records: $activity_package"
        activity_package_line=$package_line
        activity_version_code=${BASH_REMATCH[2]}
    fi
done <<<"$activity_package_output"
[[ $activity_version_code =~ ^[0-9]+$ && $activity_version_code -ge 40 ]] ||
    fail "BVB visible host versionCode 40 or newer is required: ${activity_package_output:-not installed}"

: >"$service_log"
: >"$launcher_log"
: >"$frame_client_log"
: >"$frame_result"
activity_token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
[[ $activity_token =~ ^[0-9a-f]{64}$ ]] ||
    fail 'could not generate a 256-bit Activity capability'
BVB_FRAME_PROFILE="$frame_profile" \
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
BVB_ICD_DIAGNOSTICS="$icd_diagnostics" \
TOMB_RAIDER_DIRECT_DIAGNOSTICS="$direct_diagnostics" \
TOMB_RAIDER_BVB_COMMAND_STREAM="$command_stream" \
TOMB_RAIDER_BVB_MAPPED_MEMORY="$mapped_memory" \
TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC="$first_rejection_diagnostic" \
BVB_FRAME_PROFILE="$frame_profile" \
TOMB_RAIDER_BVB_FRAME_PROFILE="$frame_profile" \
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

remove_stale_activity_tasks
activity_start_arguments=(start -S -W)
if [[ -n $activity_adb_serial ]]; then
    activity_start_arguments+=(--windowingMode 1)
fi
activity_start_arguments+=(-n "$activity_component"
    --ei bvb_activity_port "$activity_port"
    --ei bvb_retain_external_renderer 1
    --ei bvb_frame_profile "$frame_profile"
    --es bvb_activity_token "$activity_token")
activity_manager "${activity_start_arguments[@]}" >/dev/null
activity_started=1
if [[ -n $activity_adb_serial ]]; then
    # Samsung DeX can ignore the requested fullscreen launch mode and create a
    # small freeform surface. Resize the new task before waiting for renderer
    # readiness: the bootstrap batch itself is sized for the native extent and
    # can fail before event 11 when initialized against that small surface.
    prepare_adb_activity_fullscreen
else
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
fi
helper_apk=$(package_manager_call path "$activity_package" 2>/dev/null |
    sed -n 's/^package://p' | sed -n '1p')
[[ $helper_apk == /* && -f $helper_apk && -r $helper_apk && ! -L $helper_apk ]] ||
    fail 'could not resolve a readable installed BVB Activity APK'
[[ $helper_apk == */base.apk ]] ||
    fail 'installed BVB Activity APK path is not canonical'
helper_native_library=${helper_apk%/base.apk}/lib/arm64/libbvb-visible-host.so
[[ $helper_native_library == /* && -f $helper_native_library &&
   -r $helper_native_library && -x $helper_native_library &&
   ! -L $helper_native_library ]] ||
    fail 'could not resolve the installed BVB Activity native library'
helper_native_library_dir=${helper_native_library%/*}
env -u LD_LIBRARY_PATH -u LD_PRELOAD \
    BVB_VISIBLE_HOST_NATIVE_LIBRARY="$helper_native_library" \
    CLASSPATH="$helper_apk" \
    "$app_process" -Xnoimage-dex2oat \
    "-Djava.library.path=$helper_native_library_dir" \
    / "$frame_client_class" \
    "$activity_token" "$frame_result" "$frame_setup_socket" \
    >"$frame_client_log" 2>&1 &
frame_client_pid=$!
for _ in $(seq 1 200); do
    frame_setup_listener_visible && break
    process_is_running "$frame_client_pid" || break
    sleep 0.05
done
frame_setup_listener_visible || {
    sed -n '1,80p' "$frame_client_log" >&2 || true
    fail 'Activity frame setup relay did not publish its same-UID socket'
}
(set -o noclobber; : >"$start_gate") 2>/dev/null ||
    fail 'could not release the private direct-launch gate'

printf 'Starting Tomb Raider BVB probe: socket=%s activity_port=%s service_log=%s launcher_log=%s\n' \
    "$socket" "$activity_port" "$service_log" "$launcher_log"
terminal_failure=
while :; do
    # Deterministic precedence: a launcher exit observed in this sample wins
    # when nonzero; while it remains live, service death precedes helper death.
    if ! process_is_running "$launcher_pid"; then
        reap_child "$launcher_pid" launcher_status
        launcher_pid=
        if [[ $launcher_status -ne 0 ]]; then
            terminal_failure=launcher
            break
        fi
        if ! process_is_running "$service_pid"; then
            reap_child "$service_pid" service_status
            service_pid=
            terminal_failure=service
        fi
        break
    fi
    if ! process_is_running "$service_pid"; then
        reap_child "$service_pid" service_status
        service_pid=
        terminal_failure=service
        break
    fi
    if [[ -n $frame_client_pid ]] && ! process_is_running "$frame_client_pid"; then
        reap_child "$frame_client_pid" frame_client_status
        frame_client_pid=
        if [[ $frame_client_status -ne 0 ]] ||
           ! frame_result_summary=$(validate_frame_result 2>>"$frame_client_log"); then
            terminal_failure=frame
            break
        fi
    fi
    sleep 0.05
done

if [[ $terminal_failure == launcher ]]; then
    printf 'Tomb Raider BVB probe complete: status=%s service_log=%s launcher_log=%s\n' \
        "$launcher_status" "$service_log" "$launcher_log"
    exit "$launcher_status"
fi
if [[ $terminal_failure == service ]]; then
    sed -n '1,120p' "$service_log" >&2 || true
    fail "BVB service exited during the foreground probe: status=${service_status:-unknown}"
fi
if [[ $terminal_failure == frame ]]; then
    sed -n '1,80p' "$frame_client_log" >&2 || true
    fail "Activity frame transport did not pass: status=${frame_client_status:-unknown} result=$frame_result"
fi

if [[ -n $frame_client_pid ]]; then
    for _ in $(seq 1 "$frame_finish_ticks"); do
        if ! process_is_running "$service_pid"; then
            reap_child "$service_pid" service_status
            service_pid=
            terminal_failure=service
            break
        fi
        if ! process_is_running "$frame_client_pid"; then
            reap_child "$frame_client_pid" frame_client_status
            frame_client_pid=
            break
        fi
        sleep 0.05
    done
    if [[ $terminal_failure == service ]]; then
        sed -n '1,120p' "$service_log" >&2 || true
        fail "BVB service exited while frame setup was finishing: status=${service_status:-unknown}"
    fi
    if [[ -n $frame_client_pid ]]; then
        stop_child_bounded "$frame_client_pid" frame_client_status frame-client || true
        frame_client_pid=
        sed -n '1,80p' "$frame_client_log" >&2 || true
        fail "Activity frame transport timed out: status=${frame_client_status:-unknown} result=$frame_result"
    fi
    if [[ $frame_client_status -ne 0 ]] ||
       ! frame_result_summary=$(validate_frame_result 2>>"$frame_client_log"); then
        sed -n '1,80p' "$frame_client_log" >&2 || true
        fail "Activity frame transport did not pass: status=$frame_client_status result=$frame_result"
    fi
fi

stop_child_bounded "$service_pid" service_status bridge-service || true
service_pid=
printf 'Tomb Raider BVB probe complete: status=%s service_log=%s launcher_log=%s\n' \
    "$launcher_status" "$service_log" "$launcher_log"
printf 'Tomb Raider BVB frame setup-only handoff: result=%s log=%s E057_present_proof=not-claimed standalone_E074=authoritative\n' \
    "$frame_result_summary" "$frame_client_log"
exit "$launcher_status"
