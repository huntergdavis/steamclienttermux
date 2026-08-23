#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
RUNNER = ROOT / "scripts/run-tombraider-native-benchmark.py"
WRAPPER = ROOT / "scripts/test-tomb-raider-direct-fex-code-cache-40c-ceiling.sh"


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("direct_dispatch", DISPATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_dispatcher()
    with tempfile.TemporaryDirectory(prefix="fex-code-cache.") as directory:
        base = Path(directory) / "steam-arm64"
        base.mkdir(mode=0o700)

        disabled = {
            "FEX_ENABLECODECACHINGWIP": "smuggled",
            "FEX_APP_CACHE_LOCATION": "/tmp/smuggled",
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            module.apply_fex_code_cache(disabled, base, "tombraider-benchmark")
        assert "FEX_ENABLECODECACHINGWIP" not in disabled
        assert "FEX_APP_CACHE_LOCATION" not in disabled
        assert not (base / "cache").exists()

        enabled = {}
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_FEX_CODE_CACHE": "on"}, clear=True
        ):
            module.apply_fex_code_cache(enabled, base, "tombraider-benchmark")
        cache = base / "cache/fex-code-cache/tombraider-203160"
        assert enabled == {
            "FEX_ENABLECODECACHINGWIP": "1",
            "FEX_APP_CACHE_LOCATION": str(cache),
        }
        metadata = cache.lstat()
        assert stat.S_ISDIR(metadata.st_mode)
        assert not cache.is_symlink()
        assert metadata.st_uid == os.geteuid()
        assert metadata.st_mode & 0o077 == 0

        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_FEX_CODE_CACHE": "invalid"}, clear=True
        ):
            try:
                module.apply_fex_code_cache({}, base, "tombraider-benchmark")
            except module.DispatchError as error:
                assert "must be off or on" in str(error)
            else:
                raise AssertionError("invalid FEX code-cache selector was accepted")

        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_FEX_CODE_CACHE": "on"}, clear=True
        ):
            try:
                module.apply_fex_code_cache({}, base, "proton-cmd")
            except module.DispatchError as error:
                assert "valid only for Tomb Raider" in str(error)
            else:
                raise AssertionError("non-game FEX code cache was accepted")

        sanitized = module.request_environment(
            {
                "environment": [
                    "FEX_ENABLECODECACHINGWIP=smuggled",
                    "FEX_APP_CACHE_LOCATION=/tmp/smuggled",
                    "STEAM_ARM64_DIRECT_FEX_CODE_CACHE=on",
                    "TOMB_RAIDER_FEX_CODE_CACHE=on",
                    "KEEP_ME=yes",
                ]
            }
        )
        assert sanitized == {"KEEP_ME": "yes"}

    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    assert "fex_code_cache=${TOMB_RAIDER_FEX_CODE_CACHE:-off}" in launcher_source
    assert '"STEAM_ARM64_DIRECT_FEX_CODE_CACHE=$fex_code_cache"' in launcher_source
    assert launcher_source.count("-u FEX_ENABLECODECACHINGWIP") == 2
    assert launcher_source.count("-u FEX_APP_CACHE_LOCATION") == 2
    assert launcher_source.count("-u TOMB_RAIDER_FEX_CODE_CACHE") == 2
    assert "-u STEAM_ARM64_DIRECT_FEX_CODE_CACHE" in launcher_source

    rejected = subprocess.run(
        ["bash", str(LAUNCHER)],
        env={**os.environ, "TOMB_RAIDER_FEX_CODE_CACHE": "invalid"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "TOMB_RAIDER_FEX_CODE_CACHE must be off or on" in rejected.stderr

    runner_source = RUNNER.read_text(encoding="utf-8")
    assert '"--fex-code-cache"' in runner_source
    assert '"fex_code_cache": arguments.fex_code_cache' in runner_source
    wrapper_source = WRAPPER.read_text(encoding="utf-8")
    assert "TOMB_RAIDER_BENCHMARK_COMMAND" in wrapper_source
    assert "compat-bin/run-tombraider-native-benchmark.py" not in wrapper_source
    assert "--fex-code-cache on" in wrapper_source
    assert "--start-temperature-ceiling-c 40" in wrapper_source

    print("Tomb Raider final-game FEX code-cache tests: PASS")


if __name__ == "__main__":
    main()
