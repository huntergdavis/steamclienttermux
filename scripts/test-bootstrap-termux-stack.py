#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap-termux-stack.sh"
RELEASE = ROOT / "scripts/build-release-archive.py"
PRODUCT_RUNTIME_USERS = (
    ROOT / "bin/steam-arm-native",
    ROOT / "bin/steam-arm64-forward-dispatch",
    ROOT / "scripts/install-project-files.sh",
    ROOT / "scripts/pressure-vessel-direct-dispatch.py",
)


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/data/data/com.termux/files/usr/bin/bash\n")
    assert "set -euo pipefail" in source
    assert "${PREFIX:-} == /data/data/com.termux/files/usr" in source
    assert "getprop ro.product.cpu.abi" in source
    assert '"$PREFIX/bin/pkg" install -y python' in source
    assert 'dependencies --install --yes --base "$base"' in source
    assert 'python3 "$setup" --lock "$lock" prepare --base "$base"' in source
    assert 'python3 "$turnip_installer" --lock "$turnip_lock" install --base "$base"' in source
    assert 'python3 "$tgcompat_installer" --lock "$tgcompat_lock" --base "$base"' in source
    assert 'python3 "$glibc_installer" --lock "$glibc_lock"' in source
    assert '--package "$glibc_package" --base "$base"' in source
    assert 'exec python3 "$proot_installer" --lock "$proot_lock"' in source
    assert '--builder "$proot_builder" --base "$base"' in source
    assert "curl |" not in source and "wget |" not in source
    for path in PRODUCT_RUNTIME_USERS:
        consumer = path.read_text(encoding="utf-8")
        assert "workspace/termux-glibc-compat" not in consumer
        assert "tgcompat/current" in consumer
    release = RELEASE.read_text(encoding="utf-8")
    assert '"scripts/bootstrap-termux-stack.sh"' in release or '"scripts/"' in release
    print("Termux one-command bootstrap contract: PASS")


if __name__ == "__main__":
    main()
