#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${1:-$HOME/steam-arm64}
source_run=$base/runtime/SteamLinuxRuntime_4-arm64/run
destination=$base/config/steamlinuxruntime4-run-direct
direct_parent=$base/runtime/SteamLinuxRuntime_4-arm64-direct
direct_selector=$direct_parent/current

fail() {
    printf 'prepare-runtime-direct-run: %s\n' "$*" >&2
    exit 1
}

[[ $base == /* && -f $source_run && ! -L $source_run ]] ||
    fail "runtime shadow run script is unavailable: $source_run"
[[ $(stat -c %u -- "$source_run") == $(id -u) ]] ||
    fail 'runtime shadow run script has an unexpected owner'
[[ $(grep -Fxc 'export PRESSURE_VESSEL_COPY_RUNTIME=1' "$source_run") == 1 ]] ||
    fail 'runtime run script has an unexpected copy policy'
grep -Fqx '# Generated file, do not edit' "$source_run" ||
    fail 'runtime run script is not the expected generated form'
grep -Fq 'pressure-vessel-unruntime' "$source_run" ||
    fail 'runtime run script does not invoke pressure-vessel-unruntime'
[[ $(grep -Fxc 'export PRESSURE_VESSEL_RUNTIME="${dir}"' "$source_run") == 1 ]] ||
    fail 'runtime run script has an unexpected runtime path'
direct_root=$(realpath -e -- "$direct_selector") ||
    fail "direct runtime root is unavailable: $direct_selector"
resolved_parent=$(realpath -e -- "$direct_parent") ||
    fail "direct runtime parent is unavailable: $direct_parent"
[[ $direct_root == "$resolved_parent"/* && -d $direct_root && ! -L $direct_root &&
        -f $direct_root/.steamclienttermux-runtime-direct-root &&
        ! -L $direct_root/.steamclienttermux-runtime-direct-root ]] ||
    fail "direct runtime root is unsafe: $direct_root"

install -d -m 0700 -- "$(dirname -- "$destination")"
[[ ! -L $destination ]] || fail "destination cannot be a symlink: $destination"
stage=$(mktemp "$destination.tmp.XXXXXX")
cleanup() {
    if [[ -n ${stage:-} && -f $stage && ! -L $stage ]]; then
        rm -- "$stage"
    fi
}
trap cleanup EXIT

sed -e 's/^export PRESSURE_VESSEL_COPY_RUNTIME=1$/unset PRESSURE_VESSEL_COPY_RUNTIME/' \
    -e "s|^export PRESSURE_VESSEL_RUNTIME=\"\${dir}\"$|export PRESSURE_VESSEL_RUNTIME=\"$direct_root\"|" \
    "$source_run" >"$stage"
[[ $(grep -Fxc 'unset PRESSURE_VESSEL_COPY_RUNTIME' "$stage") == 1 &&
        $(grep -Fxc 'export PRESSURE_VESSEL_COPY_RUNTIME=1' "$stage") == 0 &&
        $(grep -Fxc "export PRESSURE_VESSEL_RUNTIME=\"$direct_root\"" "$stage") == 1 ]] ||
    fail 'unable to generate direct runtime policy'
chmod 0700 "$stage"

if [[ -f $destination && ! -L $destination ]] && cmp -s "$stage" "$destination"; then
    rm -- "$stage"
else
    mv -- "$stage" "$destination"
fi
stage=
trap - EXIT
printf 'Prepared direct Runtime 4 policy: %s\n' "$destination"
