#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tempfile


FEX_COMMIT = "a04b0241c2fe3911729842205cd8643981108aad"
COMPILER_SHA256 = "7efb8f8e51e74a33f9633cac25031247d888c74c5f3ac5bce21597fd9954879b"
COMPILER_DLL_SHA256 = {
    "libc++.dll": "ed9edb58ea9f8ed633082e3636e130bac5b05b5d5c1aa4ed05f53780725b6126",
    "libunwind.dll": "535c6c8626c75f2b57cba17e0b550131d5fd699119d274290116fbe31e5b6046",
}
CANDIDATE_NAME = "tombraider-203160-offline-7efb8f8e"
MAP_NAME = re.compile(r"tombraider\.exe-[0-9a-f]{16}\.[0-9]+\.bin")
REFRESH_MAP_NAME = re.compile(
    r"(?P<program>steam|tombraider)\.exe-[0-9a-f]{16}\.[0-9]+\.bin"
)


def fail(message: str) -> None:
    raise SystemExit(f"prepare-tombraider-fex-offline-cache: {message}")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def private_directory(path: Path, description: str) -> Path:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        fail(f"{description} is unsafe: {path}")
    return path


def regular_file(path: Path, description: str, maximum: int) -> os.stat_result:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or metadata.st_size <= 0
        or metadata.st_size > maximum
    ):
        fail(f"{description} is unsafe: {path}")
    return metadata


def compiler_path(
    base: Path, expected_sha256: str, expected_dll_sha256: dict[str, str]
) -> Path:
    compiler = (
        base
        / "compat-bin/fex-2605-offline-compiler-native-arm64/FEXOfflineCompiler.exe"
    )
    regular_file(compiler, "FEX offline compiler", 16 * 1024 * 1024)
    if digest(compiler) != expected_sha256:
        fail("FEX offline compiler SHA-256 does not match")
    for name, expected in expected_dll_sha256.items():
        runtime = compiler.parent / name
        regular_file(runtime, f"FEX offline compiler runtime {name}", 4 * 1024 * 1024)
        if digest(runtime) != expected:
            fail(f"FEX offline compiler runtime SHA-256 does not match: {name}")
    return compiler


def write_exclusive(source: Path, destination: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb", closefd=False
        ) as output_stream:
            while chunk := input_stream.read(1024 * 1024):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json_atomic(path: Path, document: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_verified_result(root: Path, expected_sha256: str) -> tuple[dict, str]:
    path = root / "result.json"
    regular_file(path, "verified FEX cache result", 4 * 1024 * 1024)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"verified FEX cache result is unavailable: {error}")
    if (
        not isinstance(document, dict)
        or document.get("status") != "verified"
        or document.get("fex_commit") != FEX_COMMIT
        or document.get("compiler_sha256") != expected_sha256
    ):
        fail("verified FEX cache result failed identity validation")
    return document, digest(path)


def compiled_cache_inventory(cache_files: list[Path]) -> list[dict]:
    expected_hash = bytes.fromhex(FEX_COMMIT)
    compiled = []
    for path in cache_files:
        metadata = regular_file(path, "compiled FEX cache", 256 * 1024 * 1024)
        with path.open("rb") as stream:
            header = stream.read(32)
        if len(header) != 32:
            fail(f"compiled cache has a truncated header: {path.name}")
        magic, version, fex_hash, blocks = struct.unpack("<4sI20sI", header)
        if magic != b"FXCC" or version != 1 or fex_hash != expected_hash or blocks == 0:
            fail(f"compiled cache header is incompatible with FEX-2605: {path.name}")
        compiled.append(
            {
                "name": path.name,
                "size_bytes": metadata.st_size,
                "sha256": digest(path),
                "format_version": version,
                "fex_commit": fex_hash.hex(),
                "blocks": blocks,
            }
        )
    return compiled


def audit(
    base: Path, expected_sha256: str, expected_dll_sha256: dict[str, str]
) -> None:
    """Idempotently authenticate a finalized cache without advancing it."""
    compiler_path(base, expected_sha256, expected_dll_sha256)
    root = private_directory(
        base / "cache/fex-code-cache" / CANDIDATE_NAME,
        "compiled FEX cache candidate",
    )
    pending = private_directory(root / "codemap/new", "pending code-map directory")
    ready = private_directory(root / "codemap/ready", "ready code-map directory")
    cache = private_directory(root / "cache", "compiled cache directory")
    pending_files = sorted(pending.iterdir())
    ready_files = sorted(ready.iterdir())
    cache_files = sorted(cache.iterdir())
    if len(pending_files) > 128 or not 1 <= len(ready_files) <= 128 or not 1 <= len(cache_files) <= 128:
        fail("finalized FEX cache has invalid map or cache counts")
    for path in pending_files:
        match = REFRESH_MAP_NAME.fullmatch(path.name)
        if match is None:
            fail(f"runtime delta map has an unexpected name: {path.name}")
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or metadata.st_size > 64 * 1024 * 1024
            or (metadata.st_size == 0 and match.group("program") != "steam")
        ):
            fail(f"runtime delta map is unsafe: {path}")
    for path in ready_files:
        regular_file(path, "aggregated FEX code map", 64 * 1024 * 1024)
    result, result_sha256 = read_verified_result(root, expected_sha256)
    generation = result.get("generation", 1)
    history = result.get("refresh_history")
    if (
        result.get("schema") != 1
        or type(generation) is not int
        or not 1 <= generation <= 1024
        or result.get("candidate") != str(root)
        or result.get("ready_code_maps") != len(ready_files)
        or not isinstance(history, list)
        or len(history) >= 64
        or result.get("compiled_caches") != compiled_cache_inventory(cache_files)
    ):
        fail("finalized FEX cache result does not match its files")
    print(
        f"FEX_OFFLINE_CACHE_AUDITED={root} generation={generation} "
        f"caches={len(cache_files)} pending={len(pending_files)} "
        f"result_sha256={result_sha256}"
    )


def refresh(
    base: Path, expected_sha256: str, expected_dll_sha256: dict[str, str]
) -> None:
    compiler_path(base, expected_sha256, expected_dll_sha256)
    root = private_directory(
        base / "cache/fex-code-cache" / CANDIDATE_NAME,
        "compiled FEX cache candidate",
    )
    pending = private_directory(root / "codemap/new", "pending code-map directory")
    ready = private_directory(root / "codemap/ready", "ready code-map directory")
    cache = private_directory(root / "cache", "compiled cache directory")
    result, result_sha256 = read_verified_result(root, expected_sha256)
    if not list(ready.iterdir()) or not list(cache.iterdir()):
        fail("verified FEX cache candidate has no compiled files")
    paths = sorted(pending.iterdir())
    if not 1 <= len(paths) <= 128:
        fail(f"expected 1 through 128 runtime delta maps, found {len(paths)}")
    recorded = []
    for path in paths:
        match = REFRESH_MAP_NAME.fullmatch(path.name)
        if match is None:
            fail(f"runtime delta map has an unexpected name: {path.name}")
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or metadata.st_size > 64 * 1024 * 1024
            or (metadata.st_size == 0 and match.group("program") != "steam")
        ):
            fail(f"runtime delta map is unsafe: {path}")
        recorded.append(
            {
                "name": path.name,
                "size_bytes": metadata.st_size,
                "sha256": digest(path),
            }
        )
    generation = result.get("generation", 1)
    if type(generation) is not int or not 1 <= generation < 1024:
        fail("verified FEX cache result has an invalid generation")
    manifest = {
        "schema": 1,
        "status": "refresh-prepared",
        "generation": generation + 1,
        "previous_result_sha256": result_sha256,
        "pending_maps": recorded,
    }
    write_json_atomic(root / "refresh.json", manifest)
    print(
        f"FEX_OFFLINE_CACHE_REFRESH_PREPARED={root} "
        f"generation={generation + 1} maps={len(recorded)}"
    )


def prepare(
    base: Path, expected_sha256: str, expected_dll_sha256: dict[str, str]
) -> None:
    compiler = compiler_path(base, expected_sha256, expected_dll_sha256)
    source = private_directory(
        base / "cache/fex-code-cache/tombraider-203160/codemap/new",
        "recorded Tomb Raider code-map directory",
    )
    maps = sorted(path for path in source.iterdir() if MAP_NAME.fullmatch(path.name))
    if not 1 <= len(maps) <= 128:
        fail(f"expected 1 through 128 Tomb Raider code maps, found {len(maps)}")
    for path in maps:
        regular_file(path, "recorded Tomb Raider code map", 16 * 1024 * 1024)

    root = base / "cache/fex-code-cache" / CANDIDATE_NAME
    copied = [
        {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        for path in maps
    ]
    if root.exists() or root.is_symlink():
        private_directory(root, "existing offline-cache candidate")
        expected_children = {"cache", "codemap", "prepare.json"}
        if {path.name for path in root.iterdir()} != expected_children:
            fail(f"existing candidate is not pristine: {root}")
        pending = private_directory(root / "codemap/new", "pending code-map directory")
        ready = private_directory(root / "codemap/ready", "ready code-map directory")
        cache = private_directory(root / "cache", "compiled cache directory")
        if list(ready.iterdir()) or list(cache.iterdir()):
            fail(f"existing candidate is not in pre-compile state: {root}")
        pending_files = sorted(pending.iterdir())
        if [path.name for path in pending_files] != [item["name"] for item in copied]:
            fail(f"existing candidate code maps differ from the recording: {root}")
        for path, item in zip(pending_files, copied, strict=True):
            regular_file(path, "existing candidate code map", 16 * 1024 * 1024)
            if path.stat().st_size != item["size_bytes"] or digest(path) != item["sha256"]:
                fail(f"existing candidate code map failed identity validation: {path.name}")
        try:
            manifest = json.loads((root / "prepare.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            fail(f"existing candidate manifest is unavailable: {error}")
        expected = {
            "schema": 1,
            "status": "prepared",
            "fex_commit": FEX_COMMIT,
            "compiler": str(compiler),
            "compiler_sha256": expected_sha256,
            "source": str(source),
            "candidate": str(root),
            "maps": copied,
        }
        if manifest != expected:
            fail(f"existing candidate manifest failed identity validation: {root}")
        print(f"FEX_OFFLINE_CACHE_REUSED={root} maps={len(copied)}")
        return
    root.mkdir(mode=0o700)
    (root / "codemap/new").mkdir(mode=0o700, parents=True)
    (root / "codemap/ready").mkdir(mode=0o700)
    (root / "cache").mkdir(mode=0o700)
    for path, item in zip(maps, copied, strict=True):
        destination = root / "codemap/new" / path.name
        write_exclusive(path, destination)
        if digest(destination) != item["sha256"]:
            fail(f"copied code map failed SHA-256 validation: {path.name}")
    manifest = {
        "schema": 1,
        "status": "prepared",
        "fex_commit": FEX_COMMIT,
        "compiler": str(compiler),
        "compiler_sha256": expected_sha256,
        "source": str(source),
        "candidate": str(root),
        "maps": copied,
    }
    manifest_path = root / "prepare.json"
    descriptor = os.open(
        manifest_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(f"FEX_OFFLINE_CACHE_PREPARED={root} maps={len(copied)}")


def verify(
    base: Path, expected_sha256: str, expected_dll_sha256: dict[str, str]
) -> None:
    compiler_path(base, expected_sha256, expected_dll_sha256)
    root = private_directory(
        base / "cache/fex-code-cache" / CANDIDATE_NAME,
        "compiled FEX cache candidate",
    )
    pending = private_directory(root / "codemap/new", "pending code-map directory")
    ready = private_directory(root / "codemap/ready", "ready code-map directory")
    cache = private_directory(root / "cache", "compiled cache directory")
    pending_files = list(pending.iterdir())
    ready_files = sorted(ready.iterdir())
    cache_files = sorted(cache.iterdir())
    if pending_files or not 1 <= len(ready_files) <= 128 or not 1 <= len(cache_files) <= 128:
        fail("offline compiler did not produce a complete candidate")
    for path in ready_files:
        regular_file(path, "aggregated FEX code map", 64 * 1024 * 1024)

    compiled = compiled_cache_inventory(cache_files)
    result_path = root / "result.json"
    refresh_path = root / "refresh.json"
    generation = 1
    refresh_history = []
    if result_path.exists() or result_path.is_symlink():
        previous, previous_sha256 = read_verified_result(root, expected_sha256)
        regular_file(refresh_path, "FEX cache refresh manifest", 4 * 1024 * 1024)
        try:
            refresh_manifest = json.loads(refresh_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            fail(f"FEX cache refresh manifest is unavailable: {error}")
        previous_generation = previous.get("generation", 1)
        if (
            not isinstance(refresh_manifest, dict)
            or refresh_manifest.get("status") != "refresh-prepared"
            or refresh_manifest.get("previous_result_sha256") != previous_sha256
            or refresh_manifest.get("generation") != previous_generation + 1
            or not isinstance(refresh_manifest.get("pending_maps"), list)
        ):
            fail("FEX cache refresh manifest failed identity validation")
        generation = refresh_manifest["generation"]
        refresh_history = previous.get("refresh_history", [])
        if not isinstance(refresh_history, list) or len(refresh_history) >= 64:
            fail("FEX cache refresh history is invalid or full")
        refresh_history = [
            *refresh_history,
            {
                "generation": generation,
                "previous_result_sha256": previous_sha256,
                "pending_maps": refresh_manifest["pending_maps"],
            },
        ]
    result = {
        "schema": 1,
        "status": "verified",
        "generation": generation,
        "fex_commit": FEX_COMMIT,
        "compiler_sha256": expected_sha256,
        "candidate": str(root),
        "ready_code_maps": len(ready_files),
        "compiled_caches": compiled,
        "refresh_history": refresh_history,
    }
    write_json_atomic(result_path, result)
    print(f"FEX_OFFLINE_CACHE_VERIFIED={root} caches={len(compiled)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "refresh", "verify", "audit"))
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--expected-compiler-sha256", default=COMPILER_SHA256)
    parser.add_argument(
        "--expected-libcpp-sha256", default=COMPILER_DLL_SHA256["libc++.dll"]
    )
    parser.add_argument(
        "--expected-libunwind-sha256",
        default=COMPILER_DLL_SHA256["libunwind.dll"],
    )
    arguments = parser.parse_args()
    expected_hashes = {
        "libc++.dll": arguments.expected_libcpp_sha256,
        "libunwind.dll": arguments.expected_libunwind_sha256,
    }
    if not all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (arguments.expected_compiler_sha256, *expected_hashes.values())
    ):
        fail("expected compiler SHA-256 values must be 64 lowercase hex characters")
    base = Path(arguments.base)
    private_directory(base, "Steam ARM64 base")
    if arguments.action == "prepare":
        prepare(base, arguments.expected_compiler_sha256, expected_hashes)
    elif arguments.action == "refresh":
        refresh(base, arguments.expected_compiler_sha256, expected_hashes)
    elif arguments.action == "verify":
        verify(base, arguments.expected_compiler_sha256, expected_hashes)
    else:
        audit(base, arguments.expected_compiler_sha256, expected_hashes)


if __name__ == "__main__":
    main()
