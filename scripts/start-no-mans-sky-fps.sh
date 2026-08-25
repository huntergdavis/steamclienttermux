#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

launcher=${NO_MANS_SKY_FPS_LAUNCHER:-$HOME/start-no-mans-sky-direct}
package=mangohud-glibc

[[ -x $launcher && ! -L $launcher ]] || {
    printf 'start-no-mans-sky-fps: launcher is unavailable: %s\n' "$launcher" >&2
    exit 1
}
if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) != \
        'install ok installed' ]]; then
    printf 'start-no-mans-sky-fps: install the maintained FPS layer first:\n' >&2
    printf '  pkg install %s\n' "$package" >&2
    exit 1
fi

exec env NO_MANS_SKY_MANGOHUD=1 "$launcher" "$@"
