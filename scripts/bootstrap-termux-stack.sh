#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
setup=$repo_root/scripts/setup-steam-stack.py
profile=$repo_root/config/termux-setup-profile.json
lock=$repo_root/config/steam-arm64-bootstrap-lock.json
turnip_lock=$repo_root/config/turnip-runtime-lock.json
turnip_installer=$repo_root/scripts/install-turnip-runtime.py
tgcompat_lock=$repo_root/config/tgcompat-runtime-lock.json
tgcompat_installer=$repo_root/scripts/install-tgcompat-runtime.py
glibc_lock=$repo_root/config/glibc-runtime-lock.json
glibc_installer=$repo_root/scripts/install-glibc-runtime.py
glibc_package=$repo_root/artifacts/glibc_2.44_aarch64.deb
proot_lock=$repo_root/config/proot-runtime-lock.json
proot_installer=$repo_root/scripts/install-proot-runtime.py
proot_builder=$repo_root/scripts/build-proot.sh
debian_lock=$repo_root/config/debian-runtime-lock.json
debian_installer=$repo_root/scripts/install-debian-runtime.py
launcher_installer=$repo_root/scripts/install-project-files.sh
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
        -f $lock && ! -L $lock && -f $turnip_lock && ! -L $turnip_lock &&
        -f $turnip_installer && ! -L $turnip_installer &&
        -f $tgcompat_lock && ! -L $tgcompat_lock &&
        -f $tgcompat_installer && ! -L $tgcompat_installer &&
        -f $glibc_lock && ! -L $glibc_lock &&
        -f $glibc_installer && ! -L $glibc_installer &&
        -f $glibc_package && ! -L $glibc_package &&
        -f $proot_lock && ! -L $proot_lock &&
        -f $proot_installer && ! -L $proot_installer &&
        -f $proot_builder && ! -L $proot_builder &&
        -f $debian_lock && ! -L $debian_lock &&
        -f $debian_installer && ! -L $debian_installer &&
        -x $launcher_installer && ! -L $launcher_installer ]] ||
    fail 'release archive is incomplete or contains unsafe links'
[[ $(getprop ro.product.cpu.abi) == arm64-v8a ]] ||
    fail 'this profile requires an ARM64 Android device'

if ! command -v python3 >/dev/null 2>&1; then
    "$PREFIX/bin/pkg" install -y python
fi

python3 "$setup" --package-profile "$profile" \
    dependencies --install --yes --base "$base"
python3 "$setup" --lock "$lock" prepare --base "$base"
python3 "$turnip_installer" --lock "$turnip_lock" install --base "$base"
python3 "$tgcompat_installer" --lock "$tgcompat_lock" --base "$base"
python3 "$glibc_installer" --lock "$glibc_lock" \
    --package "$glibc_package" --base "$base"
python3 "$proot_installer" --lock "$proot_lock" \
    --builder "$proot_builder" --base "$base"
python3 "$debian_installer" --lock "$debian_lock" \
    --base "$base" --prefix "$PREFIX"
python3 "$setup" --lock "$lock" activate --base "$base"
exec "$launcher_installer"
