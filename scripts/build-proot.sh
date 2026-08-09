#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${1:-$HOME/steam-arm64/src/proot-production}"
commit="a89b3732ec6ae1db674510f0843b2f3db54d0a2f"

command -v git >/dev/null || { echo 'git is required' >&2; exit 1; }
command -v make >/dev/null || { echo 'make is required' >&2; exit 1; }
command -v sha256sum >/dev/null || { echo 'sha256sum is required' >&2; exit 1; }

patches=(
    proot-steam-android.patch
    proot-link2symlink-getdents.patch
    proot-link2symlink-host-path.patch
    proot-link2symlink-force-exdev.patch
    proot-runtime-bind-exact-detranslate.patch
    proot-pivot-detached-root.patch
    proot-pivot-drop-stale-bindings.patch
    proot-mountinfo-escape-paths.patch
    proot-runtime-mount-stack.patch
)

if [[ ! -d "$source_dir/.git" ]]; then
    mkdir -p "$(dirname "$source_dir")"
    git clone https://github.com/termux/proot.git "$source_dir"
fi

git -C "$source_dir" fetch origin "$commit"
git -C "$source_dir" checkout --detach "$commit"
stamp="$source_dir/.steamclienttermux-patchset"
patchset_hash="$({
    for patch in "${patches[@]}"; do
        sha256sum "$repo_root/patches/$patch"
    done
} | sha256sum | awk '{print $1}')"

if [[ -f "$stamp" ]]; then
    stamped_commit="$(sed -n 's/^commit=//p' "$stamp")"
    stamped_patchset="$(sed -n 's/^patchset_sha256=//p' "$stamp")"
    stamped_diff="$(sed -n 's/^diff_sha256=//p' "$stamp")"
    current_diff="$(git -C "$source_dir" diff --binary | sha256sum | awk '{print $1}')"
    if [[ "$stamped_commit" != "$commit" ]] ||
            [[ "$stamped_patchset" != "$patchset_hash" ]] ||
            [[ "$stamped_diff" != "$current_diff" ]]; then
        printf 'Refusing changed or stale patched source tree: %s\n' "$source_dir" >&2
        exit 1
    fi
    printf 'Verified existing patch set: %s\n' "$patchset_hash"
else
    if ! git -C "$source_dir" diff --quiet; then
        printf 'Refusing source modifications without a patch-set stamp: %s\n' \
            "$source_dir" >&2
        exit 1
    fi
    for patch in "${patches[@]}"; do
        git -C "$source_dir" apply --check "$repo_root/patches/$patch"
        git -C "$source_dir" apply "$repo_root/patches/$patch"
    done
    current_diff="$(git -C "$source_dir" diff --binary | sha256sum | awk '{print $1}')"
    printf 'commit=%s\npatchset_sha256=%s\ndiff_sha256=%s\n' \
        "$commit" "$patchset_hash" "$current_diff" >"$stamp"
fi
make -C "$source_dir/src" clean
make -C "$source_dir/src" -j"$(nproc)" PROOT_WITH_LIBANDROID_SHMEM=1

printf 'Built patched PRoot: %s\n' "$source_dir/src/proot"
