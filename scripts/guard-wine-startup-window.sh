#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

display=${DISPLAY:-:0}
window_class=
hold_seconds=2
search_timeout=300
xdotool_command=${WINE_STARTUP_GUARD_XDOTOOL:-xdotool}
window=
unmapped=0

fail() {
    printf 'guard-wine-startup-window: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if (( unmapped )) && [[ $window =~ ^[0-9]+$ ]]; then
        DISPLAY="$display" "$xdotool_command" \
            windowmap "$window" windowraise "$window" windowfocus "$window" \
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

set +e
search_result=$(DISPLAY="$display" timeout "$search_timeout" \
    "$xdotool_command" search --sync --onlyvisible \
    --class "^${window_class}$" 2>&1)
search_status=$?
set -e
(( search_status == 0 )) ||
    fail "window search failed ($search_status): $search_result"
window=${search_result%%$'\n'*}
[[ $window =~ ^[0-9]+$ ]] || fail "invalid window id: $window"
[[ $(DISPLAY="$display" "$xdotool_command" getwindowclassname "$window") == \
    "$window_class" ]] || fail "window class changed before guard: $window"

DISPLAY="$display" "$xdotool_command" windowunmap "$window"
unmapped=1
printf 'wine-startup-window-guard version=1 event=hidden window=%s class=%s epoch=%s\n' \
    "$window" "$window_class" "${EPOCHREALTIME:-unknown}"
sleep "$hold_seconds"
DISPLAY="$display" "$xdotool_command" \
    windowmap "$window" windowraise "$window" windowfocus "$window"
unmapped=0
printf 'wine-startup-window-guard version=1 event=revealed window=%s class=%s epoch=%s\n' \
    "$window" "$window_class" "${EPOCHREALTIME:-unknown}"
