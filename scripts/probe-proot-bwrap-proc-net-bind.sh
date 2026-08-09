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

fixture_dir="$(mktemp -d "$termux_tmp/proot-bwrap-proc-net.XXXXXX")"
guest_dir="/tmp/${fixture_dir##*/}"
marker="steam-arm64-proc-net-$$"
printf '%s\n' "$marker" >"$fixture_dir/route"
: >"$fixture_dir/ipv6_route"
chmod 700 "$fixture_dir"
chmod 600 "$fixture_dir/route" "$fixture_dir/ipv6_route"

cleanup() {
    if [[ "$fixture_dir" != "$termux_tmp"/proot-bwrap-proc-net.* ]] ||
            [[ -L "$fixture_dir" ]] || [[ ! -d "$fixture_dir" ]]; then
        printf 'Refusing to clean unexpected fixture: %s\n' "$fixture_dir" >&2
        return 1
    fi
    for fixture_file in "$fixture_dir/route" "$fixture_dir/ipv6_route"; do
        if [[ -L "$fixture_file" ]] || [[ ! -f "$fixture_file" ]]; then
            printf 'Refusing to remove unexpected fixture: %s\n' \
                "$fixture_file" >&2
            return 1
        fi
        rm -- "$fixture_file"
    done
    rmdir -- "$fixture_dir"
}
trap cleanup EXIT

payload='marker="$1"
source_fd="$2"
test ! -L /proc/net
test -d /proc/net
# srt-bwrap consumes the inherited source fd; the mount must remain usable by
# the payload after that descriptor is closed rather than relying on a path.
test ! -e "/proc/self/fd/$source_fd"
test "$(cat /proc/net/route)" = "$marker"
test -f /proc/net/ipv6_route
test ! -s /proc/net/ipv6_route
child_route="$(/bin/bash -eu -c "cat /proc/net/route")"
test "$child_route" = "$marker"
printf "proc-net-directory-bind: PASS (%s)\n" "$marker"'

PATH="$custom_proot_dir:$PATH" timeout 25s \
    proot-distro login debian --shared-tmp -- /bin/bash -lc '
        exec {proc_net_fd}<"$2"
        exec "$1" --ro-bind / / --proc /proc \
            --ro-bind-fd "$proc_net_fd" /proc/net -- \
            /bin/bash -eu -c "$3" probe "$4" "$proc_net_fd"
    ' probe "$bwrap" "$guest_dir" "$payload" "$marker"
