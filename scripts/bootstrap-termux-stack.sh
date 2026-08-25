#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
setup=$repo_root/scripts/setup-steam-stack.py
profile=$repo_root/config/termux-setup-profile.json
lock=$repo_root/config/steam-arm64-bootstrap-lock.json
base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}

fail() {
    printf 'bootstrap-termux-stack: %s\n' "$*" >&2
    exit 1
}

[[ ${PREFIX:-} == /data/data/com.termux/files/usr ]] ||
    fail 'run this command inside the official com.termux environment'
[[ -x $PREFIX/bin/pkg && ! -L $PREFIX/bin/pkg ]] ||
    fail "unsafe or missing Termux package manager: $PREFIX/bin/pkg"
[[ -f $setup && ! -L $setup && -f $profile && ! -L $profile &&
        -f $lock && ! -L $lock ]] ||
    fail 'release archive is incomplete or contains unsafe links'
[[ $(getprop ro.product.cpu.abi) == arm64-v8a ]] ||
    fail 'this profile requires an ARM64 Android device'

if ! command -v python3 >/dev/null 2>&1; then
    "$PREFIX/bin/pkg" install -y python
fi

python3 "$setup" --package-profile "$profile" \
    dependencies --install --yes --base "$base"
exec python3 "$setup" --lock "$lock" prepare --base "$base"
