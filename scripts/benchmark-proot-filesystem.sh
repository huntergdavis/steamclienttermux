#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="$HOME/steam-arm64"
client="$base/client"
custom_proot="$base/src/proot-debug/src"
target="$client/steamapps/common/Proton - Experimental"

[[ -d "$target" ]] || { printf 'Missing benchmark tree: %s\n' "$target" >&2; exit 1; }
[[ -x "$custom_proot/proot" ]] || { printf 'Missing custom PRoot\n' >&2; exit 1; }

now() { date +%s%N; }

start="$(now)"
count="$(find "$target" -xdev -type f -printf . | wc -c)"
end="$(now)"
printf '%-16s files=%s ns=%s\n' native "$count" "$((end-start))"

export PATH="$custom_proot:$PATH"
start="$(now)"
count="$(proot-distro login debian -- /bin/bash -c \
    'find "$1" -xdev -type f -printf . | wc -c' benchmark "$target")"
end="$(now)"
printf '%-16s files=%s ns=%s\n' proot-long "$count" "$((end-start))"

start="$(now)"
count="$(proot-distro login debian --bind "$client:/opt/steam-client" -- \
    /bin/bash -c 'find "$1" -xdev -type f -printf . | wc -c' benchmark \
    '/opt/steam-client/steamapps/common/Proton - Experimental')"
end="$(now)"
printf '%-16s files=%s ns=%s\n' proot-bind "$count" "$((end-start))"
