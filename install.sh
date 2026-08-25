#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
installer=$repo_root/scripts/bootstrap-termux-stack.sh

[[ -f $installer && ! -L $installer && -x $installer ]] || {
    printf 'install: release is incomplete: %s\n' "$installer" >&2
    exit 1
}
[[ $# -eq 0 ]] || {
    printf 'usage: ./install.sh\n' >&2
    exit 2
}

exec "$installer"
