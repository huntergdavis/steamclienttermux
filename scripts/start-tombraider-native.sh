#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

steam_start="${STEAM_START_SCRIPT:-$HOME/start-steam-native.sh}"
[[ -x "$steam_start" ]] || {
    printf 'start-tombraider-native: native Steam launcher is unavailable: %s\n' \
        "$steam_start" >&2
    exit 1
}

# Keep the same direct, backgrounded Tomb Raider route as start-tombraider.sh,
# but select the no-PRoot Steam/CEF host. Additional game arguments are kept.
export STEAM_BACKGROUND=1
declare -a native_options=()
if [[ ${1:-} == --proton-log ]]; then
    native_options+=(--proton-log)
    shift
fi

retry_count=${TOMB_RAIDER_LAUNCH_RETRIES:-1}
retry_wait=${TOMB_RAIDER_RETRY_WAIT_SECONDS:-180}
window_stable_seconds=${TOMB_RAIDER_WINDOW_STABLE_SECONDS:-30}
supervise_poll=${TOMB_RAIDER_SUPERVISE_POLL_SECONDS:-5}
base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
proc_root=${TOMB_RAIDER_PROC_ROOT:-/proc}
gameprocess_log=${TOMB_RAIDER_GAMEPROCESS_LOG:-$base/client/logs/gameprocess_log.txt}
display=${STEAM_X11_DISPLAY:-:0}
xdotool_command=${TOMB_RAIDER_XDOTOOL:-xdotool}
declare -a launch_command=(
    "$steam_start" "${native_options[@]}" --appid 203160 -- -nolauncher "$@"
)

[[ $retry_count =~ ^[0-9]+$ ]] || {
    printf 'start-tombraider-native: TOMB_RAIDER_LAUNCH_RETRIES must be nonnegative\n' >&2
    exit 2
}
[[ $retry_wait =~ ^[1-9][0-9]*$ ]] || {
    printf 'start-tombraider-native: TOMB_RAIDER_RETRY_WAIT_SECONDS must be positive\n' >&2
    exit 2
}
[[ $window_stable_seconds =~ ^[1-9][0-9]*$ ]] || {
    printf 'start-tombraider-native: TOMB_RAIDER_WINDOW_STABLE_SECONDS must be positive\n' >&2
    exit 2
}
[[ $supervise_poll =~ ^[1-9][0-9]*$ ]] || {
    printf 'start-tombraider-native: TOMB_RAIDER_SUPERVISE_POLL_SECONDS must be positive\n' >&2
    exit 2
}
# Preserve the original thin-wrapper behavior for explicit callers and the
# argument-contract test. Production defaults to one verified fast-exit retry.
if (( retry_count == 0 )); then
    exec "${launch_command[@]}"
fi
command -v "$xdotool_command" >/dev/null 2>&1 || {
    printf 'start-tombraider-native: xdotool is unavailable: %s\n' \
        "$xdotool_command" >&2
    exit 1
}

# A game passed on Steam's own cold-start command line repeatedly reaches the
# window and then loses PRoot vPID 1 to signal 1. The same AppID forwarded to
# the remembered-login-ready client is stable, so establish that client first.
# With an existing client this is a quick, focus-free readiness check.
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
        [[ $(<"$process/comm") == TombRaider.exe ]] || continue
        environment=$(tr '\0' '\n' <"$process/environ" 2>/dev/null || true)
        grep -Fxq 'STEAM_COMPAT_APP_ID=203160' <<<"$environment" || continue
        compatdata=$(sed -n 's/^STEAM_COMPAT_DATA_PATH=//p' <<<"$environment")
        case "$compatdata" in
            "$base/removable-library/steamapps/compatdata/203160"|"$base/removable-library-compatdata/203160")
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
        --class '^steam_app_203160$' 2>/dev/null | grep -Eq '^[0-9]+$'
}

app_removed_since() {
    local offset=$1 size
    [[ -f $gameprocess_log && ! -L $gameprocess_log ]] || return 1
    size=$(stat -c %s -- "$gameprocess_log" 2>/dev/null || true)
    [[ $size =~ ^[0-9]+$ && $size -ge $offset ]] || return 1
    tail -c "+$((offset + 1))" -- "$gameprocess_log" |
        grep -F 'Remove 203160 from running list' >/dev/null
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
                printf 'start-tombraider-native: verified top-app TombRaider.exe and visible game window for %ss on attempt %s\n' \
                    "$window_stable_seconds" "$((attempt + 1))"
                # RunCommandService owns the foreground Android lifetime. Its
                # shell exiting has repeatedly delivered signal 1 to the game
                # container in the same second, so supervise until game exit.
                while verified_game_exists; do
                    sleep "$supervise_poll"
                done
                printf 'start-tombraider-native: TombRaider.exe exited; foreground supervision complete\n'
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
        printf 'start-tombraider-native: Steam acknowledged AppID 203160 but no verified game window appeared in %ss\n' \
            "$retry_wait" >&2
        exit 1
    fi
    if (( attempt == retry_count )); then
        printf 'start-tombraider-native: AppID 203160 exited before the verified game process after %s attempt(s)\n' \
            "$((attempt + 1))" >&2
        exit 1
    fi
    printf 'start-tombraider-native: fast pre-game exit detected; retrying through the stable Steam client (%s/%s)\n' \
        "$((attempt + 1))" "$retry_count" >&2
done
