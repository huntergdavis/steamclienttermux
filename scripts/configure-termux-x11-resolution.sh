#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

usage() {
    printf 'Usage: %s --set-720p|--native|--check\n' "$0" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
action="$1"
command -v termux-x11-preference >/dev/null || {
    printf 'termux-x11-preference is required\n' >&2
    exit 2
}
command -v xrandr >/dev/null || {
    printf 'xrandr is required\n' >&2
    exit 2
}

display="${DISPLAY:-:0}"

preferences() {
    timeout 10 termux-x11-preference list
}

preference_value() {
    local key="$1" listing="$2"
    sed -n "s/^\"${key}\"=\"\([^\"]*\)\"$/\1/p" <<<"$listing"
}

geometry() {
    DISPLAY="$display" xrandr --current |
        sed -n 's/^Screen 0:.* current \([0-9][0-9]*\) x \([0-9][0-9]*\),.*/\1x\2/p'
}

wait_for_geometry() {
    local expected="$1" observed=""
    for _ in 1 2 3 4 5; do
        observed="$(geometry)"
        if [[ "$observed" == "$expected" ]]; then
            printf '%s' "$observed"
            return 0
        fi
        sleep 1
    done
    printf '%s' "$observed"
    return 1
}

before="$(preferences)"
previous_mode="$(preference_value displayResolutionMode "$before")"
previous_exact="$(preference_value displayResolutionExact "$before")"
if [[ ! "$previous_mode" =~ ^(native|scaled|exact|custom)$ ]] ||
        [[ ! "$previous_exact" =~ ^[0-9]+x[0-9]+$ ]]; then
    printf 'Unable to validate current Termux:X11 resolution preferences\n' >&2
    exit 2
fi

case "$action" in
    --check)
        current="$(geometry)"
        printf 'mode=%s exact=%s xrandr=%s\n' \
            "$previous_mode" "$previous_exact" "$current"
        [[ "$previous_mode" == exact && "$previous_exact" == 1280x720 &&
            "$current" == 1280x720 ]]
        ;;
    --set-720p)
        if ! timeout 10 termux-x11-preference \
                displayResolutionMode:exact displayResolutionExact:1280x720; then
            printf 'Termux:X11 rejected the 720p preferences\n' >&2
            exit 2
        fi
        if current="$(wait_for_geometry 1280x720)"; then
            printf 'Termux:X11: %s/%s -> exact/1280x720; xrandr=%s\n' \
                "$previous_mode" "$previous_exact" "$current"
            exit 0
        fi
        printf 'X11 remained at %s; restoring %s/%s\n' \
            "$current" "$previous_mode" "$previous_exact" >&2
        timeout 10 termux-x11-preference \
            "displayResolutionMode:${previous_mode}" \
            "displayResolutionExact:${previous_exact}" >/dev/null
        exit 2
        ;;
    --native)
        timeout 10 termux-x11-preference displayResolutionMode:native >/dev/null
        printf 'Termux:X11: %s/%s -> native; xrandr=%s\n' \
            "$previous_mode" "$previous_exact" "$(geometry)"
        ;;
    *)
        usage
        ;;
esac
