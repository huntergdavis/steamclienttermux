#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

requested_appid=''
background_mode="${STEAM_BACKGROUND:-}"
convenience_appid=0
declare -a steam_arguments=("$@")

if [[ "${1:-}" == --appid ]]; then
    [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || {
        printf 'start-steam: --appid requires a positive numeric Steam AppID\n' >&2
        exit 1
    }
    requested_appid="$2"
    convenience_appid=1
    shift 2
    [[ "${1:-}" == -- ]] && shift
    steam_arguments=(-applaunch "$requested_appid" "$@")
elif [[ "${1:-}" =~ ^[1-9][0-9]*$ ]]; then
    requested_appid="$1"
    convenience_appid=1
    shift
    [[ "${1:-}" == -- ]] && shift
    steam_arguments=(-applaunch "$requested_appid" "$@")
else
    for ((argument_index = 0;
            argument_index < ${#steam_arguments[@]};
            argument_index++)); do
        if [[ "${steam_arguments[argument_index]}" == -applaunch ]]; then
            appid_index=$((argument_index + 1))
            [[ "${steam_arguments[appid_index]:-}" =~ ^[1-9][0-9]*$ ]] || {
                printf 'start-steam: -applaunch requires a positive numeric Steam AppID\n' >&2
                exit 1
            }
            requested_appid="${steam_arguments[appid_index]}"
            break
        fi
    done
fi

if [[ -z "$background_mode" ]]; then
    background_mode="$convenience_appid"
fi
[[ "$background_mode" == 0 || "$background_mode" == 1 ]] || {
    printf 'start-steam: STEAM_BACKGROUND must be 0 or 1\n' >&2
    exit 1
}
skip_game_affinity_guard=${STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD:-0}
[[ $skip_game_affinity_guard == 0 || $skip_game_affinity_guard == 1 ]] || {
    printf 'start-steam: STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD must be 0 or 1\n' >&2
    exit 1
}
if [[ $skip_game_affinity_guard == 1 && $requested_appid != 203160 ]]; then
    printf 'start-steam: affinity-guard suppression is valid only for AppID 203160\n' >&2
    exit 1
fi
forward_bootstrap=${STEAM_ARM64_FORWARD_BOOTSTRAP:-fast}
[[ $forward_bootstrap == strict || $forward_bootstrap == fast ]] || {
    printf 'start-steam: STEAM_ARM64_FORWARD_BOOTSTRAP must be strict or fast\n' >&2
    exit 1
}
hidapi_mode=${STEAM_ARM64_HIDAPI:-default}
[[ $hidapi_mode == default || $hidapi_mode == disabled ]] || {
    printf 'start-steam: STEAM_ARM64_HIDAPI must be default or disabled\n' >&2
    exit 1
}
cef_affinity=${STEAM_ARM64_CEF_AFFINITY:-auto}
[[ $cef_affinity == auto || $cef_affinity == compact ||
        $cef_affinity == responsive || $cef_affinity == launch-boost ]] || {
    printf 'start-steam: STEAM_ARM64_CEF_AFFINITY must be auto, compact, responsive, or launch-boost\n' >&2
    exit 1
}
if [[ $cef_affinity == launch-boost && -z $requested_appid ]]; then
    printf 'start-steam: launch-boost CEF affinity requires an AppID\n' >&2
    exit 1
fi
cef_launch_boost=0
cef_cpu_mask=0
if [[ $cef_affinity == responsive ||
        ($cef_affinity == auto && -z $requested_appid &&
            $background_mode == 0) ]]; then
    cef_cpu_mask=0-3
elif [[ $cef_affinity == launch-boost ||
        ($cef_affinity == auto && -n $requested_appid) ]]; then
    cef_cpu_mask=0-3
    cef_launch_boost=1
fi
if [[ "$background_mode" == 1 ]]; then
    has_silent=0
    for argument in "${steam_arguments[@]}"; do
        [[ "$argument" == -silent ]] && has_silent=1
    done
    if [[ "$has_silent" == 0 ]]; then
        steam_arguments=(-silent "${steam_arguments[@]}")
    fi
fi

if [[ "${START_STEAM_PARSE_ONLY:-0}" == 1 ]]; then
    printf 'appid=%s\nbackground=%s\nargc=%s\n' \
        "$requested_appid" "$background_mode" "${#steam_arguments[@]}"
    for argument in "${steam_arguments[@]}"; do
        printf 'arg=%s\n' "$argument"
    done
    exit 0
fi

display="${STEAM_X11_DISPLAY:-:0}"
base="${STEAM_ARM64_BASE:-$HOME/steam-arm64}"
steam_launcher="${STEAM_ARM64_LAUNCHER:-$HOME/bin/steam-arm}"
pulse_helper="$base/prepare-pulseaudio-tcp.sh"
affinity_helper="$base/compat-bin/set-tombraider-affinity.py"
gtaiv_affinity_helper="$base/compat-bin/set-gtaiv-affinity.py"
process_match_helper="$base/compat-bin/steam-arm64-process-match.sh"
forward_dispatcher="$base/compat-bin/steam-arm64-forward-dispatch"
affinity_lock="$base/runtime/tomb-raider-affinity.lock"
gtaiv_affinity_lock="$base/runtime/gtaiv-affinity.lock"
steam_affinity_stamp="$base/runtime/steam-session-affinity-v1"
x11_component="com.termux.x11/com.termux.x11.MainActivity"
x11_preferences="/data/data/com.termux.x11/shared_prefs/com.termux.x11_preferences.xml"
x11_socket="${PREFIX:-}/tmp/.X11-unix/X${display#:}"
x11_log="$base/logs/termux-x11-minimal.log"
profile="${STEAM_ARM64_FEX_PROFILE:-safe}"
process_timeout="${STEAM_PROCESS_TIMEOUT:-180}"
duplicate_process_timeout="${STEAM_DUPLICATE_PROCESS_TIMEOUT:-10}"
window_timeout="${STEAM_WINDOW_TIMEOUT:-1200}"
app_timeout="${STEAM_APP_TIMEOUT:-1200}"
window_stable_seconds="${STEAM_WINDOW_STABLE_SECONDS:-5}"
minimum_window_width="${STEAM_MIN_WINDOW_WIDTH:-640}"
minimum_window_height="${STEAM_MIN_WINDOW_HEIGHT:-400}"
pulse_server="tcp:127.0.0.1:4713"
login_log="$base/client/logs/steamui_login.txt"
login_users="$base/client/config/loginusers.vdf"
gameprocess_log="$base/client/logs/gameprocess_log.txt"

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
    local kind="$1" process pid cmdline
    local -a arguments=() candidates=()
    case "$kind" in
        x11)
            mapfile -t candidates < <(
                pgrep -f -u "$(id -u)" -- "com.termux.x11 ${display}" || true
            )
            ;;
        steam)
            mapfile -t candidates < <(
                pgrep -f -u "$(id -u)" -- 'steamrtarm64/steam($| )' || true
            )
            ;;
        steamwebhelper)
            mapfile -t candidates < <(
                pgrep -f -u "$(id -u)" -- \
                    'steamrtarm64/steamwebhelper($| )' || true
            )
            ;;
        *)
            for process in /proc/[0-9]*; do
                candidates+=("${process#/proc/}")
            done
            ;;
    esac
    for pid in "${candidates[@]}"; do
        [[ $pid =~ ^[1-9][0-9]*$ ]] || continue
        process=/proc/$pid
        [[ -r "$process/cmdline" ]] || continue
        case "$kind" in
            x11)
                arguments=()
                mapfile -d '' -t arguments < "$process/cmdline" || continue
                [[ ${arguments[0]:-} == "termux-x11 com.termux.x11 ${display} "* ||
                        (${arguments[0]:-} == termux-x11 &&
                            ${arguments[1]:-} == com.termux.x11 &&
                            ${arguments[2]:-} == "$display") ]] || continue
                ;;
            steam)
                steam_arm64_process_matches "$pid" \
                    "$base/client/steamrtarm64/steam" ||
                    continue
                ;;
            steamwebhelper)
                steam_arm64_process_matches "$pid" \
                    "$base/client/steamrtarm64/steamwebhelper" || continue
                ;;
            launcher)
                cmdline="$(tr '\0' ' ' <"$process/cmdline" 2>/dev/null || true)"
                [[ "$cmdline" == *" $steam_launcher "* ||
                        "$cmdline" == *" $steam_launcher" ]] || continue
                ;;
            *)
                fail "internal process selector is invalid: $kind"
                ;;
        esac
        printf '%s\n' "$pid"
    done
}

steam_pid_is_current() {
    steam_arm64_process_matches "$1" "$base/client/steamrtarm64/steam"
}

steam_hidapi_mode_matches() {
    local pid="$1" entry actual= control=default
    [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/environ ]] || return 1
    while IFS= read -r -d '' entry; do
        case $entry in
            SDL_JOYSTICK_HIDAPI=*) actual=${entry#*=} ;;
            STEAM_ARM64_HIDAPI=*) control=${entry#*=} ;;
        esac
    done < "/proc/$pid/environ"
    case $hidapi_mode in
        default) [[ $control == default && -z $actual ]] ;;
        disabled) [[ $control == disabled && $actual == 0 ]] ;;
    esac
}

settle_steam_processes() {
    local _
    for _ in $(seq 1 "$duplicate_process_timeout"); do
        mapfile -t steam_pids < <(matching_pids steam)
        ((${#steam_pids[@]} <= 1)) && return 0
        sleep 1
    done
    return 1
}

x11_is_ready() {
    DISPLAY="$display" timeout 10 xdpyinfo >/dev/null 2>&1
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

configure_x11_preferences() {
    local _ output=''
    # The preference receiver can trail the activity handoff briefly on a
    # cold start. Retry only before an X server exists; never broadcast live
    # preference reloads into a rendering session.
    for _ in $(seq 1 5); do
        if output="$(timeout 10 termux-x11-preference \
                touchMode:Trackpad \
                'screenIdleTimeout:Never (keep screen on)' 2>&1)"; then
            return 0
        fi
        sleep 1
    done
    [[ -z "$output" ]] || printf 'start-steam: termux-x11-preference: %s\n' \
        "$output" >&2
    return 1
}

x11_preferences_are_configured() {
    [[ -f "$x11_preferences" && ! -L "$x11_preferences" ]] || return 1
    grep -Fq '<string name="touchMode">1</string>' "$x11_preferences" &&
        grep -Fq '<string name="screenIdleTimeout">never</string>' \
            "$x11_preferences"
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
    local expected_pid="$1" required_stable_count="${2:-$window_stable_seconds}"
    local _ window candidate stable_window='' stable_count=0
    for _ in $(seq 1 "$window_timeout"); do
        steam_pid_is_current "$expected_pid" || return 1
        window="$(largest_steam_window visible || true)"
        if [[ -n "$window" ]]; then
            if [[ "$window" == "$stable_window" ]]; then
                stable_count=$((stable_count + 1))
            else
                stable_window="$window"
                stable_count=1
            fi
            if (( stable_count >= required_stable_count )); then
                printf '%s\n' "$window"
                return 0
            fi
        else
            stable_window=''
            stable_count=0
        fi

        # Steam can create its full-size CEF window without mapping it when no
        # desktop session exists. A live process and responsive DISPLAY are not
        # enough: expose that existing window, then verify it became visible.
        if [[ -z "$window" && "$background_mode" == 0 ]]; then
            candidate="$(largest_steam_window any || true)"
            if [[ -n "$candidate" ]]; then
                surface_steam_window "$candidate" || true
            fi
        fi
        sleep 1
    done
    return 1
}

remembered_login_configured() {
    [[ -f "$login_users" && ! -L "$login_users" ]] || return 1
    grep -Eq '"RememberPassword"[[:space:]]+"1"' "$login_users"
}

steam_login_ready() {
    local offset="${1:-0}" size
    [[ -f "$login_log" && ! -L "$login_log" ]] || return 1
    if (( offset > 0 )); then
        size="$(stat -c %s -- "$login_log" 2>/dev/null || true)"
        [[ "$size" =~ ^[0-9]+$ && "$size" -ge "$offset" ]] || return 1
        tail -c "+$((offset + 1))" -- "$login_log" |
            grep -F 'SetLoginState: Success - OK' >/dev/null
        return
    fi
    awk '
        /Client version:/ { ready = 0 }
        /SetLoginState: Success - OK/ { ready = 1 }
        END { exit !ready }
    ' "$login_log"
}

wait_for_remembered_login() {
    local expected_pid="$1" offset="${2:-0}" _ candidate
    remembered_login_configured || return 0
    if (( offset == 0 )) && steam_login_ready; then
        return 0
    fi

    printf 'start-steam: waiting for remembered Steam login to complete\n' >&2
    for _ in $(seq 1 "$window_timeout"); do
        steam_pid_is_current "$expected_pid" || return 1
        steam_login_ready "$offset" && return 0
        # Keep a visible launch usable in the WM-free session, but a direct
        # AppID request deliberately leaves every Steam surface untouched.
        if [[ "$background_mode" == 0 ]]; then
            candidate="$(largest_steam_window any || true)"
            if [[ -n "$candidate" ]]; then
                surface_steam_window "$candidate" || true
            fi
        fi
        sleep 1
    done
    return 1
}

app_launch_seen() {
    local appid="$1" offset="$2" size
    [[ -f "$gameprocess_log" && ! -L "$gameprocess_log" ]] || return 1
    size="$(stat -c %s -- "$gameprocess_log" 2>/dev/null || true)"
    [[ "$size" =~ ^[0-9]+$ && "$size" -ge "$offset" ]] || return 1
    tail -c "+$((offset + 1))" -- "$gameprocess_log" |
        grep -F "AppID $appid adding PID" >/dev/null
}

wait_for_app_launch() {
    local expected_pid="$1" appid="$2" offset="$3" _
    printf 'start-steam: waiting for Steam AppID %s launch acknowledgement\n' \
        "$appid" >&2
    for _ in $(seq 1 "$app_timeout"); do
        steam_pid_is_current "$expected_pid" || return 1
        app_launch_seen "$appid" "$offset" && return 0
        sleep 1
    done
    return 1
}

read_process_cgroups() {
    local pid="$1" hierarchy controllers path
    steam_process_cpuset=
    steam_process_cpu=
    [[ $pid =~ ^[1-9][0-9]*$ && -r /proc/$pid/cgroup ]] || return 1
    while IFS=: read -r hierarchy controllers path; do
        [[ $hierarchy =~ ^[0-9]+$ && $path == /* ]] || continue
        case ",$controllers," in
            *,cpuset,*) [[ -n $steam_process_cpuset ]] ||
                steam_process_cpuset=$path ;;
        esac
        case ",$controllers," in
            *,cpu,*) [[ -n $steam_process_cpu ]] || steam_process_cpu=$path ;;
        esac
    done < "/proc/$pid/cgroup"
    [[ -n $steam_process_cpuset && -n $steam_process_cpu ]]
}

require_top_app() {
    local label="$1" pid="$2"
    read_process_cgroups "$pid" || true
    [[ $steam_process_cpuset == /top-app && $steam_process_cpu == /top-app ]] ||
        fail "$label PID $pid is cpuset=${steam_process_cpuset:-unknown}, cpu=${steam_process_cpu:-unknown}; refusing a four-core background launch. Open Termux visibly and run ~/start-steam.sh there"
}

process_is_top_app() {
    local pid="$1"
    read_process_cgroups "$pid" &&
        [[ $steam_process_cpuset == /top-app && $steam_process_cpu == /top-app ]]
}

wait_for_top_app() {
    local pid="$1" _
    for _ in $(seq 1 100); do
        process_is_top_app "$pid" && return 0
        sleep 0.05
    done
    return 1
}

read_status_cpu_mask() {
    local status="$1" key value
    steam_status_cpu_mask=
    [[ -r $status ]] || return 1
    while IFS=: read -r key value; do
        [[ $key == Cpus_allowed_list ]] || continue
        value=${value#"${value%%[![:space:]]*}"}
        [[ -n $value ]] || return 1
        steam_status_cpu_mask=$value
        return 0
    done < "$status"
    return 1
}

thread_masks_are() {
    local pid="$1" expected="$2" status count=0
    for status in "/proc/$pid/task/"[0-9]*/status; do
        read_status_cpu_mask "$status" || continue
        [[ $steam_status_cpu_mask == "$expected" ]] || return 1
        count=$((count + 1))
    done
    (( count > 0 ))
}

process_mask_is() {
    local pid="$1" expected="$2"
    read_status_cpu_mask "/proc/$pid/status" &&
        [[ $steam_status_cpu_mask == "$expected" ]]
}

apply_uniform_affinity() {
    local label="$1" pid="$2" mask="$3"
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/status" ]] ||
        fail "$label PID is no longer alive: $pid"
    # Warm forwarding commonly revisits the same X11, Steam, and CEF process
    # identities. Reading their masks is much cheaper than asking taskset to
    # rewrite every thread twice per request.
    if thread_masks_are "$pid" "$mask"; then
        return 0
    fi
    taskset -apc "$mask" "$pid" >/dev/null ||
        fail "unable to place $label PID $pid on CPUs $mask"
    thread_masks_are "$pid" "$mask" ||
        fail "$label PID $pid did not retain CPUs $mask"
}

apply_steam_session_affinity() {
    local x11_pid="$1" steam_pid="$2" helper_pid start_ticks signature
    local masks_current
    local stamp_tmp
    local -a helper_pids=()
    require_top_app X11 "$x11_pid"
    require_top_app Steam "$steam_pid"
    mapfile -t helper_pids < <(matching_pids steamwebhelper | sort -n)
    start_ticks=$(steam_arm64_process_start_ticks "$x11_pid") ||
        fail "unable to resolve X11 PID $x11_pid start identity"
    signature="version=1 x11=$x11_pid:$start_ticks:0-3"
    start_ticks=$(steam_arm64_process_start_ticks "$steam_pid") ||
        fail "unable to resolve Steam PID $steam_pid start identity"
    signature+=" steam=$steam_pid:$start_ticks:0-3 helpers="
    for helper_pid in "${helper_pids[@]}"; do
        require_top_app Steam-helper "$helper_pid"
        start_ticks=$(steam_arm64_process_start_ticks "$helper_pid") ||
            fail "unable to resolve Steam-helper PID $helper_pid start identity"
        signature+="$helper_pid:$start_ticks:$cef_cpu_mask,"
    done
    if [[ -f $steam_affinity_stamp && ! -L $steam_affinity_stamp ]] &&
            [[ $(<"$steam_affinity_stamp") == "$signature" ]] &&
            process_mask_is "$x11_pid" 0-3 &&
            process_mask_is "$steam_pid" 0-3; then
        masks_current=1
        for helper_pid in "${helper_pids[@]}"; do
            if ! process_mask_is "$helper_pid" "$cef_cpu_mask"; then
                masks_current=0
                break
            fi
        done
        (( masks_current == 0 )) || return 0
    fi
    apply_uniform_affinity X11 "$x11_pid" 0-3
    apply_uniform_affinity Steam "$steam_pid" 0-3
    for helper_pid in "${helper_pids[@]}"; do
        apply_uniform_affinity Steam-helper "$helper_pid" "$cef_cpu_mask"
    done
    mkdir -p "$base/runtime"
    stamp_tmp=$(mktemp "$steam_affinity_stamp.tmp.XXXXXX")
    chmod 600 "$stamp_tmp"
    if ! printf '%s\n' "$signature" >"$stamp_tmp"; then
        unlink -- "$stamp_tmp"
        fail 'unable to write Steam session affinity stamp'
    fi
    mv -- "$stamp_tmp" "$steam_affinity_stamp"
}

finish_app_launch_affinity() {
    local x11_pid="$1" steam_pid="$2"
    if [[ $cef_launch_boost == 1 ]]; then
        cef_cpu_mask=0
    fi
    apply_steam_session_affinity "$x11_pid" "$steam_pid"
}

start_tomb_raider_affinity_guard() {
    local stamp guard_log guard_pid
    [[ -x "$affinity_helper" ]] ||
        fail "Tomb Raider affinity helper is unavailable: $affinity_helper"
    mkdir -p "$base/runtime"
    stamp="$(date +%Y%m%d-%H%M%S)"
    guard_log="$base/logs/tomb-raider-affinity-$stamp.log"
    nohup python3 "$affinity_helper" \
        --watch \
        --raknet-cpu1 \
        --wait-for-cpu-log \
        --steam-base "$base" \
        --display "$display" \
        --lock-file "$affinity_lock" \
        >"$guard_log" 2>&1 </dev/null &
    guard_pid=$!
    if ! taskset -pc 0 "$guard_pid" >/dev/null 2>&1; then
        sleep 1
        grep -Fq 'affinity guard: already active' "$guard_log" ||
            fail "unable to confine affinity guard PID $guard_pid to CPU 0"
    fi
    sleep 1
    if ! kill -0 "$guard_pid" 2>/dev/null; then
        grep -Fq 'affinity guard: already active' "$guard_log" ||
            fail "Tomb Raider affinity guard exited; inspect $guard_log"
    fi
    printf 'start-steam: Tomb Raider affinity guard armed; log %s\n' "$guard_log"
}

maybe_start_tomb_raider_affinity_guard() {
    if [[ "$requested_appid" == 203160 ]]; then
        start_tomb_raider_affinity_guard
    fi
}

start_gtaiv_affinity_guard() {
    local stamp guard_log guard_pid
    [[ -x "$gtaiv_affinity_helper" ]] ||
        fail "GTA IV affinity helper is unavailable: $gtaiv_affinity_helper"
    mkdir -p "$base/runtime"
    stamp="$(date +%Y%m%d-%H%M%S)"
    guard_log="$base/logs/gtaiv-affinity-$stamp.log"
    nohup python3 "$gtaiv_affinity_helper" \
        --watch \
        --steam-base "$base" \
        --display "$display" \
        --lock-file "$gtaiv_affinity_lock" \
        >"$guard_log" 2>&1 </dev/null &
    guard_pid=$!
    if ! taskset -pc 0 "$guard_pid" >/dev/null 2>&1; then
        sleep 1
        grep -Fq 'affinity guard: already active' "$guard_log" ||
            fail "unable to confine GTA IV affinity guard PID $guard_pid to CPU 0"
    fi
    sleep 1
    if ! kill -0 "$guard_pid" 2>/dev/null; then
        grep -Fq 'affinity guard: already active' "$guard_log" ||
            fail "GTA IV affinity guard exited; inspect $guard_log"
    fi
    printf 'start-steam: GTA IV affinity guard armed; log %s\n' "$guard_log"
}

maybe_start_game_affinity_guard() {
    if [[ $skip_game_affinity_guard == 1 ]]; then
        printf 'start-steam: Tomb Raider affinity guard suppressed for the validated non-game AppID handoff\n'
        return
    fi
    case "$requested_appid" in
        203160) start_tomb_raider_affinity_guard ;;
        12210) start_gtaiv_affinity_guard ;;
    esac
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

for value_name in process_timeout duplicate_process_timeout window_timeout \
        app_timeout window_stable_seconds minimum_window_width \
        minimum_window_height; do
    value="${!value_name}"
    [[ "$value" =~ ^[1-9][0-9]*$ ]] ||
        fail "$value_name must be a positive integer (got: $value)"
done

for command in am cmd termux-x11 termux-x11-preference timeout xdpyinfo \
        xdotool pactl pgrep pulseaudio python3 stat tail taskset unlink logcat; do
    require_command "$command"
done
[[ -n "${PREFIX:-}" ]] || fail 'PREFIX is not set; run this from Termux'
[[ "$display" =~ ^:[0-9]+$ ]] || fail "invalid X display: $display"
[[ -x "$steam_launcher" ]] || fail "Steam launcher is unavailable: $steam_launcher"
[[ -x "$pulse_helper" ]] || fail "PulseAudio helper is unavailable: $pulse_helper"
[[ -x "$affinity_helper" ]] || fail "affinity helper is unavailable: $affinity_helper"
[[ -x "$gtaiv_affinity_helper" ]] ||
    fail "GTA IV affinity helper is unavailable: $gtaiv_affinity_helper"
[[ -f $process_match_helper && ! -L $process_match_helper ]] ||
    fail "process matcher is unavailable: $process_match_helper"
[[ -x $forward_dispatcher && ! -L $forward_dispatcher ]] ||
    fail "forward dispatcher is unavailable: $forward_dispatcher"
# shellcheck source=/dev/null
source "$process_match_helper"
mkdir -p "$base/logs"
phase_id=${EPOCHREALTIME/./}
[[ $phase_id =~ ^[0-9]+$ ]] || fail 'Bash realtime clock is unavailable'
phase_log=$base/logs/start-steam-phases-$phase_id-$$.log
(set -o noclobber; : >"$phase_log") 2>/dev/null ||
    fail "could not create Steam phase log: $phase_log"
chmod 600 "$phase_log"

steam_phase() {
    local event=$1 detail=${2:-none} clock_value whole fraction
    [[ $event =~ ^[a-z][a-z0-9_]*$ &&
       $detail =~ ^[A-Za-z0-9_.:/=,-]+$ ]] ||
        fail "invalid Steam phase: $event $detail"
    clock_value=${EPOCHREALTIME:-}
    [[ $clock_value =~ ^[0-9]+([.][0-9]+)?$ ]] ||
        fail 'Bash realtime clock is unavailable'
    whole=${clock_value%%.*}
    if [[ $clock_value == *.* ]]; then
        fraction=${clock_value#*.}00
        fraction=${fraction:0:2}
    else
        fraction=00
    fi
    printf 'steam-arm64-wrapper-phase version=1 event=%s clock=realtime timestamp_cs=%s detail=%s\n' \
        "$event" "$((10#$whole * 100 + 10#$fraction))" "$detail" \
        >>"$phase_log"
}

steam_phase wrapper_start "appid=${requested_appid:-none},background=$background_mode"
printf 'start-steam: phase log %s\n' "$phase_log"

termux_uid="$(package_uid com.termux)"
x11_uid="$(package_uid com.termux.x11)"
[[ "$termux_uid" =~ ^[0-9]+$ ]] || fail 'unable to resolve the Termux package UID'
[[ "$x11_uid" =~ ^[0-9]+$ ]] || fail 'unable to resolve the Termux:X11 package UID'
[[ "$termux_uid" == "$x11_uid" ]] ||
    fail "Termux and Termux:X11 do not share a UID ($termux_uid != $x11_uid)"

x11_cold_start=0
x11_foreground_handoff=0
mapfile -t x11_pids < <(matching_pids x11)
case "${#x11_pids[@]}" in
    0)
        x11_cold_start=1
        require_top_app launcher "$$"
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

        # Upstream separates the foreground Android activity from the server.
        # Open it first only on a cold start. The shared-UID build lets us
        # verify persisted preferences directly. Broadcast only if they are
        # missing: a live preference reload is unsafe while Steam is rendering.
        foreground_x11
        x11_foreground_handoff=1
        if ! x11_preferences_are_configured; then
            if ! configure_x11_preferences; then
                fail 'unable to configure Termux:X11 input and idle behavior'
            fi
            for _ in $(seq 1 5); do
                x11_preferences_are_configured && break
                sleep 1
            done
            x11_preferences_are_configured ||
                fail 'Termux:X11 did not persist input and idle preferences'
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
        # A prior native Activity (including BVB) can leave this shared-UID
        # X server backgrounded. Ask Android to foreground its visible Activity
        # before enforcing the performance cgroup invariant.
        if ! process_is_top_app "${x11_pids[0]}"; then
            foreground_x11
            x11_foreground_handoff=1
            wait_for_top_app "${x11_pids[0]}" ||
                require_top_app X11 "${x11_pids[0]}"
        fi
        require_top_app X11 "${x11_pids[0]}"
        wait_for_x11 || fail "existing X server ${x11_pids[0]} is unreachable"
        ;;
    *)
        fail "multiple X servers target $display: ${x11_pids[*]}"
        ;;
esac

require_top_app X11 "${x11_pids[0]}"
apply_uniform_affinity X11 "${x11_pids[0]}" 0-3

# A cold start deliberately performs a second handoff after server readiness
# because opening the Activity before the server can otherwise leave a black
# Android surface. A reused server was already foregrounded above.
if [[ $x11_cold_start == 1 ]]; then
    foreground_x11
fi

if [[ $x11_foreground_handoff == 1 ]]; then
    if x11_bridge_has_dead_binder "${x11_pids[0]}"; then
        fail "X server ${x11_pids[0]} has a stale Android Binder bridge; X clients cannot migrate, so stop them and restart this server"
    else
        bridge_status=$?
        [[ "$bridge_status" -ne 2 ]] ||
            fail 'unable to inspect the Termux:X11 Android bridge log'
    fi
fi

if ! x11_input="$(DISPLAY="$display" timeout 5 \
        xdpyinfo -ext XInputExtension 2>/dev/null)"; then
    fail 'unable to query X11 input devices'
fi
for input_device in '"Lorie mouse"' '"Lorie touch"' '"Lorie keyboard"'; do
    grep -Fq "$input_device" <<<"$x11_input" ||
        fail "Termux:X11 input device is unavailable: $input_device"
done
steam_phase x11_ready "cold=$x11_cold_start,foreground=$x11_foreground_handoff"

"$pulse_helper" "$base"
export PULSE_SERVER="$pulse_server"
pactl --server="$pulse_server" info >/dev/null 2>&1 ||
    fail 'PulseAudio TCP endpoint is unavailable after preparation'
if ! pulse_sinks="$(pactl --server="$pulse_server" list short sinks 2>/dev/null)" ||
        [[ -z "$pulse_sinks" ]]; then
    fail 'PulseAudio is reachable but exposes no audio sink'
fi
steam_phase audio_ready

mapfile -t steam_pids < <(matching_pids steam)
gameprocess_log_offset="$(stat -c %s -- "$gameprocess_log" 2>/dev/null || printf '0\n')"
[[ "$gameprocess_log_offset" =~ ^[0-9]+$ ]] || gameprocess_log_offset=0
if [[ "${#steam_pids[@]}" -gt 1 ]]; then
    settle_steam_processes ||
        fail "multiple Steam main processes remained for ${duplicate_process_timeout}s: ${steam_pids[*]}"
fi
steam_phase steam_discovery "count=${#steam_pids[@]}"
if [[ "${#steam_pids[@]}" -eq 1 ]]; then
    fast_forward_authenticated=0
    steam_hidapi_mode_matches "${steam_pids[0]}" ||
        fail "existing Steam input mode does not match STEAM_ARM64_HIDAPI=$hidapi_mode; restart Steam for this cold-start-only control"
    require_top_app Steam "${steam_pids[0]}"
    apply_steam_session_affinity "${x11_pids[0]}" "${steam_pids[0]}"
    steam_phase affinity_ready "cef=$cef_cpu_mask"
    maybe_start_game_affinity_guard
    if [[ "${#steam_arguments[@]}" -gt 0 ]]; then
        steam_start_ticks="$(steam_arm64_process_start_ticks "${steam_pids[0]}" || true)"
        [[ $steam_start_ticks =~ ^[1-9][0-9]*$ ]] || steam_start_ticks=0
        forward_log="$base/logs/start-steam-forward-$(date +%Y%m%d-%H%M%S).log"
        steam_phase forward_start "mode=$forward_bootstrap"
        if [[ $forward_bootstrap == fast ]]; then
            set +e
            env DISPLAY="$display" \
                STEAM_ARM64_FORWARD_BOOTSTRAP="$forward_bootstrap" \
                "$forward_dispatcher" \
                    --steam-pid "${steam_pids[0]}" \
                    --steam-start-ticks "$steam_start_ticks" \
                    --strict-launcher "$steam_launcher" -- \
                    "${steam_arguments[@]}" \
                >"$forward_log" 2>&1 </dev/null
            forward_status=$?
            set -e
            (( forward_status == 0 )) ||
                fail "Steam fast forwarding failed with status $forward_status; inspect $forward_log"
            if grep -Eq '^steam-arm64-forward-phase version=2 mode=fast event=session_valid ' \
                    "$forward_log" &&
                    grep -Eq '^steam-arm64-forward-phase version=2 mode=fast event=fast_launch ' \
                    "$forward_log" &&
                    grep -Eq '^steam-arm64-forward-phase version=2 mode=fast event=complete .* detail=status=0$' \
                    "$forward_log" &&
                    ! grep -Eq '^steam-arm64-forward-phase version=2 mode=fast event=fast_fallback ' \
                    "$forward_log"; then
                fast_forward_authenticated=1
            fi
        else
            nohup env DISPLAY="$display" \
                STEAM_ARM64_FORWARD_BOOTSTRAP="$forward_bootstrap" \
                "$forward_dispatcher" \
                    --steam-pid "${steam_pids[0]}" \
                    --steam-start-ticks "$steam_start_ticks" \
                    --strict-launcher "$steam_launcher" -- \
                    "${steam_arguments[@]}" \
                >"$forward_log" 2>&1 </dev/null &
        fi
        printf 'start-steam: forwarded request to Steam PID %s; log %s\n' \
            "${steam_pids[0]}" "$forward_log"
        steam_phase forward_complete "authenticated=$fast_forward_authenticated"
    fi
    if [[ $fast_forward_authenticated == 0 ]] &&
            ! wait_for_remembered_login "${steam_pids[0]}"; then
        steam_pid_is_current "${steam_pids[0]}" ||
            fail "Steam PID ${steam_pids[0]} exited before remembered login completed"
        fail "remembered Steam login did not complete in ${window_timeout}s"
    fi
    if [[ -z "$requested_appid" && "$background_mode" == 1 ]]; then
        steam_phase complete "route=warm-background"
        printf 'start-steam: existing Steam PID %s ready in background; X11 PID %s CPUs 0-3, Steam CPUs 0-3, CEF CPUs %s, PulseAudio sink, no Steam window focus, no KDE\n' \
            "${steam_pids[0]}" "${x11_pids[0]}" "$cef_cpu_mask"
        exit 0
    fi
    if [[ -n "$requested_appid" && "$background_mode" == 1 ]]; then
        if ! wait_for_app_launch "${steam_pids[0]}" "$requested_appid" \
                "$gameprocess_log_offset"; then
            steam_pid_is_current "${steam_pids[0]}" ||
                fail "Steam exited before AppID $requested_appid launched"
            fail "Steam did not acknowledge AppID $requested_appid in ${app_timeout}s"
        fi
        finish_app_launch_affinity "${x11_pids[0]}" "${steam_pids[0]}"
        steam_phase appid_ready "appid=$requested_appid,cef=$cef_cpu_mask"
        steam_phase complete "route=warm-appid"
        printf 'start-steam: AppID %s accepted in background; X11 PID %s CPUs 0-3, Steam PID %s CPUs 0-3, CEF CPUs %s, PulseAudio sink, no Steam window focus, no KDE\n' \
            "$requested_appid" "${x11_pids[0]}" "${steam_pids[0]}" \
            "$cef_cpu_mask"
        exit 0
    fi
    if ! steam_window="$(wait_for_steam_window "${steam_pids[0]}" 1)"; then
        steam_pid_is_current "${steam_pids[0]}" ||
            fail "Steam PID ${steam_pids[0]} exited before a usable window appeared"
        fail "Steam PID ${steam_pids[0]} exists but no usable window became visible in ${window_timeout}s"
    fi
    surface_steam_window "$steam_window" ||
        fail "Steam window $steam_window could not be mapped, raised, and focused"
    apply_steam_session_affinity "${x11_pids[0]}" "${steam_pids[0]}"
    steam_phase window_ready "window=$steam_window,cef=$cef_cpu_mask"
    steam_phase complete "route=warm-visible"
    printf 'start-steam: ready; X11 PID %s CPUs 0-3, Steam PID %s CPUs 0-3, CEF CPUs %s, window %s visible, PulseAudio sink, Lorie mouse/touch/keyboard, no KDE\n' \
        "${x11_pids[0]}" "${steam_pids[0]}" "$cef_cpu_mask" \
        "$steam_window"
    exit 0
fi

login_log_offset="$(stat -c %s -- "$login_log" 2>/dev/null || printf '0\n')"
[[ "$login_log_offset" =~ ^[0-9]+$ ]] || login_log_offset=0

mapfile -t launcher_pids < <(matching_pids launcher)
if [[ "${#launcher_pids[@]}" -gt 1 ]]; then
    fail "multiple Steam launcher processes found: ${launcher_pids[*]}"
fi

if [[ "${#launcher_pids[@]}" -eq 1 ]]; then
    launcher_pid="${launcher_pids[0]}"
    require_top_app Steam-launcher "$launcher_pid"
    maybe_start_game_affinity_guard
    steam_log="$base/logs"
    printf 'start-steam: attaching to Steam initialization under launcher PID %s\n' \
        "$launcher_pid"
else
    require_top_app launcher "$$"
    maybe_start_game_affinity_guard
    steam_log="$base/logs/start-steam-$(date +%Y%m%d-%H%M%S).log"
    steam_phase steam_launch_start "profile=$profile"
    nohup env -u STEAM_ARM64_FORWARD_BOOTSTRAP \
        DISPLAY="$display" PULSE_SERVER="$pulse_server" \
        STEAM_ARM64_FEX_PROFILE="$profile" "$steam_launcher" -noshaders \
        "${steam_arguments[@]}" \
        >"$steam_log" 2>&1 </dev/null &
    launcher_pid=$!
fi

for _ in $(seq 1 "$process_timeout"); do
    mapfile -t steam_pids < <(matching_pids steam)
    if [[ "${#steam_pids[@]}" -eq 1 ]]; then
        break
    fi
    if [[ "${#steam_pids[@]}" -gt 1 ]]; then
        settle_steam_processes ||
            fail "multiple Steam main processes remained for ${duplicate_process_timeout}s: ${steam_pids[*]}"
        if [[ "${#steam_pids[@]}" -eq 1 ]]; then
            break
        fi
    fi
    if ! kill -0 "$launcher_pid" 2>/dev/null; then
        fail "Steam launcher exited before Steam appeared; inspect $steam_log"
    fi
    sleep 1
done

[[ "${#steam_pids[@]}" -eq 1 ]] ||
    fail "Steam did not appear in ${process_timeout}s; inspect $steam_log"
steam_hidapi_mode_matches "${steam_pids[0]}" ||
    fail "launched Steam input mode does not match STEAM_ARM64_HIDAPI=$hidapi_mode; inspect $steam_log"
require_top_app Steam "${steam_pids[0]}"
steam_phase steam_process_ready "pid=${steam_pids[0]}"
if ! wait_for_remembered_login "${steam_pids[0]}" "$login_log_offset"; then
    steam_pid_is_current "${steam_pids[0]}" ||
        fail "Steam PID ${steam_pids[0]} exited before remembered login completed; inspect $steam_log"
    fail "remembered Steam login did not complete in ${window_timeout}s; inspect $steam_log"
fi
steam_phase login_ready
if [[ -z "$requested_appid" && "$background_mode" == 1 ]]; then
    apply_steam_session_affinity "${x11_pids[0]}" "${steam_pids[0]}"
    steam_phase complete "route=cold-background"
    printf 'start-steam: Steam ready in background; X11 PID %s CPUs 0-3, Steam PID %s CPUs 0-3, CEF CPU 0, PulseAudio sink, FEX %s, no Steam window focus, no KDE\n' \
        "${x11_pids[0]}" "${steam_pids[0]}" "$profile"
    exit 0
fi
if [[ -n "$requested_appid" && "$background_mode" == 1 ]]; then
    if ! wait_for_app_launch "${steam_pids[0]}" "$requested_appid" \
            "$gameprocess_log_offset"; then
        steam_pid_is_current "${steam_pids[0]}" ||
            fail "Steam exited before AppID $requested_appid launched; inspect $steam_log"
        fail "Steam did not acknowledge AppID $requested_appid in ${app_timeout}s; inspect $steam_log"
    fi
    finish_app_launch_affinity "${x11_pids[0]}" "${steam_pids[0]}"
    steam_phase appid_ready "appid=$requested_appid,cef=$cef_cpu_mask"
    steam_phase complete "route=cold-appid"
    printf 'start-steam: AppID %s accepted in background; X11 PID %s CPUs 0-3, Steam PID %s CPUs 0-3, CEF CPUs %s, PulseAudio sink, FEX %s, no Steam window focus, no KDE\n' \
        "$requested_appid" "${x11_pids[0]}" "${steam_pids[0]}" \
        "$cef_cpu_mask" "$profile"
    exit 0
fi
if ! steam_window="$(wait_for_steam_window "${steam_pids[0]}")"; then
    steam_pid_is_current "${steam_pids[0]}" ||
        fail "Steam PID ${steam_pids[0]} exited before a usable window appeared; inspect $steam_log"
    fail "Steam PID ${steam_pids[0]} exists but no usable window became visible in ${window_timeout}s; inspect $steam_log"
fi
surface_steam_window "$steam_window" ||
    fail "Steam window $steam_window could not be mapped, raised, and focused"
apply_steam_session_affinity "${x11_pids[0]}" "${steam_pids[0]}"
steam_phase window_ready "window=$steam_window,cef=$cef_cpu_mask"
steam_phase complete "route=cold-visible"
printf 'start-steam: ready; X11 PID %s CPUs 0-3, Steam PID %s CPUs 0-3, CEF CPU 0, window %s visible, PulseAudio sink, Lorie mouse/touch/keyboard, FEX %s, no KDE\n' \
    "${x11_pids[0]}" "${steam_pids[0]}" "$steam_window" "$profile"
