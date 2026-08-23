#!/usr/bin/env bash

set -euo pipefail
umask 077

fex_repository=https://github.com/FEX-Emu/FEX.git
fex_commit=a04b0241c2fe3911729842205cd8643981108aad
process_all_commit=329e561effcdc751f860d289ffc13aa5e1a66df1
windows_backend_commit=6d1cd6790071884dce058e223c3cacf3a0db43f7
windows_integration_commit=6cb73adfd509597e58918832c1a42dad56c62538
toolchain_url=https://github.com/bylaws/llvm-mingw/releases/download/20250920/llvm-mingw-20250920-ucrt-ubuntu-22.04-x86_64.tar.xz
toolchain_sha256=8dd8c34fc051a50c2fae86015f35057f8aae93fe1e19b34537ef1269a8b4c772
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_directory/.." && pwd -P)
compat_patch=$repo_root/patches/fex-2605-arm64ec-offline-compiler-compat.patch

fail() {
    printf 'build-fex-2605-offline-compiler: %s\n' "$*" >&2
    exit 1
}

[[ $# == 1 ]] || fail 'usage: build-fex-2605-offline-compiler.sh OUTPUT-DIRECTORY'
output=$1
[[ $output == /* ]] || output=$PWD/$output
[[ ! -e $output && ! -L $output ]] || fail "output already exists: $output"
[[ -f $compat_patch && ! -L $compat_patch ]] || fail "compatibility patch is unavailable: $compat_patch"
for command in cmake curl file git ninja python3 sha256sum tar; do
    command -v "$command" >/dev/null || fail "required command is unavailable: $command"
done

work_root=$(mktemp -d "${TMPDIR:-/tmp}/fex-2605-offline.XXXXXXXX")
printf 'WORK_ROOT=%s\n' "$work_root"
toolchain_archive=$work_root/llvm-mingw.tar.xz
toolchain=$work_root/llvm-mingw
source=$work_root/FEX
build=$work_root/build
mkdir -m 700 "$toolchain"

curl -fL --retry 3 --output "$toolchain_archive" "$toolchain_url"
printf '%s  %s\n' "$toolchain_sha256" "$toolchain_archive" | sha256sum -c -
tar -xJf "$toolchain_archive" --strip-components=1 -C "$toolchain"
[[ -x $toolchain/bin/arm64ec-w64-mingw32-clang ]] ||
    fail 'pinned ARM64EC compiler is unavailable after extraction'

git clone --filter=blob:none --no-checkout "$fex_repository" "$source"
git -C "$source" checkout --detach "$fex_commit"
git -C "$source" config user.name steamclienttermux-builder
git -C "$source" config user.email build@invalid
git -C "$source" cherry-pick "$process_all_commit" "$windows_backend_commit"
if git -C "$source" cherry-pick "$windows_integration_commit"; then
    fail 'upstream integration unexpectedly applied without the audited FEX-2605 conflict'
fi
[[ $(git -C "$source" diff --name-only --diff-filter=U) == Source/Tools/FEXOfflineCompiler/Main.cpp ]] ||
    fail 'upstream integration produced an unexpected conflict set'
git -C "$source" checkout --theirs -- Source/Tools/FEXOfflineCompiler/Main.cpp
git -C "$source" add Source/Tools/FEXOfflineCompiler/Main.cpp
GIT_EDITOR=true git -C "$source" cherry-pick --continue
git -C "$source" apply --check "$compat_patch"
git -C "$source" apply "$compat_patch"
git -C "$source" diff --check
SOURCE_DATE_EPOCH=$(git -C "$source" show -s --format=%ct "$fex_commit")
export SOURCE_DATE_EPOCH

git -C "$source" submodule update --init --depth 1 \
    External/rpmalloc External/unordered_dense External/xxhash External/fmt \
    External/range-v3 External/vixl External/zydis Source/Common/cpp-optparse

PATH=$toolchain/bin:$PATH cmake -S "$source" -B "$build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$source/Data/CMake/toolchain_mingw.cmake" \
    -DMINGW_TRIPLE=arm64ec-w64-mingw32 \
    -DOVERRIDE_HASH="$fex_commit" \
    -DOVERRIDE_VERSION=FEX-2605 \
    -DENABLE_LTO=False \
    -DENABLE_ASSERTIONS=False \
    -DBUILD_TESTING=False
PATH=$toolchain/bin:$PATH ninja -C "$build" -j "${FEX_BUILD_JOBS:-2}" FEXOfflineCompiler

compiler=$build/Bin/FEXOfflineCompiler.exe
[[ -f $compiler && ! -L $compiler ]] || fail 'compiler build did not produce the expected executable'
mkdir -m 700 "$output"
install -m 700 "$compiler" "$output/FEXOfflineCompiler.exe"
file "$output/FEXOfflineCompiler.exe" >"$output/file.txt"
sha256sum "$output/FEXOfflineCompiler.exe" >"$output/SHA256SUMS"
cat >"$output/build-identity.txt" <<EOF
fex_commit=$fex_commit
process_all_commit=$process_all_commit
windows_backend_commit=$windows_backend_commit
windows_integration_commit=$windows_integration_commit
toolchain_url=$toolchain_url
toolchain_sha256=$toolchain_sha256
override_hash=$fex_commit
override_version=FEX-2605
work_root=$work_root
EOF
chmod 600 "$output/file.txt" "$output/SHA256SUMS" "$output/build-identity.txt"
printf 'FEX_OFFLINE_COMPILER=%s\n' "$output/FEXOfflineCompiler.exe"
printf 'SHA256=%s\n' "$(sha256sum "$output/FEXOfflineCompiler.exe" | cut -d' ' -f1)"
