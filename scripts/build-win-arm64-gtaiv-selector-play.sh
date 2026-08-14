#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/build/win-arm64-gtaiv-selector-play}"
source_file="$repo_root/diagnostics/win-arm64-gtaiv-selector-play.c"
kernel_def="$repo_root/diagnostics/win-arm64-kernel32.def"
user_def="$repo_root/diagnostics/win-arm64-user32-selector-play.def"

resolve_llvm_tool() {
    local tool="$1"
    local version
    if command -v "$tool" >/dev/null 2>&1; then
        command -v "$tool"
        return
    fi
    for version in 21 20 19 18 17 16; do
        if command -v "$tool-$version" >/dev/null 2>&1; then
            command -v "$tool-$version"
            return
        fi
    done
    printf 'Required LLVM tool is missing: %s\n' "$tool" >&2
    return 1
}

clang="$(resolve_llvm_tool clang)"
llvm_dlltool="$(resolve_llvm_tool llvm-dlltool)"
lld_link="$(resolve_llvm_tool lld-link)"
llvm_readobj="$(resolve_llvm_tool llvm-readobj)"

mkdir -p "$output_dir"

"$llvm_dlltool" -m arm64 -d "$kernel_def" -l "$output_dir/kernel32.lib"
"$llvm_dlltool" -m arm64 -d "$user_def" -l "$output_dir/user32.lib"

"$clang" --target=aarch64-pc-windows-msvc \
    -O2 -Wall -Wextra -Werror \
    -ffreestanding -fno-builtin -fno-stack-protector \
    -c "$source_file" -o "$output_dir/win-arm64-gtaiv-selector-play.obj"

"$lld_link" \
    /machine:arm64 \
    /subsystem:console \
    /entry:entry \
    /nodefaultlib \
    /timestamp:0 \
    "/out:$output_dir/win-arm64-gtaiv-selector-play.exe" \
    "$output_dir/win-arm64-gtaiv-selector-play.obj" \
    "$output_dir/kernel32.lib" \
    "$output_dir/user32.lib"

"$llvm_readobj" --file-headers --coff-imports \
    "$output_dir/win-arm64-gtaiv-selector-play.exe"
