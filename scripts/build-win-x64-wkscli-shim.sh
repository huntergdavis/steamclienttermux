#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/build/win-x64-wkscli-shim}"
source_file="$repo_root/diagnostics/win-x64-wkscli-shim.c"

for tool in clang lld-link llvm-readobj; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Required LLVM tool is missing: %s\n' "$tool" >&2
        exit 1
    fi
done

mkdir -p "$output_dir"

clang --target=x86_64-pc-windows-msvc \
    -O2 -Wall -Wextra -Werror \
    -ffreestanding -fno-builtin -fno-stack-protector \
    -c "$source_file" -o "$output_dir/win-x64-wkscli-shim.obj"

lld-link \
    /machine:x64 \
    /dll \
    /noentry \
    /nodefaultlib \
    /timestamp:0 \
    /export:NetGetJoinInformation \
    "/out:$output_dir/wkscli.dll" \
    "$output_dir/win-x64-wkscli-shim.obj"

llvm-readobj --file-headers --coff-imports --coff-exports \
    "$output_dir/wkscli.dll"
