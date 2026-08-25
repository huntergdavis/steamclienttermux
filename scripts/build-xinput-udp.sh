#!/usr/bin/env bash

set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
source_dir="$root/native/xinput-udp"
output_dir=${1:-"$root/out/xinput-udp"}
compiler=${BVB_MINGW_CC:-x86_64-w64-mingw32-gcc}

command -v "$compiler" >/dev/null 2>&1 || {
    printf 'build-xinput-udp: missing compiler: %s\n' "$compiler" >&2
    exit 1
}
[[ ! -e $output_dir || (-d $output_dir && ! -L $output_dir) ]] || {
    printf 'build-xinput-udp: unsafe output directory: %s\n' "$output_dir" >&2
    exit 1
}
mkdir -p "$output_dir"

for library in xinput1_3 xinput9_1_0; do
    output="$output_dir/$library.dll"
    if [[ $library == xinput1_3 ]]; then
        image_base=0x180000000
    else
        image_base=0x181000000
    fi
    "$compiler" -std=c11 -O2 -s -Wall -Wextra -Werror -shared \
        -Wl,--no-insert-timestamp -Wl,--kill-at -Wl,--image-base,"$image_base" \
        -o "$output" "$source_dir/xinput_udp.c" "$source_dir/$library.def" \
        -lws2_32
    printf 'xinput-udp: %s\n' "$output"
    sha256sum "$output"
done
