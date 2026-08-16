#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
client_preflight=$HOME/bin/steam-arm-native
boundary_preflight=$base/compat-bin/steam-arm64-native-bwrap
proot_dir=${STEAM_ARM64_PROOT_DIR:-$base/src/proot-production/src}

usage() {
    cat <<'EOF'
Usage: check-native-steam-stack.sh [--proot-dir ABSOLUTE_DIRECTORY]

Verify the native Steam/CEF dependencies and the generic Pressure Vessel
boundary without launching Steam, X11, a game, or an authentication flow.
EOF
}

while (( $# > 0 )); do
    case $1 in
        --proot-dir)
            (( $# >= 2 )) || {
                printf '%s\n' 'check-native-steam-stack: --proot-dir needs a value' >&2
                exit 2
            }
            proot_dir=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'check-native-steam-stack: unknown argument: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

[[ $proot_dir == /* ]] || {
    printf 'check-native-steam-stack: PRoot directory must be absolute: %s\n' \
        "$proot_dir" >&2
    exit 2
}
[[ -x $client_preflight && ! -L $client_preflight ]] || {
    printf 'check-native-steam-stack: client preflight is unavailable: %s\n' \
        "$client_preflight" >&2
    exit 1
}
[[ -x $boundary_preflight && ! -L $boundary_preflight ]] || {
    printf 'check-native-steam-stack: boundary preflight is unavailable: %s\n' \
        "$boundary_preflight" >&2
    exit 1
}

STEAM_ARM64_PROOT_DIR=$proot_dir STEAM_ARM64_NATIVE_CHECK=1 \
    "$client_preflight"
STEAM_ARM64_PROOT_DIR=$proot_dir STEAM_ARM64_NATIVE_BWRAP_CHECK=1 \
    "$boundary_preflight"

printf 'native Steam stack preflight: PASS\n'
