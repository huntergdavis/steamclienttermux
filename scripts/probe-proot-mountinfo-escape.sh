#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--inside-proot" ]]; then
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    script="$script_dir/${BASH_SOURCE[0]##*/}"
    custom_proot_dir="${PROOT_BUILD_DIR:-$HOME/steam-arm64/src/proot-production/src}"
    if [[ ! -x "$custom_proot_dir/proot" ]]; then
        printf 'Patched PRoot not found: %s/proot\n' "$custom_proot_dir" >&2
        exit 1
    fi
    export PATH="$custom_proot_dir:$PATH"
    exec proot-distro login debian --shared-tmp -- \
        /bin/bash "$script" --inside-proot
fi

probe_root="$(mktemp -d '/tmp/proot mountinfo probe.XXXXXX')"
cleanup() {
    umount "$probe_root/destination with space\\slash" 2>/dev/null || true
    rmdir "$probe_root/destination with space\\slash" \
        "$probe_root/source with space\\slash" "$probe_root" 2>/dev/null || true
}
trap cleanup EXIT

source_path="$probe_root/source with space\\slash"
target_path="$probe_root/destination with space\\slash"
mkdir "$source_path" "$target_path"
mount --bind "$source_path" "$target_path"

python3 - "$target_path" <<'PY'
import re
import sys

target = sys.argv[1]
escape_re = re.compile(r"\\([0-7]{3})")


def decode_mountinfo(value: str) -> str:
    return escape_re.sub(lambda match: chr(int(match.group(1), 8)), value)


with open("/proc/self/mountinfo", encoding="utf-8") as mountinfo:
    lines = mountinfo.read().splitlines()

matches = []
for line in lines:
    fields = line.split()
    if len(fields) < 10 or "-" not in fields:
        continue
    if decode_mountinfo(fields[4]) == target:
        matches.append((line, fields))

if len(matches) != 1:
    raise SystemExit(
        f"expected one decoded mountpoint for {target!r}, found {len(matches)}"
    )

line, fields = matches[0]
separator = fields.index("-")
source = fields[separator + 2]
if r"\040" not in fields[4] or r"\134" not in fields[4]:
    raise SystemExit(f"mountpoint is not mountinfo-escaped: {fields[4]!r}")
if r"\040" not in source or r"\134" not in source:
    raise SystemExit(f"mount source is not mountinfo-escaped: {source!r}")

print("mountinfo-escape: PASS")
print(line)
PY
