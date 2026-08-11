#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="$HOME/steam-arm64"
client="$base/client"
custom_proot="${PROOT_BUILD_DIR:-$base/src/proot-debug/src}"
target="${PROOT_BENCHMARK_TARGET:-$client/steamapps/common/Proton - Experimental}"

[[ -d "$target" ]] || { printf 'Missing benchmark tree: %s\n' "$target" >&2; exit 1; }
[[ -x "$custom_proot/proot" ]] || {
    printf 'Missing custom PRoot: %s/proot\n' "$custom_proot" >&2
    exit 1
}

if [[ "$target" == "$client"/* ]]; then
    bind_source="$client"
    bind_target=/opt/steam-client
    guest_target="$bind_target/${target#"$client"/}"
else
    bind_source="$target"
    bind_target=/opt/proot-benchmark-target
    guest_target="$bind_target"
fi

now() { date +%s%N; }

pd_args=(login debian)
if [[ -n "${PROOT_NODEREF_FAST_PATH:-}" ]]; then
    pd_args+=(--env "PROOT_NODEREF_FAST_PATH=$PROOT_NODEREF_FAST_PATH")
fi

start="$(now)"
count="$(find "$target" -xdev -type f -printf . | wc -c)"
end="$(now)"
printf '%-16s files=%s ns=%s\n' native "$count" "$((end-start))"

export PATH="$custom_proot:$PATH"
start="$(now)"
count="$(proot-distro "${pd_args[@]}" -- /bin/bash -c \
    'find "$1" -xdev -type f -printf . | wc -c' benchmark "$target")"
end="$(now)"
printf '%-16s files=%s ns=%s\n' proot-long "$count" "$((end-start))"

start="$(now)"
count="$(proot-distro "${pd_args[@]}" --bind "$bind_source:$bind_target" -- \
    /bin/bash -c 'find "$1" -xdev -type f -printf . | wc -c' benchmark \
    "$guest_target")"
end="$(now)"
printf '%-16s files=%s ns=%s\n' proot-bind "$count" "$((end-start))"
