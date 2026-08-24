#!/usr/bin/env python3

import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
RUNNER = ROOT / "scripts/run-tombraider-native-benchmark.py"
WRAPPER = ROOT / "scripts/test-tomb-raider-direct-fex-code-cache-40c-ceiling.sh"
PROFILE_WRAPPER = (
    ROOT
    / "scripts/test-tomb-raider-direct-fex-max-buffer-profile-excluded-40c-ceiling.sh"
)
NORMAL_720P_WRAPPER = (
    ROOT
    / "scripts/test-tomb-raider-direct-fex-offline-compiled-720p-normal-single-40c-ceiling.sh"
)


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
            "FEX_APP_CACHE_LOCATION": f"{cache}/",
        }
        metadata = cache.lstat()
        assert stat.S_ISDIR(metadata.st_mode)
        assert not cache.is_symlink()
        assert metadata.st_uid == os.geteuid()
        assert metadata.st_mode & 0o077 == 0

        compiled = (
            base
            / "cache/fex-code-cache/tombraider-203160-offline-7efb8f8e"
        )
        compiled.mkdir(mode=0o700, parents=True)
        (compiled / "codemap/new").mkdir(mode=0o700, parents=True)
        (compiled / "codemap/ready").mkdir(mode=0o700)
        (compiled / "cache").mkdir(mode=0o700)
        ready = compiled / "codemap/ready/tombraider.exe-4cb3720654f045ff"
        ready.write_bytes(b"ready")
        ready.chmod(0o600)
        cache_file = (
            compiled
            / "cache/tombraider.exe-4cb3720654f045ff-0000000000000000"
        )
        cache_file.write_bytes(
            struct.pack(
                "<4sI20sI",
                b"FXCC",
                1,
                bytes.fromhex("a04b0241c2fe3911729842205cd8643981108aad"),
                7,
            )
            + b"code"
        )
        cache_file.chmod(0o600)
        result = compiled / "result.json"
        result.write_text(
            json.dumps(
                {
                    "status": "verified",
                    "fex_commit": "a04b0241c2fe3911729842205cd8643981108aad",
                    "compiler_sha256": module.FEX_2605_OFFLINE_COMPILER_SHA256,
                }
            ),
            encoding="utf-8",
        )
        result.chmod(0o600)
        compiled_environment = {}
        with mock.patch.dict(
            os.environ,
            {"STEAM_ARM64_DIRECT_FEX_CODE_CACHE": "compiled"},
            clear=True,
        ):
            module.apply_fex_code_cache(
                compiled_environment, base, "tombraider-benchmark"
            )
        assert compiled_environment == {
            "FEX_ENABLECODECACHINGWIP": "1",
            "FEX_APP_CACHE_LOCATION": f"{compiled}/",
        }

        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_FEX_CODE_CACHE": "invalid"}, clear=True
        ):
            try:
                module.apply_fex_code_cache({}, base, "tombraider-benchmark")
            except module.DispatchError as error:
                assert "must be off, on, or compiled" in str(error)
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
    assert "fex_code_cache=${TOMB_RAIDER_FEX_CODE_CACHE:-compiled}" in launcher_source
    assert "$fex_code_cache == compiled" in launcher_source
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
    assert "TOMB_RAIDER_FEX_CODE_CACHE must be off, on, or compiled" in rejected.stderr

    runner_source = RUNNER.read_text(encoding="utf-8")
    assert '"--fex-code-cache"' in runner_source
    assert 'choices=("off", "on", "compiled")' in runner_source
    assert '"fex_code_cache": arguments.fex_code_cache' in runner_source
    wrapper_source = WRAPPER.read_text(encoding="utf-8")
    assert "TOMB_RAIDER_BENCHMARK_COMMAND" in wrapper_source
    assert "compat-bin/run-tombraider-native-benchmark.py" not in wrapper_source
    assert "--fex-code-cache on" in wrapper_source
    assert "--start-temperature-ceiling-c 40" in wrapper_source

    profile_wrapper_source = PROFILE_WRAPPER.read_text(encoding="utf-8")
    assert "--fex-code-cache on" in profile_wrapper_source
    assert "--startup-topology full" in profile_wrapper_source
    assert "--warmups 0" in profile_wrapper_source
    assert "--runs 1" in profile_wrapper_source
    assert "--start-temperature-ceiling-c 40" in profile_wrapper_source
    assert (
        "test-tomb-raider-direct-fex-max-buffer-profile-excluded-40c-ceiling.sh"
        in (ROOT / "scripts/install-project-files.sh").read_text(encoding="utf-8")
    )
    normal_wrapper = NORMAL_720P_WRAPPER.read_text(encoding="utf-8")
    assert normal_wrapper.startswith("#!/data/data/com.termux/files/usr/bin/bash\n")
    assert "TOMB_RAIDER_BENCHMARK_PYTHON" in normal_wrapper
    assert 'benchmark_python=$(readlink -f -- "$benchmark_python")' in normal_wrapper
    assert 'exec "$benchmark_python" "$benchmark_runner"' in normal_wrapper
    assert "--game-profile 720p-normal" in normal_wrapper
    assert "--fex-code-cache compiled" in normal_wrapper
    assert "--startup-topology full" in normal_wrapper
    assert "--start-temperature-ceiling-c 40" in normal_wrapper
    assert "--warmups 0" in normal_wrapper and "--runs 1" in normal_wrapper
    assert "Starting Tomb Raider BVB probe:" in normal_wrapper
    assert NORMAL_720P_WRAPPER.name in (
        ROOT / "scripts/install-project-files.sh"
    ).read_text(encoding="utf-8")

    print("Tomb Raider final-game FEX code-cache tests: PASS")


if __name__ == "__main__":
    main()
