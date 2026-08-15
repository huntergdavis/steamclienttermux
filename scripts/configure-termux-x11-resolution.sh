#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

usage() {
    printf 'Usage: %s --set-720p|--set-1080p|--set-panel-native|--native|--check\n' "$0" >&2
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

set_fixed_geometry() {
    local mode="$1" key="$2" expected="$3" description="$4" current=""
    if ! timeout 10 termux-x11-preference \
            "${key}:${expected}" "displayResolutionMode:${mode}"; then
        printf 'Termux:X11 rejected the %s preferences\n' "$description" >&2
        exit 2
    fi
    if current="$(wait_for_geometry "$expected")"; then
        printf 'Termux:X11: %s/%s -> %s/%s; xrandr=%s\n' \
            "$previous_mode" "$previous_value" "$mode" "$expected" "$current"
        exit 0
    fi
    printf 'X11 remained at %s; restoring %s/%s\n' \
        "$current" "$previous_mode" "$previous_value" >&2
    timeout 10 termux-x11-preference \
        "displayResolutionExact:${previous_exact}" \
        "displayResolutionCustom:${previous_custom}" \
        "displayResolutionMode:${previous_mode}" >/dev/null
    exit 2
}

before="$(preferences)"
previous_mode="$(preference_value displayResolutionMode "$before")"
previous_exact="$(preference_value displayResolutionExact "$before")"
previous_custom="$(preference_value displayResolutionCustom "$before")"
if [[ ! "$previous_mode" =~ ^(native|scaled|exact|custom)$ ]] ||
        [[ ! "$previous_exact" =~ ^[0-9]+x[0-9]+$ ]] ||
        [[ ! "$previous_custom" =~ ^[0-9]+x[0-9]+$ ]]; then
    printf 'Unable to validate current Termux:X11 resolution preferences\n' >&2
    exit 2
fi
case "$previous_mode" in
    exact) previous_value="$previous_exact" ;;
    custom) previous_value="$previous_custom" ;;
    *) previous_value="automatic" ;;
esac

case "$action" in
    --check)
        current="$(geometry)"
        printf 'mode=%s expected=%s exact=%s custom=%s xrandr=%s\n' \
            "$previous_mode" "$previous_value" "$previous_exact" \
            "$previous_custom" "$current"
        if [[ "$previous_mode" == exact || "$previous_mode" == custom ]]; then
            [[ "$current" == "$previous_value" ]]
        else
            [[ "$current" =~ ^[0-9]+x[0-9]+$ ]]
        fi
        ;;
    --set-720p)
        set_fixed_geometry exact displayResolutionExact 1280x720 720p
        ;;
    --set-1080p)
        set_fixed_geometry exact displayResolutionExact 1920x1080 1080p
        ;;
    --set-panel-native)
        # Galaxy Tab S8+ physical panel. The preset-only "exact" selector
        # rejects this size, so Termux:X11's arbitrary custom mode is required.
        set_fixed_geometry custom displayResolutionCustom 2800x1752 \
            'Galaxy Tab S8+ panel-native'
        ;;
    --native)
        timeout 10 termux-x11-preference displayResolutionMode:native >/dev/null
        printf 'Termux:X11: %s/%s -> native; xrandr=%s\n' \
            "$previous_mode" "$previous_value" "$(geometry)"
        ;;
    *)
        usage
        ;;
esac
