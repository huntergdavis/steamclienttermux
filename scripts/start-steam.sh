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
process_timeout="${STEAM_PROCESS_TIMEOUT:-180}"
window_timeout="${STEAM_WINDOW_TIMEOUT:-180}"
minimum_window_width="${STEAM_MIN_WINDOW_WIDTH:-640}"
minimum_window_height="${STEAM_MIN_WINDOW_HEIGHT:-400}"
pulse_server="tcp:127.0.0.1:4713"

fail() {
    printf 'start-steam: %s\n' "$1" >&2
    exit 1
}

warn() {
    printf 'start-steam: warning: %s\n' "$1" >&2
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

x11_is_ready() {
    DISPLAY="$display" timeout 3 xdpyinfo >/dev/null 2>&1
}

wait_for_x11() {
    local _
    for _ in $(seq 1 20); do
        if x11_is_ready; then
            return 0
        fi
        sleep 1
    done
    return 1
}

foreground_x11() {
    am start --user 0 -n "$x11_component" >/dev/null ||
        fail 'unable to open the Termux:X11 Android activity'
}

largest_steam_window() {
    local visibility="$1" window geometry width height area
    local largest_window='' largest_area=0
    local -a search_arguments=(--class '^steam$')

    if [[ "$visibility" == visible ]]; then
        search_arguments=(--onlyvisible "${search_arguments[@]}")
    fi

    while IFS= read -r window; do
        [[ "$window" =~ ^[0-9]+$ ]] || continue
        geometry="$(DISPLAY="$display" timeout 3 \
            xdotool getwindowgeometry --shell "$window" 2>/dev/null || true)"
        width="$(sed -n 's/^WIDTH=//p' <<<"$geometry")"
        height="$(sed -n 's/^HEIGHT=//p' <<<"$geometry")"
        [[ "$width" =~ ^[0-9]+$ && "$height" =~ ^[0-9]+$ ]] || continue
        (( width >= minimum_window_width && height >= minimum_window_height )) ||
            continue
        area=$((width * height))
        if (( area > largest_area )); then
            largest_window="$window"
            largest_area="$area"
        fi
    done < <(DISPLAY="$display" timeout 5 \
        xdotool search "${search_arguments[@]}" 2>/dev/null || true)

    [[ -n "$largest_window" ]] && printf '%s\n' "$largest_window"
}

surface_steam_window() {
    local window="$1"
    DISPLAY="$display" timeout 5 xdotool windowmap "$window" >/dev/null 2>&1 ||
        return 1
    DISPLAY="$display" timeout 5 xdotool windowraise "$window" >/dev/null 2>&1 ||
        return 1
    # Direct X focus works in this deliberately WM-less, single-app session.
    # It avoids starting Plasma or a standalone WM just to expose Steam.
    DISPLAY="$display" timeout 5 xdotool windowfocus "$window" >/dev/null 2>&1 ||
        return 1
}

wait_for_steam_window() {
    local _ window candidate
    for _ in $(seq 1 "$window_timeout"); do
        window="$(largest_steam_window visible || true)"
        if [[ -n "$window" ]]; then
            printf '%s\n' "$window"
            return 0
        fi

        # Steam can create its full-size CEF window without mapping it when no
        # desktop session exists. A live process and responsive DISPLAY are not
        # enough: expose that existing window, then verify it became visible.
        candidate="$(largest_steam_window any || true)"
        if [[ -n "$candidate" ]]; then
            surface_steam_window "$candidate" || true
        fi
        sleep 1
    done
    return 1
}

cgroup_class() {
    local pid="$1" controller="$2"
    sed -n "s#^[0-9][0-9]*:${controller}:##p" "/proc/$pid/cgroup" 2>/dev/null |
        head -n 1
}

warn_if_backgrounded() {
    local label="$1" pid="$2" cpuset cpu
    cpuset="$(cgroup_class "$pid" cpuset)"
    cpu="$(cgroup_class "$pid" cpu)"
    if [[ "$cpuset" != /top-app || "$cpu" != /top-app ]]; then
        warn "$label PID $pid is cpuset=${cpuset:-unknown}, cpu=${cpu:-unknown}; Android did not promote this shell descendant to /top-app"
    fi
}

x11_bridge_has_dead_binder() {
    local pid="$1" since recent
    since="$(date +%s)"
    sleep 2
    recent="$(timeout 5 logcat -d -t 400 -v epoch 2>/dev/null)" ||
        return 2
    awk -v since="$since" -v pid="$pid" '
        $1 + 0 >= since && $2 == pid && /DeadObjectException/ { found = 1 }
        END { exit !found }
    ' <<<"$recent"
}

for value_name in process_timeout window_timeout minimum_window_width \
        minimum_window_height; do
    value="${!value_name}"
    [[ "$value" =~ ^[1-9][0-9]*$ ]] ||
        fail "$value_name must be a positive integer (got: $value)"
done

for command in am cmd termux-x11 termux-x11-preference timeout xdpyinfo \
        xdotool pactl pulseaudio stat unlink logcat; do
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
# the activity first so a cold launch receives one clean server connection.
# Android may still classify shell descendants as background; that is measured
# and reported below instead of being inferred from activity launch success.
foreground_x11

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
        if x11_is_ready; then
            fail "display $display responds without a validated Termux:X11 server"
        fi
        if [[ -e "$x11_socket" || -L "$x11_socket" ]]; then
            if [[ -S "$x11_socket" && ! -L "$x11_socket" ]] &&
                    [[ "$(stat -c %u -- "$x11_socket")" == "$(id -u)" ]]; then
                # A normal server SIGTERM can leave this exact pathname behind.
                # It is safe to reclaim only after the display is unreachable,
                # no matching server exists, and the target is our owned socket.
                unlink -- "$x11_socket"
                printf 'start-steam: reclaimed stale owned X socket %s\n' \
                    "$x11_socket"
            else
                fail "display path exists but is not a reclaimable owned socket: $x11_socket"
            fi
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

# A second handoff is required after a cold server start. Merely starting the
# activity before the server can leave a responsive X socket behind a black
# Android surface.
foreground_x11

if x11_bridge_has_dead_binder "${x11_pids[0]}"; then
    fail "X server ${x11_pids[0]} has a stale Android Binder bridge; X clients cannot migrate, so stop them and restart this server"
else
    bridge_status=$?
    [[ "$bridge_status" -ne 2 ]] ||
        fail 'unable to inspect the Termux:X11 Android bridge log'
fi

if ! x11_input="$(DISPLAY="$display" timeout 5 \
        xdpyinfo -ext XInputExtension 2>/dev/null)"; then
    fail 'unable to query X11 input devices'
fi
for input_device in '"Lorie mouse"' '"Lorie touch"' '"Lorie keyboard"'; do
    grep -Fq "$input_device" <<<"$x11_input" ||
        fail "Termux:X11 input device is unavailable: $input_device"
done

"$pulse_helper" "$base"
export PULSE_SERVER="$pulse_server"
pactl --server="$pulse_server" info >/dev/null 2>&1 ||
    fail 'PulseAudio TCP endpoint is unavailable after preparation'
if ! pulse_sinks="$(pactl --server="$pulse_server" list short sinks 2>/dev/null)" ||
        [[ -z "$pulse_sinks" ]]; then
    fail 'PulseAudio is reachable but exposes no audio sink'
fi

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
    if ! steam_window="$(wait_for_steam_window)"; then
        fail "Steam PID ${steam_pids[0]} exists but no usable window became visible in ${window_timeout}s"
    fi
    foreground_x11
    surface_steam_window "$steam_window" ||
        fail "Steam window $steam_window could not be mapped, raised, and focused"
    warn_if_backgrounded X11 "${x11_pids[0]}"
    warn_if_backgrounded Steam "${steam_pids[0]}"
    printf 'start-steam: ready; X11 PID %s, Steam PID %s, window %s visible, PulseAudio sink, Lorie mouse/touch/keyboard, no KDE\n' \
        "${x11_pids[0]}" "${steam_pids[0]}" "$steam_window"
    exit 0
fi

mapfile -t launcher_pids < <(matching_pids launcher)
if [[ "${#launcher_pids[@]}" -gt 1 ]]; then
    fail "multiple Steam launcher processes found: ${launcher_pids[*]}"
fi

if [[ "${#launcher_pids[@]}" -eq 1 ]]; then
    launcher_pid="${launcher_pids[0]}"
    steam_log="$base/logs"
    printf 'start-steam: attaching to Steam initialization under launcher PID %s\n' \
        "$launcher_pid"
else
    steam_log="$base/logs/start-steam-$(date +%Y%m%d-%H%M%S).log"
    nohup env DISPLAY="$display" PULSE_SERVER="$pulse_server" \
        STEAM_ARM64_FEX_PROFILE="$profile" "$steam_launcher" -noshaders "$@" \
        >"$steam_log" 2>&1 </dev/null &
    launcher_pid=$!
fi

for _ in $(seq 1 "$process_timeout"); do
    mapfile -t steam_pids < <(matching_pids steam)
    if [[ "${#steam_pids[@]}" -eq 1 ]]; then
        break
    fi
    if [[ "${#steam_pids[@]}" -gt 1 ]]; then
        fail "multiple Steam main processes found: ${steam_pids[*]}"
    fi
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        fail "Steam launcher exited before Steam appeared; inspect $steam_log"
    fi
    sleep 1
done

[[ "${#steam_pids[@]}" -eq 1 ]] ||
    fail "Steam did not appear in ${process_timeout}s; inspect $steam_log"
if ! steam_window="$(wait_for_steam_window)"; then
    fail "Steam PID ${steam_pids[0]} exists but no usable window became visible in ${window_timeout}s; inspect $steam_log"
fi
foreground_x11
surface_steam_window "$steam_window" ||
    fail "Steam window $steam_window could not be mapped, raised, and focused"
warn_if_backgrounded X11 "${x11_pids[0]}"
warn_if_backgrounded Steam "${steam_pids[0]}"
printf 'start-steam: ready; X11 PID %s, Steam PID %s, window %s visible, PulseAudio sink, Lorie mouse/touch/keyboard, FEX %s, no KDE\n' \
    "${x11_pids[0]}" "${steam_pids[0]}" "$steam_window" "$profile"
