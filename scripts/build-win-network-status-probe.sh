#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/build/win-network-status-probe}"
source_file="$repo_root/diagnostics/win-network-status-probe.c"
kernel_def="$repo_root/diagnostics/win-arm64-kernel32.def"
ole_def="$repo_root/diagnostics/win-arm64-ole32.def"

for tool in clang llvm-dlltool lld-link llvm-readobj; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Required LLVM tool is missing: %s\n' "$tool" >&2
        exit 1
    fi
done

mkdir -p "$output_dir"

llvm-dlltool -m arm64 -d "$kernel_def" \
    -l "$output_dir/kernel32.lib"
llvm-dlltool -m arm64 -d "$ole_def" \
    -l "$output_dir/ole32.lib"

clang --target=aarch64-pc-windows-msvc \
    -O2 -Wall -Wextra -Werror \
    -ffreestanding -fno-builtin -fno-stack-protector \
    -c "$source_file" -o "$output_dir/win-network-status-probe.obj"

lld-link \
    /machine:arm64 \
    /subsystem:console \
    /entry:mainCRTStartup \
    /nodefaultlib \
    /timestamp:0 \
    "/out:$output_dir/win-network-status-probe.exe" \
    "$output_dir/win-network-status-probe.obj" \
    "$output_dir/kernel32.lib" \
    "$output_dir/ole32.lib"

llvm-readobj --file-headers --coff-imports \
    "$output_dir/win-network-status-probe.exe"
