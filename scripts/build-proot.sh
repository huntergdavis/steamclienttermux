#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${1:-$HOME/steam-arm64/src/proot-production}"
commit="a89b3732ec6ae1db674510f0843b2f3db54d0a2f"
profile="${PROOT_BUILD_PROFILE:-portable}"
jobs="${PROOT_BUILD_JOBS:-$(nproc)}"

command -v git >/dev/null || { echo 'git is required' >&2; exit 1; }
command -v make >/dev/null || { echo 'make is required' >&2; exit 1; }
command -v sha256sum >/dev/null || { echo 'sha256sum is required' >&2; exit 1; }
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || {
    printf 'PROOT_BUILD_JOBS must be a positive integer\n' >&2
    exit 1
}

profile_cflags=""
profile_main_cflags=""
profile_cli_cflags=""
profile_ldflags=""
strip_release=0
case "$profile" in
    portable)
        ;;
    native)
        compiler="${CC:-cc}"
        command -v "$compiler" >/dev/null || {
            printf 'Compiler is unavailable: %s\n' "$compiler" >&2
            exit 1
        }
        target="$($compiler -dumpmachine 2>/dev/null || true)"
        cpu_flag=""
        case "$target" in
            aarch64*)
                arm_march=armv8-a
                cpu_features=" $(sed -n 's/^Features[[:space:]]*:[[:space:]]*/ /p' \
                    /proc/cpuinfo 2>/dev/null | head -n 1) "
                [[ "$cpu_features" == *' crc32 '* ]] && arm_march+=+crc
                if [[ "$cpu_features" == *' aes '* &&
                        "$cpu_features" == *' pmull '* &&
                        "$cpu_features" == *' sha1 '* &&
                        "$cpu_features" == *' sha2 '* ]]; then
                    arm_march+=+crypto
                fi
                [[ "$cpu_features" == *' atomics '* ]] && arm_march+=+lse
                cpu_flag="-march=$arm_march"
                ;;
            arm*) cpu_flag=-mcpu=native ;;
            *) cpu_flag=-march=native ;;
        esac
        profile_cflags="-Wall -Wextra -O2 -DWITH_LIBANDROID_SHMEM"
        profile_main_cflags="-O3 -DNDEBUG -flto=thin -fno-plt -fno-semantic-interposition -fomit-frame-pointer -ffunction-sections -fdata-sections $cpu_flag"
        profile_cli_cflags="$profile_main_cflags -fno-lto"
        profile_ldflags="-ltalloc -landroid-shmem -flto=thin -Wl,-O2,--as-needed,--gc-sections,-z,relro,-z,now,-z,noexecstack"
        strip_release=1
        ;;
    *)
        printf 'PROOT_BUILD_PROFILE must be portable or native\n' >&2
        exit 1
        ;;
esac
build_options_hash="$({
    printf 'profile=%s\ncflags=%s\nmain_cflags=%s\ncli_cflags=%s\nldflags=%s\nstrip=%s\n' \
        "$profile" "$profile_cflags" "$profile_main_cflags" \
        "$profile_cli_cflags" \
        "$profile_ldflags" "$strip_release"
} | sha256sum | awk '{print $1}')"

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
if [[ "$profile" == native ]]; then
    patches+=(proot-main-cflags.patch)
fi
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
    stamped_profile="$(sed -n 's/^build_profile=//p' "$stamp")"
    stamped_options="$(sed -n 's/^build_options_sha256=//p' "$stamp")"
    if [[ -z "$stamped_profile" && "$profile" == portable ]]; then
        stamped_profile=portable
        stamped_options="$build_options_hash"
    fi
    current_diff="$(git -C "$source_dir" diff --binary | sha256sum | awk '{print $1}')"
    if [[ "$stamped_commit" != "$commit" ]] ||
            [[ "$stamped_patchset" != "$patchset_hash" ]] ||
            [[ "$stamped_diff" != "$current_diff" ]] ||
            [[ "$stamped_patches" != "$patch_names" ]] ||
            [[ "$stamped_profile" != "$profile" ]] ||
            [[ "$stamped_options" != "$build_options_hash" ]] ||
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
make_args=(-C "$source_dir/src" -j"$jobs" PROOT_WITH_LIBANDROID_SHMEM=1)
if [[ "$profile" == native ]]; then
    make_args+=(
        "CFLAGS=$profile_cflags"
        "PROOT_MAIN_CFLAGS=$profile_main_cflags"
        "PROOT_CLI_CFLAGS=$profile_cli_cflags"
        "LDFLAGS=$profile_ldflags"
    )
fi
make "${make_args[@]}"

built_proot="$source_dir/src/proot"
if [[ ! -x "$built_proot" ]]; then
    printf 'Build did not produce an executable PRoot: %s\n' "$built_proot" >&2
    exit 1
fi
if (( strip_release )); then
    if command -v llvm-strip >/dev/null 2>&1; then
        stripper=llvm-strip
    else
        stripper="${STRIP:-strip}"
    fi
    command -v "$stripper" >/dev/null || {
        printf 'Strip tool is unavailable: %s\n' "$stripper" >&2
        exit 1
    }
    "$stripper" --strip-unneeded "$built_proot"
fi
"$built_proot" --version >/dev/null
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
    printf 'commit=%s\npatchset_sha256=%s\ndiff_sha256=%s\npatches=%s\nbuild_profile=%s\nbuild_options_sha256=%s\nproot_sha256=%s\n' \
        "$commit" "$patchset_hash" "$current_diff" "$patch_names" \
        "$profile" "$build_options_hash" \
        "$built_proot_hash" >"$stamp_tmp"
    mv -- "$stamp_tmp" "$stamp"
    stamp_tmp=""
    trap - EXIT
elif [[ "$built_proot_hash" != "$stamped_proot" ]]; then
    printf 'Refusing non-deterministic rebuilt PRoot: expected %s, got %s\n' \
        "$stamped_proot" "$built_proot_hash" >&2
    exit 1
fi

printf 'Built patched PRoot (%s): %s\n' "$profile" "$source_dir/src/proot"
