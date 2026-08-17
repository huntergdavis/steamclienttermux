#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

force=0
dry_run=0
keep_pulse=0

usage() {
    cat <<'EOF'
Usage: ~/stop-steam.sh [--force] [--dry-run] [--keep-pulse]

Gracefully stop a steamclienttermux session, then stop its Termux:X11 server.
An active Steam game is protected unless --force is supplied. The Android
Termux and Termux:X11 packages are never force-stopped.
EOF
}

while (( $# > 0 )); do
    case "$1" in
        --force)
            force=1
            ;;
        --dry-run)
            dry_run=1
            ;;
        --keep-pulse)
            keep_pulse=1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'stop-steam: unknown argument: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

base="${STEAM_ARM64_BASE:-$HOME/steam-arm64}"
display="${STEAM_X11_DISPLAY:-:0}"
steam_launcher="${STEAM_ARM64_LAUNCHER:-$HOME/bin/steam-arm}"
affinity_helper="$base/compat-bin/set-tombraider-affinity.py"
session_guard="$base/compat-bin/steam-arm64-session-guard.py"
process_match_helper="$base/compat-bin/steam-arm64-process-match.sh"
x11_socket="${PREFIX:-}/tmp/.X11-unix/X${display#:}"
steam_timeout="${STEAM_STOP_TIMEOUT:-60}"
term_timeout="${STEAM_TERM_TIMEOUT:-15}"
x11_timeout="${X11_STOP_TIMEOUT:-10}"
pulse_server="tcp:127.0.0.1:4713"

fail() {
    printf 'stop-steam: %s\n' "$1" >&2
    exit 1
}

for timeout_name in steam_timeout term_timeout x11_timeout; do
    timeout_value="${!timeout_name}"
    [[ "$timeout_value" =~ ^[1-9][0-9]*$ ]] ||
        fail "$timeout_name must be a positive integer"
done
[[ -n "${PREFIX:-}" ]] || fail 'PREFIX is not set; run this from Termux'
[[ "$display" =~ ^:[0-9]+$ ]] || fail "invalid X display: $display"
[[ -f $process_match_helper && ! -L $process_match_helper ]] ||
    fail "process matcher is unavailable: $process_match_helper"
# shellcheck source=/dev/null
source "$process_match_helper"

process_matches() {
    local pid="$1" kind="$2" cmdline first_argument
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    first_argument="${cmdline%% *}"
    case "$kind" in
        game)
            [[ "$cmdline" == *'SteamLaunch AppId='* ]]
            ;;
        steam)
            steam_arm64_process_matches "$pid" \
                "$base/client/steamrtarm64/steam"
            ;;
        steamwebhelper)
            steam_arm64_process_matches "$pid" \
                "$base/client/steamrtarm64/steamwebhelper"
            ;;
        launcher)
            [[ "$cmdline" == *" $steam_launcher "* ||
                "$cmdline" == *" $steam_launcher" ]]
            ;;
        affinity)
            [[ "$cmdline" == *" $affinity_helper "* ||
                "$cmdline" == *" $affinity_helper" ]]
            ;;
        session_guard)
            [[ "$cmdline" == *" $session_guard "* ||
                "$cmdline" == *" $session_guard" ]]
            ;;
        x11)
            [[ "$cmdline" == "termux-x11 com.termux.x11 ${display} "* ]]
            ;;
        pulse)
            [[ "$first_argument" == pulseaudio ||
                "$first_argument" == "${PREFIX}/bin/pulseaudio" ]]
            ;;
        *)
            return 1
            ;;
    esac
}

matching_pids() {
    local kind="$1" process
    for process in /proc/[0-9]*; do
        process_matches "${process#/proc/}" "$kind" || continue
        printf '%s\n' "${process#/proc/}"
    done
}

wait_until_absent() {
    local kind="$1" seconds="$2" second
    for ((second = 0; second < seconds; ++second)); do
        [[ -z "$(matching_pids "$kind")" ]] && return 0
        sleep 1
    done
    [[ -z "$(matching_pids "$kind")" ]]
}

signal_kind() {
    local signal="$1" kind="$2" label="$3" pid
    local -a pids=()
    mapfile -t pids < <(matching_pids "$kind")
    for pid in "${pids[@]}"; do
        process_matches "$pid" "$kind" || continue
        if (( dry_run != 0 )); then
            printf 'stop-steam: would send %s to %s PID %s\n' \
                "$signal" "$label" "$pid"
        else
            kill "-$signal" "$pid" 2>/dev/null || true
        fi
    done
}

mapfile -t game_pids < <(matching_pids game)
if (( ${#game_pids[@]} > 0 && force == 0 )); then
    if (( dry_run != 0 )); then
        printf 'stop-steam: active Steam game protected: PIDs %s\n' \
            "${game_pids[*]}"
        printf 'stop-steam: a normal run would stop here; exit the game or use --force\n'
    else
        fail "a Steam game is still active (PIDs ${game_pids[*]}); exit it or use --force"
    fi
fi

mapfile -t steam_pids < <(matching_pids steam)
if (( ${#steam_pids[@]} > 0 )); then
    if (( dry_run != 0 )); then
        printf 'stop-steam: would request graceful shutdown from Steam PID(s) %s\n' \
            "${steam_pids[*]}"
    else
        [[ -x "$steam_launcher" ]] ||
            fail "Steam is live but its launcher is unavailable: $steam_launcher"
        mkdir -p "$base/logs"
        shutdown_log="$base/logs/stop-steam-$(date +%Y%m%d-%H%M%S).log"
        nohup env DISPLAY="$display" "$steam_launcher" -shutdown \
            >"$shutdown_log" 2>&1 </dev/null &
        printf 'stop-steam: graceful Steam shutdown requested; log %s\n' \
            "$shutdown_log"
        if wait_until_absent steam "$steam_timeout"; then
            printf 'stop-steam: Steam exited cleanly\n'
        else
            printf 'stop-steam: Steam did not exit in %ss; sending TERM\n' \
                "$steam_timeout" >&2
        fi
    fi
else
    printf 'stop-steam: Steam is already stopped; no -shutdown client was started\n'
fi

# Exact-path cleanup handles an interrupted forwarder or session guard. Killing
# the Steam main process causes its --kill-on-exit PRoot parent to unwind.
signal_kind TERM steam steam
signal_kind TERM steamwebhelper steamwebhelper
signal_kind TERM affinity 'affinity guard'
signal_kind TERM session_guard 'session guard'
signal_kind TERM launcher 'Steam launcher'
if (( dry_run == 0 )); then
    sleep 1
    wait_until_absent steam "$term_timeout" || true
    wait_until_absent launcher "$term_timeout" || true
fi
signal_kind KILL steam steam
signal_kind KILL steamwebhelper steamwebhelper
signal_kind KILL affinity 'affinity guard'
signal_kind KILL session_guard 'session guard'
signal_kind KILL launcher 'Steam launcher'

signal_kind TERM x11 'Termux:X11 server'
if (( dry_run == 0 )); then
    wait_until_absent x11 "$x11_timeout" || true
fi
signal_kind KILL x11 'Termux:X11 server'

if (( dry_run == 0 )) && [[ -e "$x11_socket" || -L "$x11_socket" ]]; then
    if [[ -z "$(matching_pids x11)" ]] &&
            ! DISPLAY="$display" timeout 3 xdpyinfo >/dev/null 2>&1 &&
            [[ -S "$x11_socket" && ! -L "$x11_socket" ]] &&
            [[ "$(stat -c %u -- "$x11_socket")" == "$(id -u)" ]]; then
        unlink -- "$x11_socket"
        printf 'stop-steam: removed stale owned X socket %s\n' "$x11_socket"
    fi
fi

if (( keep_pulse == 0 )); then
    if (( dry_run != 0 )); then
        signal_kind TERM pulse PulseAudio
    else
        pactl --server="$pulse_server" exit >/dev/null 2>&1 || true
        wait_until_absent pulse 5 || true
        signal_kind TERM pulse PulseAudio
        wait_until_absent pulse 5 || true
        signal_kind KILL pulse PulseAudio
    fi
else
    printf 'stop-steam: keeping PulseAudio running\n'
fi

if (( dry_run != 0 )); then
    printf 'stop-steam: dry run complete; nothing was changed\n'
else
    printf 'stop-steam: Steam, session helpers, and X display %s are stopped\n' \
        "$display"
fi
