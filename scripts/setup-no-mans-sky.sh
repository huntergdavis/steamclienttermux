#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
python=${NO_MANS_SKY_SETUP_PYTHON:-/data/data/com.termux/files/usr/bin/python3}
prepare=$base/compat-bin/prepare-no-mans-sky-proton.py
mapper=$HOME/bin/configure-steam-app-proton
tool=steamclienttermux_nms_proton_11_arm64_45a9ed5f

[[ -x $python && -f $prepare && ! -L $prepare ]] || {
    printf 'setup-no-mans-sky: contained Proton preparation is unavailable\n' >&2
    exit 1
}
[[ -x $mapper && ! -L $mapper ]] || {
    printf 'setup-no-mans-sky: Steam AppID mapper is unavailable\n' >&2
    exit 1
}

"$python" "$prepare" prepare --base "$base"
"$mapper" 275850 --tool "$tool" --base "$base"
printf 'No Man\047s Sky setup complete. Restart Steam, then run ~/start-no-mans-sky-direct\n'
