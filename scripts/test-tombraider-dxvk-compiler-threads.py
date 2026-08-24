#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import subprocess
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
RUNNER = ROOT / "scripts/run-tombraider-native-benchmark.py"
WRAPPER = (
    ROOT
    / "scripts/test-tomb-raider-direct-dxvk-241-compiler4-720p-normal-single-40c-ceiling.sh"
)
WRAPPER_1080P = (
    ROOT
    / "scripts/test-tomb-raider-direct-dxvk-241-compiler4-1080p-normal-single-40c-ceiling.sh"
)


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatch", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_rejected(module, selector: str, mode: str = "tombraider-benchmark") -> None:
    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS": selector},
        clear=True,
    ):
        try:
            module.apply_dxvk_compiler_threads({}, mode)
        except module.DispatchError:
            return
    raise AssertionError(f"invalid DXVK compiler selector accepted: {selector!r}")


def main() -> None:
    module = load_dispatcher()

    automatic = {
        "STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS": "smuggled",
    }
    with mock.patch.dict(os.environ, {}, clear=True):
        module.apply_dxvk_compiler_threads(automatic, "tombraider-benchmark")
    assert automatic == {}

    selected = {}
    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS": "4"},
        clear=True,
    ):
        module.apply_dxvk_compiler_threads(selected, "tombraider-benchmark")
    assert selected == {
        "DXVK_CONFIG": "dxvk.numCompilerThreads = 4",
        "STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS": "4",
    }

    composed = {"DXVK_CONFIG": "d3d11.relaxedGraphicsBarriers = True"}
    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS": "4"},
        clear=True,
    ):
        module.apply_dxvk_compiler_threads(composed, "tombraider")
    assert composed["DXVK_CONFIG"] == (
        "d3d11.relaxedGraphicsBarriers = True; dxvk.numCompilerThreads = 4"
    )

    for invalid in ("-1", "17", "04", "four", "٤"):
        expect_rejected(module, invalid)
    expect_rejected(module, "4", "proton-cmd")

    sanitized = module.request_environment(
        {
            "environment": [
                "DXVK_CONFIG=dxvk.numCompilerThreads = 16",
                "STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS=16",
                "STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS=16",
                "STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS=16",
                "TOMB_RAIDER_DXVK_COMPILER_THREADS=16",
                "KEEP_ME=yes",
            ]
        }
    )
    assert sanitized == {"KEEP_ME": "yes"}

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert (
        "dxvk_compiler_threads=${TOMB_RAIDER_DXVK_COMPILER_THREADS:-0}"
        in launcher
    )
    assert (
        '"STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS=$dxvk_compiler_threads"'
        in launcher
    )
    assert launcher.count("-u TOMB_RAIDER_DXVK_COMPILER_THREADS") == 2
    assert launcher.count("-u STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS") == 2

    rejected = subprocess.run(
        ["bash", str(LAUNCHER)],
        env={**os.environ, "TOMB_RAIDER_DXVK_COMPILER_THREADS": "17"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "must be 0 through 16" in rejected.stderr

    runner = RUNNER.read_text(encoding="utf-8")
    assert '"--dxvk-compiler-threads"' in runner
    assert '"dxvk_compiler_threads": arguments.dxvk_compiler_threads' in runner
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "Starting Tomb Raider BVB probe:" in wrapper
    assert "--game-profile 720p-normal" in wrapper
    assert "--dxvk-variant dxvk-2.4.1-x32" in wrapper
    assert "--dxvk-compiler-threads 4" in wrapper
    assert "--warmups 0" in wrapper and "--runs 1" in wrapper

    bwrap = (ROOT / "bin/steam-arm64-native-bwrap").read_text(encoding="utf-8")
    assert "STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS" in bwrap
    installer = (ROOT / "scripts/install-project-files.sh").read_text(
        encoding="utf-8"
    )
    assert WRAPPER.name in installer

    wrapper_1080p = WRAPPER_1080P.read_text(encoding="utf-8")
    assert "Starting Tomb Raider BVB probe:" in wrapper_1080p
    assert "--game-profile 1080p-normal" in wrapper_1080p
    assert "--dxvk-variant dxvk-2.4.1-x32" in wrapper_1080p
    assert "--dxvk-compiler-threads 4" in wrapper_1080p
    assert "--warmups 0" in wrapper_1080p and "--runs 1" in wrapper_1080p
    assert WRAPPER_1080P.name in installer

    print("Tomb Raider DXVK compiler-thread selector tests: PASS")


if __name__ == "__main__":
    main()
