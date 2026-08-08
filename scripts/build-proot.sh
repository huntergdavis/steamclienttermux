#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${1:-$HOME/steam-arm64/src/proot-steam-android}"
commit="a89b3732ec6ae1db674510f0843b2f3db54d0a2f"

command -v git >/dev/null || { echo 'git is required' >&2; exit 1; }
command -v make >/dev/null || { echo 'make is required' >&2; exit 1; }

if [[ ! -d "$source_dir/.git" ]]; then
    mkdir -p "$(dirname "$source_dir")"
    git clone https://github.com/termux/proot.git "$source_dir"
fi

git -C "$source_dir" fetch origin "$commit"
git -C "$source_dir" checkout --detach "$commit"
git -C "$source_dir" apply --check "$repo_root/patches/proot-steam-android.patch"
git -C "$source_dir" apply "$repo_root/patches/proot-steam-android.patch"
make -C "$source_dir/src" clean
make -C "$source_dir/src" -j"$(nproc)"

printf 'Built patched PRoot: %s\n' "$source_dir/src/proot"

