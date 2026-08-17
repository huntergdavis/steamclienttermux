#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

steam_start="${STEAM_START_SCRIPT:-$HOME/start-steam-native.sh}"
[[ -x "$steam_start" ]] || {
    printf 'start-gtaiv-native: native Steam launcher is unavailable: %s\n' \
        "$steam_start" >&2
    exit 1
}

export STEAM_BACKGROUND=1
declare -a native_options=()
if [[ ${1:-} == --proton-log ]]; then
    native_options+=(--proton-log)
    shift
fi

retry_count=${GTAIV_LAUNCH_RETRIES:-1}
retry_wait=${GTAIV_RETRY_WAIT_SECONDS:-1200}
window_stable_seconds=${GTAIV_WINDOW_STABLE_SECONDS:-30}
supervise_poll=${GTAIV_SUPERVISE_POLL_SECONDS:-5}
base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
proc_root=${GTAIV_PROC_ROOT:-/proc}
gameprocess_log=${GTAIV_GAMEPROCESS_LOG:-$base/client/logs/gameprocess_log.txt}
display=${STEAM_X11_DISPLAY:-:0}
xdotool_command=${GTAIV_XDOTOOL:-xdotool}
declare -a launch_command=(
    "$steam_start" "${native_options[@]}" --appid 12210 -- "$@"
)

for value_name in retry_count retry_wait window_stable_seconds supervise_poll; do
    value=${!value_name}
    [[ $value =~ ^[0-9]+$ ]] || {
        printf 'start-gtaiv-native: %s must be an integer\n' "$value_name" >&2
        exit 2
    }
done
(( retry_wait > 0 && window_stable_seconds > 0 && supervise_poll > 0 )) || {
    printf 'start-gtaiv-native: wait and stability values must be positive\n' >&2
    exit 2
}

# Preserve a direct, acknowledgement-only path for controlled diagnostics.
if (( retry_count == 0 )); then
    exec "${launch_command[@]}"
fi
command -v "$xdotool_command" >/dev/null 2>&1 || {
    printf 'start-gtaiv-native: xdotool is unavailable: %s\n' \
        "$xdotool_command" >&2
    exit 1
}

# Do not put AppID 12210 on Steam's own cold-start command line. Establish the
# remembered-login-ready native client first, then forward the Rockstar game.
"$steam_start"

process_is_top_app() {
    local process=$1 cpuset cpu
    [[ -r $process/cgroup ]] || return 1
    cpuset=$(sed -n 's#^[0-9][0-9]*:cpuset:##p' "$process/cgroup" | head -n 1)
    cpu=$(sed -n 's#^[0-9][0-9]*:cpu:##p' "$process/cgroup" | head -n 1)
    [[ $cpuset == /top-app && $cpu == /top-app ]]
}

verified_game_identity() {
    local require_top_app=$1 process environment compatdata
    for process in "$proc_root"/[0-9]*; do
        [[ -r $process/comm && -r $process/environ ]] || continue
        [[ $(<"$process/comm") == GTAIV.exe ]] || continue
        environment=$(tr '\0' '\n' <"$process/environ" 2>/dev/null || true)
        grep -Fxq 'STEAM_COMPAT_APP_ID=12210' <<<"$environment" || continue
        compatdata=$(sed -n 's/^STEAM_COMPAT_DATA_PATH=//p' <<<"$environment")
        case "$compatdata" in
            "$base/removable-library/steamapps/compatdata/12210"|"$base/removable-library-compatdata/12210")
                if (( require_top_app == 0 )) || process_is_top_app "$process"; then
                    return 0
                fi
                ;;
        esac
    done
    return 1
}

verified_game_running() {
    verified_game_identity 1
}

verified_game_exists() {
    verified_game_identity 0
}

visible_game_window() {
    DISPLAY="$display" timeout 2 "$xdotool_command" search --onlyvisible \
        --class '^steam_app_12210$' 2>/dev/null | grep -Eq '^[0-9]+$'
}

app_removed_since() {
    local offset=$1 size
    [[ -f $gameprocess_log && ! -L $gameprocess_log ]] || return 1
    size=$(stat -c %s -- "$gameprocess_log" 2>/dev/null || true)
    [[ $size =~ ^[0-9]+$ && $size -ge $offset ]] || return 1
    tail -c "+$((offset + 1))" -- "$gameprocess_log" |
        grep -F 'Remove 12210 from running list' >/dev/null
}

for ((attempt = 0; attempt <= retry_count; attempt++)); do
    log_offset=$(stat -c %s -- "$gameprocess_log" 2>/dev/null || printf '0\n')
    [[ $log_offset =~ ^[0-9]+$ ]] || log_offset=0
    "${launch_command[@]}"

    removed=0
    stable_since=-1
    for _ in $(seq 1 "$retry_wait"); do
        if verified_game_running && visible_game_window; then
            if (( stable_since < 0 )); then
                stable_since=$SECONDS
            elif (( SECONDS - stable_since >= window_stable_seconds )); then
                printf 'start-gtaiv-native: verified top-app GTAIV.exe and visible game window for %ss on attempt %s\n' \
                    "$window_stable_seconds" "$((attempt + 1))"
                while verified_game_exists; do
                    sleep "$supervise_poll"
                done
                printf 'start-gtaiv-native: GTAIV.exe exited; foreground supervision complete\n'
                exit 0
            fi
        else
            stable_since=-1
        fi
        if app_removed_since "$log_offset"; then
            removed=1
            break
        fi
        sleep 1
    done

    if (( removed == 0 )); then
        printf 'start-gtaiv-native: Steam acknowledged AppID 12210 but no verified GTA IV window appeared in %ss\n' \
            "$retry_wait" >&2
        exit 1
    fi
    if (( attempt == retry_count )); then
        printf 'start-gtaiv-native: AppID 12210 exited before durable game readiness after %s attempt(s)\n' \
            "$((attempt + 1))" >&2
        exit 1
    fi
    printf 'start-gtaiv-native: pre-game exit detected; retrying through the stable Steam client (%s/%s)\n' \
        "$((attempt + 1))" "$retry_count" >&2
done
