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
EXCLUDED_WRAPPER = (
    ROOT
    / "scripts/test-tomb-raider-direct-dxvk-relaxed-graphics-excluded-40c-ceiling.sh"
)
SERIES_WRAPPER = (
    ROOT / "scripts/test-tomb-raider-direct-dxvk-relaxed-graphics-40c-ceiling.sh"
)


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatch", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_dispatcher()

    disabled = {
        "DXVK_CONFIG": "smuggled",
        "DXVK_CONFIG_FILE": "/tmp/smuggled",
    }
    with mock.patch.dict(os.environ, {}, clear=True):
        module.apply_dxvk_relaxed_graphics_barriers(
            disabled, "tombraider-benchmark"
        )
    assert disabled == {}

    enabled = {}
    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS": "on"},
        clear=True,
    ):
        module.apply_dxvk_relaxed_graphics_barriers(
            enabled, "tombraider-benchmark"
        )
    assert enabled == {"DXVK_CONFIG": "d3d11.relaxedGraphicsBarriers = True"}

    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS": "invalid"},
        clear=True,
    ):
        try:
            module.apply_dxvk_relaxed_graphics_barriers(
                {}, "tombraider-benchmark"
            )
        except module.DispatchError as error:
            assert "must be off or on" in str(error)
        else:
            raise AssertionError("invalid DXVK barrier selector was accepted")

    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS": "on"},
        clear=True,
    ):
        try:
            module.apply_dxvk_relaxed_graphics_barriers({}, "proton-cmd")
        except module.DispatchError as error:
            assert "valid only for Tomb Raider" in str(error)
        else:
            raise AssertionError("non-game DXVK barrier mode was accepted")

    sanitized = module.request_environment(
        {
            "environment": [
                "DXVK_CONFIG=d3d11.relaxedBarriers = True",
                "DXVK_CONFIG_FILE=/tmp/smuggled",
                "STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS=on",
                "TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS=on",
                "KEEP_ME=yes",
            ]
        }
    )
    assert sanitized == {"KEEP_ME": "yes"}

    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    assert (
        "dxvk_relaxed_graphics_barriers="
        "${TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS:-off}"
        in launcher_source
    )
    assert (
        '"STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS='
        '$dxvk_relaxed_graphics_barriers"'
        in launcher_source
    )
    assert launcher_source.count("-u DXVK_CONFIG -u DXVK_CONFIG_FILE") == 2
    assert (
        launcher_source.count(
            "-u TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS"
        )
        == 2
    )

    rejected = subprocess.run(
        ["bash", str(LAUNCHER)],
        env={
            **os.environ,
            "TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS": "invalid",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert (
        "TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS must be off or on"
        in rejected.stderr
    )

    runner_source = RUNNER.read_text(encoding="utf-8")
    assert '"--dxvk-relaxed-graphics-barriers"' in runner_source
    assert '"dxvk_relaxed_graphics_barriers": (' in runner_source
    excluded_source = EXCLUDED_WRAPPER.read_text(encoding="utf-8")
    assert "--dxvk-relaxed-graphics-barriers on" in excluded_source
    assert "--warmups 0" in excluded_source
    assert "--runs 1" in excluded_source
    series_source = SERIES_WRAPPER.read_text(encoding="utf-8")
    assert "--dxvk-relaxed-graphics-barriers on" in series_source
    assert "--start-temperature-ceiling-c 40" in series_source
    installer = (ROOT / "scripts/install-project-files.sh").read_text(
        encoding="utf-8"
    )
    assert EXCLUDED_WRAPPER.name in installer
    assert SERIES_WRAPPER.name in installer

    print("Tomb Raider DXVK relaxed-graphics-barrier tests: PASS")


if __name__ == "__main__":
    main()
