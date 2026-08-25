#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap-termux-stack.sh"
RELEASE = ROOT / "scripts/build-release-archive.py"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/data/data/com.termux/files/usr/bin/bash\n")
    assert "set -euo pipefail" in source
    assert "${PREFIX:-} == /data/data/com.termux/files/usr" in source
    assert "getprop ro.product.cpu.abi" in source
    assert '"$PREFIX/bin/pkg" install -y python' in source
    assert 'dependencies --install --yes --base "$base"' in source
    assert 'exec python3 "$setup" --lock "$lock" prepare --base "$base"' in source
    assert "curl |" not in source and "wget |" not in source
    release = RELEASE.read_text(encoding="utf-8")
    assert '"scripts/bootstrap-termux-stack.sh"' in release or '"scripts/"' in release
    print("Termux one-command bootstrap contract: PASS")


if __name__ == "__main__":
    main()
