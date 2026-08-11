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
    proot-runtime-directory-bind-target.patch
)
case "${PROOT_ENABLE_NODEREF_FASTPATH:-0}" in
    0)
        ;;
    1)
        patches+=(proot-noderef-fastpath.patch)
        ;;
    *)
        printf 'PROOT_ENABLE_NODEREF_FASTPATH must be 0 or 1\n' >&2
        exit 1
        ;;
esac
patch_names="${patches[*]}"

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
write_stamp=0
stamped_proot=""

if [[ -f "$stamp" ]]; then
    stamped_commit="$(sed -n 's/^commit=//p' "$stamp")"
    stamped_patchset="$(sed -n 's/^patchset_sha256=//p' "$stamp")"
    stamped_diff="$(sed -n 's/^diff_sha256=//p' "$stamp")"
    stamped_patches="$(sed -n 's/^patches=//p' "$stamp")"
    stamped_proot="$(sed -n 's/^proot_sha256=//p' "$stamp")"
    current_diff="$(git -C "$source_dir" diff --binary | sha256sum | awk '{print $1}')"
    if [[ "$stamped_commit" != "$commit" ]] ||
            [[ "$stamped_patchset" != "$patchset_hash" ]] ||
            [[ "$stamped_diff" != "$current_diff" ]] ||
            [[ "$stamped_patches" != "$patch_names" ]] ||
            [[ ! "$stamped_proot" =~ ^[0-9a-f]{64}$ ]]; then
        printf 'Refusing changed or stale patched source tree: %s\n' "$source_dir" >&2
        exit 1
    fi
    if [[ ! -x "$source_dir/src/proot" ]]; then
        printf 'Refusing stamped source tree without built PRoot: %s\n' \
            "$source_dir/src/proot" >&2
        exit 1
    fi
    current_proot="$(sha256sum "$source_dir/src/proot" | awk '{print $1}')"
    if [[ "$current_proot" != "$stamped_proot" ]]; then
        printf 'Refusing changed PRoot binary in stamped source tree: %s\n' \
            "$source_dir/src/proot" >&2
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
    write_stamp=1
fi
make -C "$source_dir/src" clean
make -C "$source_dir/src" -j"$(nproc)" PROOT_WITH_LIBANDROID_SHMEM=1

built_proot="$source_dir/src/proot"
if [[ ! -x "$built_proot" ]]; then
    printf 'Build did not produce an executable PRoot: %s\n' "$built_proot" >&2
    exit 1
fi
built_proot_hash="$(sha256sum "$built_proot" | awk '{print $1}')"
if (( write_stamp )); then
    stamp_tmp="$(mktemp "$stamp.tmp.XXXXXX")"
    cleanup_stamp_tmp() {
        if [[ -n "${stamp_tmp:-}" ]] && [[ -f "$stamp_tmp" ]] &&
                [[ ! -L "$stamp_tmp" ]]; then
            unlink -- "$stamp_tmp"
        fi
    }
    trap cleanup_stamp_tmp EXIT
    printf 'commit=%s\npatchset_sha256=%s\ndiff_sha256=%s\npatches=%s\nproot_sha256=%s\n' \
        "$commit" "$patchset_hash" "$current_diff" "$patch_names" \
        "$built_proot_hash" >"$stamp_tmp"
    mv -- "$stamp_tmp" "$stamp"
    stamp_tmp=""
    trap - EXIT
elif [[ "$built_proot_hash" != "$stamped_proot" ]]; then
    printf 'Refusing non-deterministic rebuilt PRoot: expected %s, got %s\n' \
        "$stamped_proot" "$built_proot_hash" >&2
    exit 1
fi

printf 'Built patched PRoot: %s\n' "$source_dir/src/proot"
