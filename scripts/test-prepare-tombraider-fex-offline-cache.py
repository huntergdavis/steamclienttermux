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
            / "compat-bin/fex-2605-offline-compiler/FEXOfflineCompiler.exe"
        )
        base.mkdir(mode=0o700)
        source.mkdir(mode=0o700, parents=True)
        compiler.parent.mkdir(mode=0o700, parents=True)
        compiler.write_bytes(b"MZ" + b"compiler-fixture" * 131072)
        compiler.chmod(0o700)
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
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert prepare.returncode == 0, prepare.stderr
        candidate = (
            base
            / "cache/fex-code-cache/tombraider-203160-offline-fff9bd81"
        )
        manifest = json.loads((candidate / "prepare.json").read_text())
        assert manifest["status"] == "prepared"
        assert manifest["compiler_sha256"] == compiler_sha
        assert len(manifest["maps"]) == 2
        dispatcher.FEX_2605_OFFLINE_COMPILER_SHA256 = compiler_sha
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
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert duplicate.returncode != 0
        assert "candidate already exists" in duplicate.stderr

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
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert verify.returncode == 0, verify.stderr
        result = json.loads((candidate / "result.json").read_text())
        assert result["status"] == "verified"
        assert result["compiled_caches"][0]["fex_commit"] == FEX_COMMIT
        assert result["compiled_caches"][0]["blocks"] == 42
        assert dispatcher.validated_fex_offline_root(
            base, before_compile=False
        ) == candidate

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "TOMB_RAIDER_DIRECT_MODE=fex-offline-compile" in launcher
    assert "TOMB_RAIDER_DIRECT_CHILD_PRELOAD=full" in launcher
    assert '"$python" "$prepare" prepare' in launcher
    assert '"$python" "$prepare" verify' in launcher
    benchmark = BENCHMARK.read_text(encoding="utf-8")
    assert "--fex-code-cache compiled" in benchmark
    assert "--start-temperature-ceiling-c 40" in benchmark
    dispatcher_source = DISPATCHER.read_text(encoding="utf-8")
    assert '"fex-offline-compile"' in dispatcher_source
    assert '"process-all"' in dispatcher_source
    assert "run_fex_offline_compile" in dispatcher_source
    print("Tomb Raider FEX offline-cache preparation tests: PASS")


if __name__ == "__main__":
    main()
