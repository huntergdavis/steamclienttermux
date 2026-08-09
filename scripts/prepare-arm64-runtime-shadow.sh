#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="${1:-$HOME/steam-arm64}"
client="$base/client"
source_runtime="$client/steamapps/common/SteamLinuxRuntime_4-arm64"
pressure_vessel_donor="$client/steamapps/common/SteamLinuxRuntime_4/pressure-vessel-arm64"
destination="${2:-$base/runtime/SteamLinuxRuntime_4-arm64}"
marker="$destination/.steamclienttermux-runtime-shadow"

require_file() {
    if [[ ! -f "$1" ]]; then
        printf 'Required official runtime file is missing: %s\n' "$1" >&2
        exit 1
    fi
}

require_no_l2s_links() {
    local search_root="$1"
    local refusal_message="$2"
    local refusal_path="${3:-$search_root}"
    local match

    if ! match="$(find "$search_root" -type l -lname '*/.l2s/*' -print -quit)"; then
        printf 'Unable to inspect runtime tree for .l2s links: %s\n' \
            "$search_root" >&2
        exit 1
    fi
    if [[ -n "$match" ]]; then
        printf '%s: %s\n' "$refusal_message" "$refusal_path" >&2
        exit 1
    fi
}

require_file "$source_runtime/_v2-entry-point"
require_file "$source_runtime/run"
require_file "$source_runtime/pressure-vessel/bin/pressure-vessel-wrap"
require_file "$pressure_vessel_donor/bin/pressure-vessel-wrap"

require_no_l2s_links "$pressure_vessel_donor" \
    'Refusing pseudo-hardlink Pressure Vessel donor'

source_hash="$(sha256sum "$source_runtime/pressure-vessel/bin/pressure-vessel-wrap" | awk '{print $1}')"
donor_hash="$(sha256sum "$pressure_vessel_donor/bin/pressure-vessel-wrap" | awk '{print $1}')"
if [[ "$source_hash" != "$donor_hash" ]]; then
    printf 'ARM64 pressure-vessel donor does not match the installed runtime: %s != %s\n' \
        "$donor_hash" "$source_hash" >&2
    exit 1
fi

if [[ -e "$destination" ]]; then
    if [[ -f "$marker" ]] && [[ -x "$destination/pressure-vessel/bin/pressure-vessel-wrap" ]]; then
        require_no_l2s_links "$destination/pressure-vessel" \
            'Refusing contaminated existing runtime shadow' "$destination"
        installed_hash="$(sha256sum "$destination/pressure-vessel/bin/pressure-vessel-wrap" | awk '{print $1}')"
        if [[ "$installed_hash" == "$source_hash" ]]; then
            printf 'ARM64 runtime shadow is already prepared: %s\n' "$destination"
            exit 0
        fi
    fi
    printf 'Refusing to replace existing runtime shadow: %s\n' "$destination" >&2
    exit 1
fi

parent="$(dirname "$destination")"
stage="$parent/.SteamLinuxRuntime_4-arm64.prepare.$$"
mkdir -p "$parent"
if [[ -e "$stage" ]]; then
    printf 'Refusing to reuse existing preparation directory: %s\n' "$stage" >&2
    exit 1
fi

mkdir "$stage"
cp -a "$source_runtime/." "$stage/"

# A previous PRoot attempt can leave valid but incomplete mutable-runtime
# state in var/. Preserve the copied state for diagnosis and give the shadow a
# clean private variable directory without changing the official installation.
if [[ -e "$stage/var" ]]; then
    mv "$stage/var" "$stage/var-installed-state"
fi
install -d -m 700 "$stage/var"

# The installed ARM payload can have Pressure Vessel represented as PRoot
# pseudo-hardlinks. Its bytes are intact, but executing the backing path breaks
# $ORIGIN lookup. Preserve that copy and install the hash-identical real-file
# ARM64 Pressure Vessel shipped in the conventional Runtime 4 depot.
mv "$stage/pressure-vessel" "$stage/pressure-vessel-l2s-original"
cp -a "$pressure_vessel_donor" "$stage/pressure-vessel"

require_no_l2s_links "$stage/pressure-vessel" \
    'Prepared Pressure Vessel unexpectedly contains .l2s links'

prepared_hash="$(sha256sum "$stage/pressure-vessel/bin/pressure-vessel-wrap" | awk '{print $1}')"
if [[ "$prepared_hash" != "$source_hash" ]]; then
    printf 'Prepared pressure-vessel hash mismatch: %s != %s\n' \
        "$prepared_hash" "$source_hash" >&2
    exit 1
fi

printf 'source_runtime=%s\npressure_vessel_sha256=%s\n' \
    "$source_runtime" "$source_hash" >"$stage/.steamclienttermux-runtime-shadow"
mv "$stage" "$destination"

printf 'Prepared ARM64 runtime shadow: %s\n' "$destination"
