#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

target="$HOME/steam-arm64/client/steamui/chunk~2dcc5aaf7.js"
backup="$HOME/steam-arm64/backups/chunk~2dcc5aaf7.js.pre-network-guard"
mkdir -p "${backup%/*}"
if [[ ! -f "$backup" ]]; then
    cp -p -- "$target" "$backup"
fi

replace_one() {
    local old="$1" new="$2"
    OLD="$old" NEW="$new" perl -0pi -e '
        BEGIN { $old=$ENV{OLD}; $new=$ENV{NEW}; }
        $count = s/\Q$old\E/$new/g;
        END { die "expected exactly one compatibility target, found $count\n" unless $count == 1; }
    ' "$target"
}

if ! grep -qF 'const t="function"==typeof SteamClient.System.Network.RegisterForDeviceChanges' "$target"; then
    replace_one \
        'const t=(0,B.Dp)("System.Network.RegisterForDeviceChanges");t&&SteamClient.System.Network.RegisterForDeviceChanges' \
        'const t="function"==typeof SteamClient.System.Network.RegisterForDeviceChanges;t&&SteamClient.System.Network.RegisterForDeviceChanges'
fi
if ! grep -qF '"function"==typeof SteamClient.System.Network.GetProxyInfo' "$target"; then
    replace_one \
        '(0,B.Dp)("System.Network.GetProxyInfo")&&SteamClient.System.Network.GetProxyInfo()' \
        '"function"==typeof SteamClient.System.Network.GetProxyInfo&&SteamClient.System.Network.GetProxyInfo()'
fi
if ! grep -qF '"function"==typeof SteamClient.System.Network.RegisterForConnectivityTestChanges' "$target"; then
    replace_one \
        '(0,B.Dp)("System.Network.RegisterForConnectivityTestChanges")&&SteamClient.System.Network.RegisterForConnectivityTestChanges' \
        '"function"==typeof SteamClient.System.Network.RegisterForConnectivityTestChanges&&SteamClient.System.Network.RegisterForConnectivityTestChanges'
fi

cmp -s -- "$target" "$backup" && {
    printf 'Steam UI network guard was not changed\n' >&2
    exit 1
}
printf 'Patched %s (backup: %s)\n' "$target" "$backup"
