#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/steam-arm64-runtime-toolmanifest.vdf"
INSTALLER = ROOT / "scripts/install-project-files.sh"


def main() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    assert text.count('"version" "2"') == 1
    assert text.count('"commandline" "/_v2-entry-point --verb=%verb% --"') == 1
    assert text.count('"compatmanager_layer_name" "container-runtime"') == 1
    assert text.count('"use_tool_subprocess_reaper" "1"') == 1
    assert "@" not in text

    installer = INSTALLER.read_text(encoding="utf-8")
    assert installer.count(
        '"$repo_root/config/steam-arm64-runtime-toolmanifest.vdf"'
    ) == 1
    assert installer.count(
        '"$base/runtime/SteamLinuxRuntime_4-arm64-native/toolmanifest.vdf"'
    ) == 1
    print("native Runtime 4 toolmanifest tests: PASS")


if __name__ == "__main__":
    main()
