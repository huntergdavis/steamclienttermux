#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

display=${DISPLAY:-:0}
window_class=
hold_seconds=2
search_timeout=300
xdotool_command=${WINE_STARTUP_GUARD_XDOTOOL:-xdotool}
window=
moved=0
original_x=
original_y=

fail() {
    printf 'guard-wine-startup-window: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if (( moved )) && [[ $window =~ ^[0-9]+$ && $original_x =~ ^-?[0-9]+$ &&
            $original_y =~ ^-?[0-9]+$ ]]; then
        DISPLAY="$display" "$xdotool_command" \
            windowmove "$window" "$original_x" "$original_y" \
            windowraise "$window" windowfocus "$window" \
            >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT HUP INT TERM

while (( $# )); do
    case $1 in
        --display)
            (( $# >= 2 )) || fail '--display requires a value'
            display=$2
            shift 2
            ;;
        --class)
            (( $# >= 2 )) || fail '--class requires a value'
            window_class=$2
            shift 2
            ;;
        --hold-seconds)
            (( $# >= 2 )) || fail '--hold-seconds requires a value'
            hold_seconds=$2
            shift 2
            ;;
        --timeout)
            (( $# >= 2 )) || fail '--timeout requires a value'
            search_timeout=$2
            shift 2
            ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[[ $display =~ ^:[0-9]+([.][0-9]+)?$ ]] || fail "invalid display: $display"
[[ $window_class =~ ^[A-Za-z0-9_.-]+$ ]] ||
    fail "invalid window class: $window_class"
[[ $hold_seconds =~ ^([0-9]+)([.][0-9]+)?$ ]] ||
    fail "invalid hold duration: $hold_seconds"
[[ $search_timeout =~ ^[1-9][0-9]*$ && $search_timeout -le 600 ]] ||
    fail "invalid search timeout: $search_timeout"
command -v "$xdotool_command" >/dev/null 2>&1 ||
    fail "xdotool is unavailable: $xdotool_command"

if DISPLAY="$display" "$xdotool_command" search --onlyvisible \
        --class "^${window_class}$" >/dev/null 2>&1; then
    fail "a matching visible window already exists: $window_class"
fi

read -r display_width display_height < <(
    DISPLAY="$display" "$xdotool_command" getdisplaygeometry
) || fail "could not read display geometry: $display"
[[ $display_width =~ ^[1-9][0-9]*$ && $display_height =~ ^[1-9][0-9]*$ ]] ||
    fail "invalid display geometry: $display_width $display_height"
offscreen_x=$((display_width + 64))

# Wine maps this window before publishing WM_CLASS. Waiting for the final class
# leaves its blank white surface visible for several seconds. Snapshot the
# existing window IDs before launch, then conceal the first new game-sized
# window immediately and confirm its class while it continues painting.
declare -A baseline_windows=()
mapfile -t visible_windows < <(
    DISPLAY="$display" "$xdotool_command" search --onlyvisible --name '.*' \
        2>/dev/null || true
)
for visible_window in "${visible_windows[@]}"; do
    [[ $visible_window =~ ^[0-9]+$ ]] && baseline_windows[$visible_window]=1
done

deadline=$((SECONDS + search_timeout))
confirmed=0
while (( SECONDS < deadline && confirmed == 0 )); do
    mapfile -t visible_windows < <(
        DISPLAY="$display" "$xdotool_command" search --onlyvisible --name '.*' \
            2>/dev/null || true
    )
    for visible_window in "${visible_windows[@]}"; do
        [[ $visible_window =~ ^[0-9]+$ ]] || continue
        [[ -z ${baseline_windows[$visible_window]+set} ]] || continue
        geometry=$(DISPLAY="$display" "$xdotool_command" \
            getwindowgeometry --shell "$visible_window" 2>/dev/null || true)
        original_x=$(sed -n 's/^X=//p' <<<"$geometry")
        original_y=$(sed -n 's/^Y=//p' <<<"$geometry")
        window_width=$(sed -n 's/^WIDTH=//p' <<<"$geometry")
        window_height=$(sed -n 's/^HEIGHT=//p' <<<"$geometry")
        if ! [[ $original_x =~ ^-?[0-9]+$ && $original_y =~ ^-?[0-9]+$ &&
                $window_width =~ ^[1-9][0-9]*$ &&
                $window_height =~ ^[1-9][0-9]*$ ]] ||
                (( window_width < 320 || window_height < 180 )); then
            baseline_windows[$visible_window]=1
            continue
        fi
        window=$visible_window
        DISPLAY="$display" "$xdotool_command" \
            windowmove "$window" "$offscreen_x" "$original_y"
        moved=1
        printf 'wine-startup-window-guard version=3 event=candidate_concealed window=%s x=%s y=%s epoch=%s\n' \
            "$window" "$offscreen_x" "$original_y" \
            "${EPOCHREALTIME:-unknown}"
        while (( SECONDS < deadline )); do
            candidate_class=$(DISPLAY="$display" "$xdotool_command" \
                getwindowclassname "$window" 2>/dev/null || true)
            if [[ $candidate_class == "$window_class" ]]; then
                confirmed=1
                break
            fi
            if [[ -n $candidate_class ]]; then
                DISPLAY="$display" "$xdotool_command" \
                    windowmove "$window" "$original_x" "$original_y"
                moved=0
                baseline_windows[$window]=1
                window=
                break
            fi
            DISPLAY="$display" "$xdotool_command" \
                windowmove "$window" "$offscreen_x" "$original_y" \
                >/dev/null 2>&1 || break
            sleep 0.05
        done
        (( confirmed == 0 )) || break
    done
    (( confirmed == 0 )) && sleep 0.02
done
(( confirmed == 1 )) || fail "game startup window did not appear in ${search_timeout}s"
printf 'wine-startup-window-guard version=3 event=class_confirmed window=%s class=%s epoch=%s\n' \
    "$window" "$window_class" "${EPOCHREALTIME:-unknown}"

# Keep enforcing the offscreen position during the short post-class paint hold;
# the application is allowed to resize/reposition itself during initialization.
sleep "$hold_seconds" &
hold_pid=$!
while kill -0 "$hold_pid" 2>/dev/null; do
    DISPLAY="$display" "$xdotool_command" \
        windowmove "$window" "$offscreen_x" "$original_y" \
        >/dev/null 2>&1 || break
    sleep 0.05
done
wait "$hold_pid"
DISPLAY="$display" "$xdotool_command" \
    windowmove "$window" "$original_x" "$original_y" \
    windowraise "$window" windowfocus "$window"
moved=0
printf 'wine-startup-window-guard version=3 event=revealed window=%s class=%s x=%s y=%s epoch=%s\n' \
    "$window" "$window_class" "$original_x" "$original_y" \
    "${EPOCHREALTIME:-unknown}"
