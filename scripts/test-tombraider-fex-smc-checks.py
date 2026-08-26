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
    ROOT / "scripts/test-tomb-raider-direct-fex-smc-none-excluded-40c-ceiling.sh"
)
SERIES_WRAPPER = (
    ROOT / "scripts/test-tomb-raider-direct-fex-smc-none-40c-ceiling.sh"
)


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatch", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_dispatcher()

    control = {"FEX_SMC_CHECKS": "legacy", "FEX_SMCCHECKS": "none"}
    with mock.patch.dict(os.environ, {}, clear=True):
        module.apply_fex_smc_checks(control, "tombraider-benchmark")
    assert control == {"FEX_SMCCHECKS": "mtrack"}

    candidate = {"FEX_SMC_CHECKS": "legacy", "FEX_SMCCHECKS": "mtrack"}
    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_FEX_SMC_CHECKS": "none"},
        clear=True,
    ):
        module.apply_fex_smc_checks(candidate, "tombraider-benchmark")
    assert candidate == {"FEX_SMCCHECKS": "none"}

    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_FEX_SMC_CHECKS": "invalid"},
        clear=True,
    ):
        try:
            module.apply_fex_smc_checks({}, "tombraider-benchmark")
        except module.DispatchError as error:
            assert "must be mtrack or none" in str(error)
        else:
            raise AssertionError("invalid FEX SMC selector was accepted")

    with mock.patch.dict(
        os.environ,
        {"STEAM_ARM64_DIRECT_FEX_SMC_CHECKS": "none"},
        clear=True,
    ):
        try:
            module.apply_fex_smc_checks({}, "proton-cmd")
        except module.DispatchError as error:
            assert "valid only for Tomb Raider" in str(error)
        else:
            raise AssertionError("non-game FEX SMC override was accepted")

    sanitized = module.request_environment(
        {
            "environment": [
                "FEX_SMC_CHECKS=legacy",
                "FEX_SMCCHECKS=none",
                "STEAM_ARM64_DIRECT_FEX_SMC_CHECKS=none",
                "TOMB_RAIDER_FEX_SMC_CHECKS=none",
                "KEEP_ME=yes",
            ]
        }
    )
    assert sanitized == {"KEEP_ME": "yes"}

    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    assert (
        "fex_smc_checks=${TOMB_RAIDER_FEX_SMC_CHECKS:-mtrack}"
        in launcher_source
    )
    assert (
        '"STEAM_ARM64_DIRECT_FEX_SMC_CHECKS=$fex_smc_checks"'
        in launcher_source
    )
    assert launcher_source.count("-u FEX_SMC_CHECKS") == 2
    assert launcher_source.count("-u FEX_SMCCHECKS") == 2
    assert launcher_source.count("-u TOMB_RAIDER_FEX_SMC_CHECKS") == 2

    rejected = subprocess.run(
        ["bash", str(LAUNCHER)],
        env={**os.environ, "TOMB_RAIDER_FEX_SMC_CHECKS": "invalid"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "TOMB_RAIDER_FEX_SMC_CHECKS must be mtrack or none" in rejected.stderr

    runner_source = RUNNER.read_text(encoding="utf-8")
    assert '"--fex-smc-checks"' in runner_source
    assert '"fex_smc_checks": arguments.fex_smc_checks' in runner_source
    excluded_source = EXCLUDED_WRAPPER.read_text(encoding="utf-8")
    assert "--fex-smc-checks none" in excluded_source
    assert "--warmups 0" in excluded_source
    assert "--runs 1" in excluded_source
    series_source = SERIES_WRAPPER.read_text(encoding="utf-8")
    assert "--fex-smc-checks none" in series_source
    assert "--start-temperature-ceiling-c 40" in series_source

    installer = (ROOT / "scripts/install-project-files.sh").read_text(
        encoding="utf-8"
    )
    assert EXCLUDED_WRAPPER.name in installer
    assert SERIES_WRAPPER.name in installer

    print("Tomb Raider FEX SMC-check selector tests: PASS")


if __name__ == "__main__":
    main()
