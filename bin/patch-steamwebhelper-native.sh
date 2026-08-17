#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
target=$base/client/steamrtarm64/steamwebhelper.sh
backup=$base/backups/steamwebhelper.sh.pre-native-dev-shm
original='exec taskset 0x7c $(pwd)/steamwebhelper "$@" &> ~/.steam/steam/logs/steamwebhelper.log'
patched='exec taskset 0x7c $(pwd)/steamwebhelper --disable-dev-shm-usage "$@" &> ~/.steam/steam/logs/steamwebhelper.log'

[[ -f $target && ! -L $target ]] || {
    printf 'Steam webhelper wrapper is missing or unsafe: %s\n' "$target" >&2
    exit 1
}
if grep -Fxq -- "$patched" "$target"; then
    exit 0
fi
[[ $(grep -Fxc -- "$original" "$target") -eq 1 ]] || {
    printf 'Steam webhelper wrapper has an unexpected launch line: %s\n' \
        "$target" >&2
    exit 1
}
mkdir -p "${backup%/*}"
if [[ ! -e $backup ]]; then
    cp -p -- "$target" "$backup"
fi
OLD=$original NEW=$patched perl -0pi -e '
    BEGIN { $old=$ENV{OLD}; $new=$ENV{NEW}; }
    $count = s/^\Q$old\E$/$new/mg;
    END { die "expected one Steam webhelper launch line, found $count\n"
        unless $count == 1; }
' "$target"
grep -Fxq -- "$patched" "$target" || {
    printf 'Steam webhelper wrapper patch did not persist: %s\n' "$target" >&2
    exit 1
}
printf 'Patched Steam webhelper to avoid unavailable /dev/shm: %s\n' "$target"
