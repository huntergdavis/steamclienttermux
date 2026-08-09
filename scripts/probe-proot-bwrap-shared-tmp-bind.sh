#!/usr/bin/env bash
set -euo pipefail

custom_proot_dir="${PROOT_BUILD_DIR:-$HOME/steam-arm64/src/proot-production/src}"
bwrap="${BWRAP_BIN:-$HOME/steam-arm64/runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap}"
termux_tmp="${PREFIX:?Termux PREFIX is required}/tmp"

if [[ ! -x "$custom_proot_dir/proot" ]]; then
    printf 'Patched PRoot not found: %s/proot\n' "$custom_proot_dir" >&2
    exit 1
fi
if [[ ! -x "$bwrap" ]]; then
    printf 'ARM64 srt-bwrap not found: %s\n' "$bwrap" >&2
    exit 1
fi
if [[ ! -d "$termux_tmp" ]]; then
    printf 'Termux tmp directory not found: %s\n' "$termux_tmp" >&2
    exit 1
fi

fixture_dir="$(mktemp -d "$termux_tmp/proot-bwrap-shared-tmp.XXXXXX")"
fixture_file="$fixture_dir/payload"
guest_dir="/tmp/${fixture_dir##*/}"
guest_file="$guest_dir/payload"
printf 'shared-tmp-underlay\n' >"$fixture_file"

cleanup() {
    if [[ "$fixture_dir" != "$termux_tmp"/proot-bwrap-shared-tmp.* ]] ||
            [[ -L "$fixture_dir" ]] || [[ ! -d "$fixture_dir" ]]; then
        printf 'Refusing to clean unexpected fixture: %s\n' "$fixture_dir" >&2
        return 1
    fi
    if [[ -e "$fixture_file" ]]; then
        if [[ -L "$fixture_file" ]] || [[ ! -f "$fixture_file" ]]; then
            printf 'Refusing to remove unexpected payload: %s\n' \
                "$fixture_file" >&2
            return 1
        fi
        rm -- "$fixture_file"
    fi
    rmdir -- "$fixture_dir"
}
trap cleanup EXIT

run_case() {
    local label="$1"
    local source="$2"
    shift 2

    printf '== %s ==\n' "$label"
    PATH="$custom_proot_dir:$PATH" timeout 25s \
        proot-distro login debian --shared-tmp -- /bin/bash -lc '
            bwrap="$1"
            source="$2"
            shift 2
            test -e "$source"
            exec "$bwrap" --ro-bind / / --ro-bind "$source" "$source" -- "$@"
        ' probe "$bwrap" "$source" "$@"
}

run_case shared-tmp-file "$guest_file" /usr/bin/test -f "$guest_file"
run_case shared-tmp-directory "$guest_dir" /usr/bin/test -f "$guest_file"
printf 'bwrap-shared-tmp-bind: PASS\n'
