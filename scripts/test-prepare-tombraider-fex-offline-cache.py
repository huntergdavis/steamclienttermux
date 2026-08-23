#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare-tombraider-fex-offline-cache.py"
LAUNCHER = ROOT / "scripts/start-tombraider-fex-offline-compile.sh"
BENCHMARK = (
    ROOT
    / "scripts/test-tomb-raider-direct-fex-offline-compiled-40c-ceiling.sh"
)
SINGLE_BENCHMARK = (
    ROOT
    / "scripts/test-tomb-raider-direct-fex-offline-compiled-single-40c-ceiling.sh"
)
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
FEX_COMMIT = "a04b0241c2fe3911729842205cd8643981108aad"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    specification = importlib.util.spec_from_file_location(
        "fex_offline_dispatcher", DISPATCHER
    )
    assert specification and specification.loader
    dispatcher = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(dispatcher)
    with tempfile.TemporaryDirectory(prefix="fex-offline-cache.") as directory:
        base = Path(directory) / "steam-arm64"
        source = base / "cache/fex-code-cache/tombraider-203160/codemap/new"
        compiler = (
            base
            / "compat-bin/fex-2605-offline-compiler-native-arm64/FEXOfflineCompiler.exe"
        )
        base.mkdir(mode=0o700)
        source.mkdir(mode=0o700, parents=True)
        compiler.parent.mkdir(mode=0o700, parents=True)
        compiler.write_bytes(b"MZ" + b"compiler-fixture" * 131072)
        compiler.chmod(0o700)
        runtime_hashes = {}
        for name in ("libc++.dll", "libunwind.dll"):
            runtime = compiler.parent / name
            runtime.write_bytes(b"MZ" + name.encode() * 8192)
            runtime.chmod(0o700)
            runtime_hashes[name] = sha256(runtime)
        compiler_sha = sha256(compiler)
        original_hashes = {}
        for index in range(2):
            path = source / f"tombraider.exe-4cb3720654f045ff.{1000 + index}.bin"
            path.write_bytes((f"map-{index}".encode()) * 100)
            path.chmod(0o600)
            original_hashes[path.name] = sha256(path)

        prepare = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "prepare",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert prepare.returncode == 0, prepare.stderr
        candidate = (
            base
            / "cache/fex-code-cache/tombraider-203160-offline-7efb8f8e"
        )
        manifest = json.loads((candidate / "prepare.json").read_text())
        assert manifest["status"] == "prepared"
        assert manifest["compiler_sha256"] == compiler_sha
        assert len(manifest["maps"]) == 2
        dispatcher.FEX_2605_OFFLINE_COMPILER_SHA256 = compiler_sha
        dispatcher.FEX_2605_OFFLINE_COMPILER_DLL_SHA256 = runtime_hashes
        assert dispatcher.validated_fex_offline_compiler(base) == compiler
        assert dispatcher.validated_fex_offline_root(
            base, before_compile=True
        ) == candidate
        for name, expected in original_hashes.items():
            assert sha256(source / name) == expected
            assert sha256(candidate / "codemap/new" / name) == expected

        duplicate = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "prepare",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert duplicate.returncode == 0, duplicate.stderr
        assert "FEX_OFFLINE_CACHE_REUSED=" in duplicate.stdout

        first_pending = candidate / "codemap/new" / sorted(original_hashes)[0]
        first_pending.write_bytes(b"tampered")
        rejected = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "prepare",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode != 0
        assert "failed identity validation" in rejected.stderr
        source_copy = source / first_pending.name
        first_pending.write_bytes(source_copy.read_bytes())
        first_pending.chmod(0o600)

        pending = candidate / "codemap/new"
        ready = candidate / "codemap/ready"
        cache = candidate / "cache"
        for path in pending.iterdir():
            path.unlink()
        ready_map = ready / "tombraider.exe-4cb3720654f045ff"
        ready_map.write_bytes(b"ready")
        ready_map.chmod(0o600)
        cache_file = cache / "tombraider.exe-4cb3720654f045ff-0000000000000000"
        header = struct.pack("<4sI20sI", b"FXCC", 1, bytes.fromhex(FEX_COMMIT), 42)
        cache_file.write_bytes(header + b"compiled-code")
        cache_file.chmod(0o600)

        verify = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "verify",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert verify.returncode == 0, verify.stderr
        result = json.loads((candidate / "result.json").read_text())
        assert result["status"] == "verified"
        assert result["generation"] == 1
        assert result["refresh_history"] == []
        assert result["compiled_caches"][0]["fex_commit"] == FEX_COMMIT
        assert result["compiled_caches"][0]["blocks"] == 42
        assert dispatcher.validated_fex_offline_root(
            base, before_compile=False
        ) == candidate

        steam_delta = pending / "steam.exe-2de0112aa63806bf.2001.bin"
        steam_delta.write_bytes(b"")
        steam_delta.chmod(0o600)
        game_delta = pending / "tombraider.exe-4cb3720654f045ff.2002.bin"
        game_delta.write_bytes(b"runtime-delta" * 100)
        game_delta.chmod(0o600)
        refresh = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "refresh",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert refresh.returncode == 0, refresh.stderr
        assert "generation=2 maps=2" in refresh.stdout
        assert dispatcher.validated_fex_offline_root(
            base, before_compile=True
        ) == candidate

        steam_delta.unlink()
        game_delta.unlink()
        ready_map.write_bytes(b"ready-with-runtime-delta")
        cache_file.write_bytes(header[:-4] + struct.pack("<I", 43) + b"compiled-code-2")
        cache_file.chmod(0o600)
        verify_refresh = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "verify",
                "--base",
                str(base),
                "--expected-compiler-sha256",
                compiler_sha,
                "--expected-libcpp-sha256",
                runtime_hashes["libc++.dll"],
                "--expected-libunwind-sha256",
                runtime_hashes["libunwind.dll"],
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert verify_refresh.returncode == 0, verify_refresh.stderr
        refreshed_result = json.loads((candidate / "result.json").read_text())
        assert refreshed_result["generation"] == 2
        assert refreshed_result["compiled_caches"][0]["blocks"] == 43
        assert [item["name"] for item in refreshed_result["refresh_history"][0]["pending_maps"]] == [
            steam_delta.name,
            game_delta.name,
        ]
        assert dispatcher.validated_fex_offline_root(
            base, before_compile=False
        ) == candidate

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "TOMB_RAIDER_DIRECT_MODE=fex-offline-compile" in launcher
    assert "TOMB_RAIDER_DIRECT_CHILD_PRELOAD=full" in launcher
    assert '"$python" "$prepare" refresh' in launcher
    assert '"$python" "$prepare" prepare' in launcher
    assert '"$python" "$prepare" verify' in launcher
    direct_launcher = (ROOT / "scripts/start-tombraider-direct-dispatch.sh").read_text(
        encoding="utf-8"
    )
    assert "skip_outer_affinity_guard=1" in direct_launcher
    assert "STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD=$skip_outer_affinity_guard" in direct_launcher
    steam_launcher = (ROOT / "scripts/start-steam.sh").read_text(encoding="utf-8")
    assert "skip_game_affinity_guard == 1" in steam_launcher
    assert "validated non-game AppID handoff" in steam_launcher
    benchmark = BENCHMARK.read_text(encoding="utf-8")
    assert "--fex-code-cache compiled" in benchmark
    assert "--start-temperature-ceiling-c 40" in benchmark
    single_benchmark = SINGLE_BENCHMARK.read_text(encoding="utf-8")
    assert "--fex-code-cache compiled" in single_benchmark
    assert "--start-temperature-ceiling-c 40" in single_benchmark
    assert "--warmups 0" in single_benchmark
    assert "--runs 1" in single_benchmark
    assert (
        "Starting Tomb Raider BVB probe: workload=glibc-fex-offline-benchmark"
        in single_benchmark
    )
    dispatcher_source = DISPATCHER.read_text(encoding="utf-8")
    assert '"fex-offline-compile"' in dispatcher_source
    assert '"process-all"' in dispatcher_source
    assert "run_fex_offline_compile" in dispatcher_source
    compile_environment = dispatcher_source.split(
        'if command_mode == "fex-offline-compile":', 1
    )[1].split('if command_mode in ("tombraider", "tombraider-benchmark"):', 1)[0]
    assert 'environment.pop("FEX_ENABLECODECACHINGWIP", None)' in compile_environment
    assert 'environment["FEX_APP_CACHE_LOCATION"]' in compile_environment
    assert '"FEX_ENABLECODECACHINGWIP": "1"' not in compile_environment
    print("Tomb Raider FEX offline-cache preparation tests: PASS")


if __name__ == "__main__":
    main()
