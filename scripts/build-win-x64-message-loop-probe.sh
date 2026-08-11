#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/build/win-x64-message-loop-probe}"
source_file="$repo_root/diagnostics/win-x64-message-loop-probe.c"
kernel_def="$repo_root/diagnostics/win-x64-kernel32.def"
user_def="$repo_root/diagnostics/win-x64-user32.def"

for tool in clang llvm-dlltool lld-link llvm-readobj; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Required LLVM tool is missing: %s\n' "$tool" >&2
        exit 1
    fi
done

mkdir -p "$output_dir"

llvm-dlltool -m i386:x86-64 -d "$kernel_def" \
    -l "$output_dir/kernel32.lib"
llvm-dlltool -m i386:x86-64 -d "$user_def" \
    -l "$output_dir/user32.lib"

clang --target=x86_64-pc-windows-msvc \
    -O2 -Wall -Wextra -Werror \
    -ffreestanding -fno-builtin -fno-stack-protector \
    -c "$source_file" -o "$output_dir/win-x64-message-loop-probe.obj"

lld-link \
    /machine:x64 \
    /subsystem:console \
    /entry:mainCRTStartup \
    /nodefaultlib \
    /timestamp:0 \
    "/out:$output_dir/win-x64-message-loop-probe.exe" \
    "$output_dir/win-x64-message-loop-probe.obj" \
    "$output_dir/kernel32.lib" \
    "$output_dir/user32.lib"

llvm-readobj --file-headers --coff-imports \
    "$output_dir/win-x64-message-loop-probe.exe"
