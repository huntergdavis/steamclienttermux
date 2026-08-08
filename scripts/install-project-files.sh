#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="$HOME/steam-arm64"
stamp="$(date +%Y%m%d-%H%M%S)"
backup="$base/backups/repo-install-$stamp"

install_one() {
    local source="$1" destination="$2" mode="$3"
    mkdir -p "$(dirname "$destination")" "$backup"
    if [[ -e "$destination" || -L "$destination" ]]; then
        cp -a -- "$destination" "$backup/$(basename "$destination")"
    fi
    install -m "$mode" "$source" "$destination"
}

install_one "$repo_root/bin/steam-arm" "$HOME/bin/steam-arm" 700
install_one "$repo_root/bin/patch-steam-network-ui.sh" "$base/patch-steam-network-ui.sh" 700
install_one "$repo_root/bin/lsof" "$base/compat-bin/lsof" 700
install_one "$repo_root/config/hosts-ipv4" "$base/config/hosts-ipv4" 600
install_one "$repo_root/config/steam-arm64-compatibilitytools.vdf.in" "$base/config/steam-arm64-compatibilitytools.vdf.in" 600
install_one "$repo_root/desktop/steam-arm.desktop" "$HOME/.local/share/applications/steam-arm.desktop" 600

mkdir -p "$base/mesa-kgsl/icd.d"
sed "s|@HOME@|$HOME|g" "$repo_root/config/freedreno-private.json.in" > "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp"
mv "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp" "$base/mesa-kgsl/icd.d/freedreno-private.json"

printf 'Installed project files. Backups: %s\n' "$backup"
