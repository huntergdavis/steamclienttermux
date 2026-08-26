#!/usr/bin/env bash

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
source_dir=$root/native/nms-openvr-stub
output_dir=${1:-"$root/out/nms-openvr-stub"}
compiler=${BVB_MINGW_CC:-aarch64-w64-mingw32-gcc}

command -v "$compiler" >/dev/null 2>&1 || {
    printf 'build-nms-openvr-stub: missing compiler: %s\n' "$compiler" >&2
    exit 1
}
[[ ! -e $output_dir || (-d $output_dir && ! -L $output_dir) ]] || {
    printf 'build-nms-openvr-stub: unsafe output directory: %s\n' "$output_dir" >&2
    exit 1
}
mkdir -p "$output_dir"

output=$output_dir/openvr_api.dll
"$compiler" -std=c11 -O2 -s -Wall -Wextra -Werror -shared -nostdlib \
    -Wl,--no-insert-timestamp -Wl,--entry,DllMain -Wl,--image-base,0x182000000 \
    -o "$output" "$source_dir/openvr_stub.c" "$source_dir/openvr_api.def"
printf 'nms-openvr-stub: %s\n' "$output"
sha256sum "$output"
