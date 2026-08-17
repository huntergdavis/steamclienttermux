#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
launcher=${TOMB_RAIDER_CAPTURE_LAUNCHER:-$HOME/start-steam-native.sh}
wait_seconds=${TOMB_RAIDER_CAPTURE_WAIT_SECONDS:-300}
state=$base/run/tombraider-plan-capture.state

fail() {
    printf 'capture-tombraider-pressure-vessel-plan: %s\n' "$*" >&2
    exit 1
}

[[ $wait_seconds =~ ^[1-9][0-9]*$ ]] ||
    fail 'TOMB_RAIDER_CAPTURE_WAIT_SECONDS must be positive'
[[ -d $base && ! -L $base && -d $base/logs && ! -L $base/logs &&
        -d $base/logs/runtime-plans && ! -L $base/logs/runtime-plans &&
        -d $base/run && ! -L $base/run ]] ||
    fail "Steam capture directories are unavailable below $base"
[[ -x $launcher && ! -L $launcher ]] ||
    fail "native Tomb Raider launcher is unavailable: $launcher"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
capture=$base/logs/runtime-plans/tombraider-203160-$stamp.json
[[ ! -e $capture && ! -L $capture ]] ||
    fail "capture artifact already exists: $capture"

state_stage=$(mktemp "$state.tmp.XXXXXX")
cleanup() {
    if [[ -n ${state_stage:-} && -f $state_stage && ! -L $state_stage ]]; then
        unlink -- "$state_stage"
    fi
}
trap cleanup EXIT
printf 'pid=%s\ncapture=%s\nstarted_utc=%s\nstatus=launching\n' \
    "$$" "$capture" "$stamp" >"$state_stage"
chmod 600 "$state_stage"
mv -- "$state_stage" "$state"
state_stage=

set +e
STEAM_ARM64_BWRAP_CAPTURE_PLAN=$capture \
STEAM_BACKGROUND=1 \
STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-180} \
STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-300} \
STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300} \
"$launcher" --appid 203160 -- -nolauncher
launcher_status=$?
set -e

for _ in $(seq 1 "$wait_seconds"); do
    [[ -s $capture && ! -L $capture ]] && break
    sleep 1
done

if [[ ! -s $capture || -L $capture ]]; then
    printf 'pid=%s\ncapture=%s\nstarted_utc=%s\nstatus=failed\nlauncher_status=%s\n' \
        "$$" "$capture" "$stamp" "$launcher_status" >"$state"
    fail "no Tomb Raider Pressure Vessel plan appeared after ${wait_seconds}s"
fi

printf 'pid=%s\ncapture=%s\nstarted_utc=%s\nstatus=captured\nlauncher_status=%s\n' \
    "$$" "$capture" "$stamp" "$launcher_status" >"$state"
printf 'Captured Tomb Raider Pressure Vessel plan without executing the game: %s\n' \
    "$capture"
