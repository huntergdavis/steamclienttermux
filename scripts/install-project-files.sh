#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="$HOME/steam-arm64"
stamp="$(date +%Y%m%d-%H%M%S)"
backup="$base/backups/repo-install-$stamp"
proot_patch_stamp="$base/src/proot-production/.steamclienttermux-patchset"
proot_binary="$base/src/proot-production/src/proot"
required_proot_patch="proot-runtime-directory-bind-target.patch"

command -v sha256sum >/dev/null || { echo 'sha256sum is required' >&2; exit 1; }

if [[ ! -f "$proot_patch_stamp" ]] ||
        ! sed -n 's/^patches=//p' "$proot_patch_stamp" |
        tr ' ' '\n' | grep -Fxq "$required_proot_patch"; then
    printf 'Refusing install: production PRoot lacks %s\n' \
        "$required_proot_patch" >&2
    printf 'Build and deploy the repository PRoot patch set first.\n' >&2
    exit 1
fi
if [[ ! -x "$proot_binary" ]]; then
    printf 'Refusing install: production PRoot is not executable: %s\n' \
        "$proot_binary" >&2
    exit 1
fi
stamped_proot="$(sed -n 's/^proot_sha256=//p' "$proot_patch_stamp")"
if [[ ! "$stamped_proot" =~ ^[0-9a-f]{64}$ ]] ||
        [[ "$(sha256sum "$proot_binary" | awk '{print $1}')" != "$stamped_proot" ]]; then
    printf 'Refusing install: production PRoot does not match its build stamp: %s\n' \
        "$proot_binary" >&2
    exit 1
fi

install_one() {
    local source="$1" destination="$2" mode="$3"
    mkdir -p "$(dirname "$destination")" "$backup"
    if [[ -e "$destination" || -L "$destination" ]]; then
        cp -a -- "$destination" "$backup/$(basename "$destination")"
    fi
    install -m "$mode" "$source" "$destination"
}

wrapper_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-bwrap-route.XXXXXX")"
cleanup_wrapper_stage() {
    if [[ -n "$wrapper_stage" ]] && [[ -f "$wrapper_stage" ]] &&
            [[ ! -L "$wrapper_stage" ]]; then
        unlink -- "$wrapper_stage"
    fi
}
trap cleanup_wrapper_stage EXIT
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror \
    "$repo_root/diagnostics/pressure-vessel-route-bwrap.c" \
    -o "$wrapper_stage"

install_one "$repo_root/bin/steam-arm" "$HOME/bin/steam-arm" 700
install_one "$repo_root/bin/patch-steam-network-ui.sh" "$base/patch-steam-network-ui.sh" 700
install_one "$repo_root/bin/prepare-proc-net-shadow.sh" "$base/prepare-proc-net-shadow.sh" 700
install_one "$repo_root/bin/prepare-pulseaudio-tcp.sh" "$base/prepare-pulseaudio-tcp.sh" 700
install_one "$repo_root/bin/lsof" "$base/compat-bin/lsof" 700
install_one "$repo_root/bin/steam-arm64-session-guard.py" \
    "$base/compat-bin/steam-arm64-session-guard.py" 700
install_one "$repo_root/bin/steam-arm64-removable-library.py" \
    "$base/compat-bin/steam-arm64-removable-library.py" 700
install_one "$repo_root/scripts/configure-gtaiv-registry.py" \
    "$base/compat-bin/configure-gtaiv-registry.py" 700
install_one "$repo_root/scripts/configure-gtaiv-virtual-desktop.py" \
    "$base/compat-bin/configure-gtaiv-virtual-desktop.py" 700
install_one "$repo_root/scripts/configure-gtaiv-socialclub-wined3d.py" \
    "$base/compat-bin/configure-gtaiv-socialclub-wined3d.py" 700
install_one "$repo_root/scripts/configure-gtaiv-service-timeout.py" \
    "$base/compat-bin/configure-gtaiv-service-timeout.py" 700
install_one "$repo_root/scripts/monitor-termux-game-session.sh" \
    "$base/compat-bin/monitor-termux-game-session.sh" 700
install_one "$wrapper_stage" "$base/compat-bin/steam-arm64-bwrap-route" 700
unlink -- "$wrapper_stage"
wrapper_stage=""
trap - EXIT

install_one "$repo_root/config/hosts-ipv4" "$base/config/hosts-ipv4" 600
install_one "$repo_root/config/gtaiv-commandline-720p.txt" \
    "$base/gtaiv-exec-view-12210/commandline.txt" 600
gtaiv_prefix="$base/removable-library-compatdata/12210/pfx"
if [[ -d "$gtaiv_prefix/drive_c" ]]; then
    install_one "$repo_root/config/gtaiv-service-first.cmd" \
        "$gtaiv_prefix/drive_c/gtaiv-service-first.cmd" 600
fi
install_one "$repo_root/config/steam-arm64-compatibilitytools.vdf.in" "$base/config/steam-arm64-compatibilitytools.vdf.in" 600
install_one "$repo_root/desktop/steam-arm.desktop" "$HOME/.local/share/applications/steam-arm.desktop" 600

mkdir -p "$base/mesa-kgsl/icd.d"
sed "s|@HOME@|$HOME|g" "$repo_root/config/freedreno-private.json.in" > "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp"
mv "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp" "$base/mesa-kgsl/icd.d/freedreno-private.json"

printf 'Installed project files. Backups: %s\n' "$backup"
