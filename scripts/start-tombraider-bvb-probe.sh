#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
service=$base/bvb/bin/bvb-bridge-service
manifest=$base/bvb/icd.d/bvb_icd.aarch64.json
launcher=${TOMB_RAIDER_BVB_LAUNCHER:-$HOME/start-tombraider-direct-lean}
run_dir=$base/run/bvb
log_dir=$base/logs
stamp=$(date -u +%Y%m%dT%H%M%SZ)
socket=$run_dir/tombraider-probe-$stamp-$$.sock
service_log=$log_dir/tombraider-bvb-service-$stamp.log
launcher_log=$log_dir/tombraider-bvb-launcher-$stamp.log
service_pid=

fail() {
    printf 'start-tombraider-bvb-probe: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [[ -n ${service_pid:-} ]] && kill -0 "$service_pid" 2>/dev/null; then
        kill -TERM "$service_pid" 2>/dev/null || true
        wait "$service_pid" 2>/dev/null || true
    fi
    if [[ -S $socket ]]; then
        unlink -- "$socket"
    fi
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
mkdir -p "$run_dir"
[[ -d $run_dir && ! -L $run_dir ]] || fail "unsafe BVB run directory: $run_dir"
chmod 700 "$run_dir"

: >"$service_log"
: >"$launcher_log"
"$service" --socket "$socket" >"$service_log" 2>&1 &
service_pid=$!
for _ in $(seq 1 100); do
    [[ -S $socket ]] && break
    kill -0 "$service_pid" 2>/dev/null || break
    sleep 0.05
done
[[ -S $socket ]] || {
    sed -n '1,80p' "$service_log" >&2 || true
    fail 'BVB service did not create its socket'
}

printf 'Starting Tomb Raider BVB probe: socket=%s service_log=%s launcher_log=%s\n' \
    "$socket" "$service_log" "$launcher_log"
set +e
STEAM_ARM64_BVB_VULKAN=1 \
BVB_BRIDGE_SOCKET="$socket" \
BVB_ICD_DIAGNOSTICS=1 \
BVB_ICD_PROBE_WSI=1 \
"$launcher" "$@" >"$launcher_log" 2>&1
launcher_status=$?
set -e

if kill -0 "$service_pid" 2>/dev/null; then
    kill -TERM "$service_pid" 2>/dev/null || true
fi
wait "$service_pid" 2>/dev/null || true
service_pid=
printf 'Tomb Raider BVB probe complete: status=%s service_log=%s launcher_log=%s\n' \
    "$launcher_status" "$service_log" "$launcher_log"
exit "$launcher_status"
