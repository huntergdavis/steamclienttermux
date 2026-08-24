#!/usr/bin/env python3

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare-dxvk-state-cache.py"
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatcher", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="dxvk-state-cache.") as text:
        base = Path(text) / "base"
        base.mkdir(mode=0o700)
        source = (
            base
            / "removable-library/steamapps/compatdata/203160/pfx/drive_c/users/steamuser/AppData/Local/dxvk"
        )
        source.mkdir(parents=True)
        source.chmod(0o755)
        cache = source / "0123456789abcdef.dxvk.bin"
        cache.write_bytes(b"dxvk-cache" * 1024)
        cache.chmod(0o600)
        command = [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--base",
            str(base),
            "--appid",
            "203160",
        ]
        first = subprocess.run(command, text=True, capture_output=True, check=False)
        assert first.returncode == 0, first.stderr
        destination = base / "cache/dxvk-state/203160"
        assert "DXVK_STATE_CACHE_SEEDED=" in first.stdout
        assert (destination / cache.name).read_bytes() == cache.read_bytes()
        manifest = json.loads((destination / "seed.json").read_text())
        assert manifest["appid"] == 203160
        second = subprocess.run(command, text=True, capture_output=True, check=False)
        assert second.returncode == 0, second.stderr
        assert "DXVK_STATE_CACHE_REUSED=" in second.stdout
        (destination / "unexpected").write_bytes(b"bad")
        rejected = subprocess.run(command, text=True, capture_output=True, check=False)
        assert rejected.returncode != 0
        assert "unexpected entry" in rejected.stderr

    dispatcher = load_dispatcher()
    with tempfile.TemporaryDirectory(prefix="dxvk-dispatch.") as text:
        base = Path(text)
        root = base / "cache/dxvk-state/203160"
        root.mkdir(parents=True)
        root.chmod(0o700)
        payload = root / "0123456789abcdef.dxvk.bin"
        payload.write_bytes(b"state")
        payload.chmod(0o600)
        (root / "seed.json").write_text("{}\n", encoding="utf-8")
        (root / "seed.json").chmod(0o600)
        (root / ".lock").write_bytes(b"")
        (root / ".lock").chmod(0o600)
        environment = {"DXVK_STATE_CACHE_PATH": "/smuggled"}
        old = os.environ.get("STEAM_ARM64_DIRECT_DXVK_STATE_CACHE")
        try:
            os.environ["STEAM_ARM64_DIRECT_DXVK_STATE_CACHE"] = "internal"
            dispatcher.apply_dxvk_state_cache(environment, base, "tombraider")
            assert environment["DXVK_STATE_CACHE_PATH"] == str(root)
            os.environ["STEAM_ARM64_DIRECT_DXVK_STATE_CACHE"] = "external"
            dispatcher.apply_dxvk_state_cache(environment, base, "tombraider")
            assert "DXVK_STATE_CACHE_PATH" not in environment
        finally:
            if old is None:
                os.environ.pop("STEAM_ARM64_DIRECT_DXVK_STATE_CACHE", None)
            else:
                os.environ["STEAM_ARM64_DIRECT_DXVK_STATE_CACHE"] = old

    launcher = (ROOT / "scripts/start-tombraider-direct-dispatch.sh").read_text()
    assert "TOMB_RAIDER_DXVK_STATE_CACHE" in launcher
    assert "prepare-dxvk-state-cache.py" in launcher
    installer = (ROOT / "scripts/install-project-files.sh").read_text()
    assert "prepare-dxvk-state-cache.py" in installer
    print("DXVK internal state-cache tests: PASS")


if __name__ == "__main__":
    main()
