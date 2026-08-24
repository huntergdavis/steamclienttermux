#!/usr/bin/env python3

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
RUNNER = ROOT / "scripts/run-tombraider-native-benchmark.py"
WRAPPER = (
    ROOT
    / "scripts/test-tomb-raider-direct-dxvk-1103-x32-720p-normal-single-40c-ceiling.sh"
)
WRAPPER_1080P = (
    ROOT
    / "scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-normal-single-40c-ceiling.sh"
)


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatch", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_dispatcher()
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        base.chmod(0o700)
        candidate = base / "candidates" / "fixture-dxvk-x32" / "x32"
        candidate.mkdir(parents=True, mode=0o700)
        candidate.parent.chmod(0o700)
        candidate.parent.parent.chmod(0o700)
        fixtures = {
            "d3d10core.dll": b"arm64ec-d3d10-fixture",
            "d3d11.dll": b"arm64ec-d3d11-fixture",
            "d3d9.dll": b"x32-d3d9-fixture",
            "dxgi.dll": b"x32-dxgi-fixture",
        }
        module.DXVK_X32_VARIANTS = {
            "dxvk-1.10.3-x32": (
                "fixture-dxvk-x32",
                {
                    name: (len(data), hashlib.sha256(data).hexdigest())
                    for name, data in fixtures.items()
                },
            )
        }
        for name, data in fixtures.items():
            path = candidate / name
            path.write_bytes(data)
            path.chmod(0o600)
        bundled = {"WINEDLLPATH": "/tmp/smuggled"}
        with mock.patch.dict(os.environ, {}, clear=True):
            module.apply_dxvk_variant(bundled, base, "tombraider-benchmark")
        assert bundled == {}

        selected = {}
        with mock.patch.dict(
            os.environ,
            {"STEAM_ARM64_DIRECT_DXVK_VARIANT": "dxvk-1.10.3-x32"},
            clear=True,
        ):
            module.apply_dxvk_variant(selected, base, "tombraider-benchmark")
        assert selected["STEAMCLIENTTERMUX_DXVK_VARIANT"] == (
            "dxvk-1.10.3-x32"
        )
        assert selected["DXVK_LOG_LEVEL"] == "info"
        dxvk_log_path = Path(selected["DXVK_LOG_PATH"])
        assert dxvk_log_path.parent == base / "logs"
        assert dxvk_log_path.is_dir()

        for mode, expected in (
            ("proton-cmd", "valid only for Tomb Raider"),
            ("invalid", "must be bundled"),
        ):
            environment = {
                "STEAM_ARM64_DIRECT_DXVK_VARIANT": (
                    "dxvk-1.10.3-x32" if mode == "proton-cmd" else mode
                )
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                try:
                    module.apply_dxvk_variant({}, base, mode)
                except module.DispatchError as error:
                    assert expected in str(error)
                else:
                    raise AssertionError("invalid DXVK variant mode was accepted")

        (candidate / "dxgi.dll").write_bytes(b"corrupt")
        with mock.patch.dict(
            os.environ,
            {"STEAM_ARM64_DIRECT_DXVK_VARIANT": "dxvk-1.10.3-x32"},
            clear=True,
        ):
            try:
                module.apply_dxvk_variant({}, base, "tombraider")
            except module.DispatchError as error:
                assert "failed validation" in str(error)
            else:
                raise AssertionError("corrupt DXVK candidate was accepted")

    sanitized = module.request_environment(
        {
            "environment": [
                "WINEDLLPATH=/tmp/smuggled",
                "STEAM_ARM64_DIRECT_DXVK_VARIANT=dxvk-1.10.3-x32",
                "TOMB_RAIDER_DXVK_VARIANT=dxvk-1.10.3-x32",
                "KEEP_ME=yes",
            ]
        }
    )
    assert sanitized == {"KEEP_ME": "yes"}

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "dxvk_variant=${TOMB_RAIDER_DXVK_VARIANT:-bundled}" in launcher
    assert '"STEAM_ARM64_DIRECT_DXVK_VARIANT=$dxvk_variant"' in launcher
    assert "manage-tombraider-dxvk-overlay.py" in launcher
    assert 'activate --base "$base"' in launcher
    assert 'restore --base "$base"' in launcher
    assert launcher.count("-u WINEDLLPATH") == 2
    rejected = subprocess.run(
        ["bash", str(LAUNCHER)],
        env={**os.environ, "TOMB_RAIDER_DXVK_VARIANT": "invalid"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "must be bundled" in rejected.stderr

    runner = RUNNER.read_text(encoding="utf-8")
    assert '"--dxvk-variant"' in runner
    assert '"dxvk_variant": arguments.dxvk_variant' in runner
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "--game-profile 720p-normal" in wrapper
    assert "--dxvk-variant dxvk-1.10.3-x32" in wrapper
    assert "manage-tombraider-dxvk-overlay.py" not in wrapper
    assert "--warmups 0" in wrapper and "--runs 1" in wrapper
    installer = (ROOT / "scripts/install-project-files.sh").read_text(
        encoding="utf-8"
    )
    assert WRAPPER.name in installer

    wrapper_1080p = WRAPPER_1080P.read_text(encoding="utf-8")
    assert "--game-profile 1080p-normal" in wrapper_1080p
    assert "--dxvk-variant dxvk-2.4.1-x32" in wrapper_1080p
    assert "--warmups 0" in wrapper_1080p and "--runs 1" in wrapper_1080p
    assert WRAPPER_1080P.name in installer

    assert selected["WINEDLLOVERRIDES"] == "d3d9,d3d10core,d3d11,dxgi=n"

    print("Tomb Raider contained DXVK variant tests: PASS")


if __name__ == "__main__":
    main()
