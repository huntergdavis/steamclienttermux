#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-fex-2605-offline-compiler.sh"
PATCH = ROOT / "patches/fex-2605-native-arm64-offline-compiler-compat.patch"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    patch = PATCH.read_text(encoding="utf-8")

    assert source.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in source
    assert "a04b0241c2fe3911729842205cd8643981108aad" in source
    assert "329e561effcdc751f860d289ffc13aa5e1a66df1" in source
    assert "6d1cd6790071884dce058e223c3cacf3a0db43f7" in source
    assert "6cb73adfd509597e58918832c1a42dad56c62538" in source
    assert "c0251dc8becb749de731b65a3e228b6d42dc7cbe" in source
    assert "5bde4d875a551f4e1bc3ce8d5fe67b6341cda41f" in source
    assert "d3d735370fd67692bec850ad6df935b9f8bc959c" in source
    assert "8dd8c34fc051a50c2fae86015f35057f8aae93fe1e19b34537ef1269a8b4c772" in source
    assert "-DOVERRIDE_HASH=\"$fex_commit\"" in source
    assert "-DOVERRIDE_VERSION=FEX-2605" in source
    assert "-DMINGW_TRIPLE=aarch64-w64-mingw32" in source
    assert "-DFEX_OFFLINE_COMPILER_ARM64EC_TARGET=ON" in source
    assert "-DCMAKE_EXE_LINKER_FLAGS=-Wl,--no-insert-timestamp" in source
    assert "git -C \"$source\" apply --check \"$compat_patch\"" in source
    assert "output already exists" in source
    assert "FEX_BUILD_JOBS:-2" in source
    assert "SOURCE_DATE_EPOCH" in source
    assert "libc++.dll libunwind.dll" in source
    assert "aarch64-w64-mingw32/bin/$runtime_dll" in source

    assert "LdrProcessRelocationBlock" in patch
    assert "FEX_OFFLINE_COMPILER_ARM64EC_TARGET" in patch
    assert "FetchHostFeatures" not in patch
    assert patch.count("AddVirtualPage") == 1
    print("PASS: FEX-2605 native-ARM64 compiler targets ARM64EC codegen fail-closed")


if __name__ == "__main__":
    main()
