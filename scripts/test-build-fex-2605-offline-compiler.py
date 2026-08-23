#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-fex-2605-offline-compiler.sh"
PATCH = ROOT / "patches/fex-2605-arm64ec-offline-compiler-compat.patch"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    patch = PATCH.read_text(encoding="utf-8")

    assert source.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in source
    assert "a04b0241c2fe3911729842205cd8643981108aad" in source
    assert "329e561effcdc751f860d289ffc13aa5e1a66df1" in source
    assert "6d1cd6790071884dce058e223c3cacf3a0db43f7" in source
    assert "6cb73adfd509597e58918832c1a42dad56c62538" in source
    assert "8dd8c34fc051a50c2fae86015f35057f8aae93fe1e19b34537ef1269a8b4c772" in source
    assert "-DOVERRIDE_HASH=\"$fex_commit\"" in source
    assert "-DOVERRIDE_VERSION=FEX-2605" in source
    assert "git -C \"$source\" apply --check \"$compat_patch\"" in source
    assert "output already exists" in source
    assert "FEX_BUILD_JOBS:-2" in source
    assert "SOURCE_DATE_EPOCH" in source

    assert "LdrProcessRelocationBlock" in patch
    assert "CPUFeatures::FetchHostFeatures(IsWine)" in patch
    assert "HostTypeEnum" not in patch
    assert patch.count("AddVirtualPage") == 1
    print("PASS: FEX-2605 ARM64EC offline-compiler build stays pinned and fail-closed")


if __name__ == "__main__":
    main()
