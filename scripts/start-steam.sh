#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

display="${STEAM_X11_DISPLAY:-:0}"
base="${STEAM_ARM64_BASE:-$HOME/steam-arm64}"
steam_launcher="${STEAM_ARM64_LAUNCHER:-$HOME/bin/steam-arm}"
pulse_helper="$base/prepare-pulseaudio-tcp.sh"
x11_component="com.termux.x11/com.termux.x11.MainActivity"
x11_socket="${PREFIX:-}/tmp/.X11-unix/X${display#:}"
x11_log="$base/logs/termux-x11-minimal.log"
profile="${STEAM_ARM64_FEX_PROFILE:-safe}"

fail() {
    printf 'start-steam: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

package_uid() {
    local package="$1"
    cmd package list packages -U --user 0 "$package" 2>/dev/null |
        sed -n "s/^package:${package} uid:\([0-9][0-9]*\)$/\1/p" |
        head -n 1
}

matching_pids() {
    local kind="$1" process cmdline first_argument
    for process in /proc/[0-9]*; do
        [[ -r "$process/cmdline" ]] || continue
        cmdline="$(tr '\0' ' ' <"$process/cmdline" 2>/dev/null || true)"
        case "$kind" in
            x11)
                [[ "$cmdline" == "termux-x11 com.termux.x11 ${display} "* ]] ||
                    continue
                ;;
            steam)
                first_argument="${cmdline%% *}"
                [[ "$first_argument" == "$base/client/steamrtarm64/steam" ]] ||
                    continue
                ;;
            launcher)
                [[ "$cmdline" == *" $steam_launcher "* ||
                        "$cmdline" == *" $steam_launcher" ]] || continue
                ;;
            *)
                fail "internal process selector is invalid: $kind"
                ;;
        esac
        printf '%s\n' "${process#/proc/}"
    done
}

wait_for_x11() {
    local _
    for _ in $(seq 1 20); do
        if DISPLAY="$display" timeout 3 xdpyinfo >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

for command in am cmd termux-x11 termux-x11-preference timeout xdpyinfo \
        pactl pulseaudio; do
    require_command "$command"
done
[[ -n "${PREFIX:-}" ]] || fail 'PREFIX is not set; run this from Termux'
[[ "$display" =~ ^:[0-9]+$ ]] || fail "invalid X display: $display"
[[ -x "$steam_launcher" ]] || fail "Steam launcher is unavailable: $steam_launcher"
[[ -x "$pulse_helper" ]] || fail "PulseAudio helper is unavailable: $pulse_helper"
mkdir -p "$base/logs"

termux_uid="$(package_uid com.termux)"
x11_uid="$(package_uid com.termux.x11)"
[[ "$termux_uid" =~ ^[0-9]+$ ]] || fail 'unable to resolve the Termux package UID'
[[ "$x11_uid" =~ ^[0-9]+$ ]] || fail 'unable to resolve the Termux:X11 package UID'
[[ "$termux_uid" == "$x11_uid" ]] ||
    fail "Termux and Termux:X11 do not share a UID ($termux_uid != $x11_uid)"

# Upstream separates the foreground Android activity from the X server. Open
# the activity first so a cold launch receives one clean server connection and
# so Samsung keeps this shared UID in the foreground cpuset.
if ! am start --user 0 -n "$x11_component" >/dev/null; then
    fail 'unable to open the Termux:X11 Android activity'
fi

# Trackpad mode provides touch-to-mouse input without enabling pointer capture,
# which can trap a physical mouse. Termux:X11's screen-idle preference keeps the
# display awake without adding a separate CPU/wake-lock policy to benchmarks.
if ! timeout 10 termux-x11-preference \
        touchMode:Trackpad 'screenIdleTimeout:Never (keep screen on)' >/dev/null; then
    fail 'unable to configure Termux:X11 input and idle behavior'
fi

mapfile -t x11_pids < <(matching_pids x11)
case "${#x11_pids[@]}" in
    0)
        if [[ -e "$x11_socket" || -L "$x11_socket" ]]; then
            fail "display socket exists without a validated X server: $x11_socket"
        fi
        nohup termux-x11 "$display" -ac >"$x11_log" 2>&1 </dev/null &
        x11_pid=$!
        if ! wait_for_x11; then
            fail "X server $x11_pid did not become ready; inspect $x11_log"
        fi
        mapfile -t x11_pids < <(matching_pids x11)
        [[ "${#x11_pids[@]}" -eq 1 ]] ||
            fail "expected one X server after startup, found ${#x11_pids[@]}"
        ;;
    1)
        wait_for_x11 || fail "existing X server ${x11_pids[0]} is unreachable"
        ;;
    *)
        fail "multiple X servers target $display: ${x11_pids[*]}"
        ;;
esac

if ! x11_extensions="$(DISPLAY="$display" timeout 5 \
        xdpyinfo -queryExtensions 2>/dev/null)"; then
    fail 'unable to query X11 input extensions'
fi
if ! grep -Fq XInputExtension <<<"$x11_extensions"; then
    fail 'XInputExtension is unavailable; mouse input cannot be verified'
fi

"$pulse_helper" "$base"
pactl --server=tcp:127.0.0.1:4713 info >/dev/null 2>&1 ||
    fail 'PulseAudio TCP endpoint is unavailable after preparation'

mapfile -t steam_pids < <(matching_pids steam)
if [[ "${#steam_pids[@]}" -gt 1 ]]; then
    fail "multiple Steam main processes found: ${steam_pids[*]}"
fi
if [[ "${#steam_pids[@]}" -eq 1 ]]; then
    if [[ "$#" -gt 0 ]]; then
        forward_log="$base/logs/start-steam-forward-$(date +%Y%m%d-%H%M%S).log"
        nohup env DISPLAY="$display" "$steam_launcher" "$@" \
            >"$forward_log" 2>&1 </dev/null &
        printf 'start-steam: forwarded request to Steam PID %s; log %s\n' \
            "${steam_pids[0]}" "$forward_log"
    fi
    printf 'start-steam: ready; X11 PID %s, Steam PID %s, PulseAudio TCP, mouse input, no KDE started\n' \
        "${x11_pids[0]}" "${steam_pids[0]}"
    exit 0
fi

mapfile -t launcher_pids < <(matching_pids launcher)
if [[ "${#launcher_pids[@]}" -gt 0 ]]; then
    printf 'start-steam: Steam initialization is already running under launcher PID %s\n' \
        "${launcher_pids[0]}"
    exit 0
fi

steam_log="$base/logs/start-steam-$(date +%Y%m%d-%H%M%S).log"
nohup env DISPLAY="$display" STEAM_ARM64_FEX_PROFILE="$profile" \
    "$steam_launcher" -noshaders "$@" >"$steam_log" 2>&1 </dev/null &
launcher_pid=$!

for _ in $(seq 1 60); do
    mapfile -t steam_pids < <(matching_pids steam)
    if [[ "${#steam_pids[@]}" -eq 1 ]]; then
        printf 'start-steam: ready; X11 PID %s, Steam PID %s, PulseAudio TCP, mouse input, FEX %s, no KDE\n' \
            "${x11_pids[0]}" "${steam_pids[0]}" "$profile"
        exit 0
    fi
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        fail "Steam launcher exited before Steam appeared; inspect $steam_log"
    fi
    sleep 1
done

printf 'start-steam: launcher PID %s is still initializing; follow %s\n' \
    "$launcher_pid" "$steam_log"
