#!/usr/bin/env bash
set -euo pipefail

custom_proot_dir="${PROOT_BUILD_DIR:-$HOME/steam-arm64/src/proot-production/src}"
bwrap="${BWRAP_BIN:-$HOME/steam-arm64/runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap}"
spaced_source="${1:-$HOME/steam-arm64/client/steamapps/common/Proton 11.0 (ARM64)}"

if [[ ! -x "$custom_proot_dir/proot" ]]; then
    printf 'Patched PRoot not found: %s/proot\n' "$custom_proot_dir" >&2
    exit 1
fi
if [[ ! -x "$bwrap" ]]; then
    printf 'ARM64 srt-bwrap not found: %s\n' "$bwrap" >&2
    exit 1
fi
if [[ ! -d "$spaced_source" ]]; then
    printf 'Spaced bind source not found: %s\n' "$spaced_source" >&2
    exit 1
fi

run_case() {
    local label="$1"
    local source="$2"

    printf '== %s ==\n' "$label"
    PATH="$custom_proot_dir:$PATH" timeout 25s \
        proot-distro login debian --shared-tmp -- /bin/bash -lc '
            exec "$1" --ro-bind / / --ro-bind "$2" "$2" -- /bin/true
        ' probe "$bwrap" "$source"
}

run_case no-space /bin
run_case spaced "$spaced_source"
printf 'bwrap-spaced-bind: PASS\n'
