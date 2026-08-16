#!/usr/bin/env bash

set -euo pipefail

CDPATH=''
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)

for test_file in "$repo_root"/scripts/test-*.py; do
    PYTHONDONTWRITEBYTECODE=1 python3 "$test_file"
done

while IFS= read -r -d '' script; do
    case $(head -n 1 -- "$script") in
        *bash|*'/bin/sh')
            bash -n "$script"
            ;;
    esac
done < <(find "$repo_root/bin" "$repo_root/scripts" -maxdepth 1 -type f -print0)

git -C "$repo_root" diff --check
printf '%s\n' 'steamclienttermux checks: PASS'
