#!/usr/bin/env python3
"""Move a Pressure Vessel payload out of PRoot without logging its environment."""

from __future__ import annotations

import argparse
import array
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import sys
import tempfile
import time
from typing import NoReturn


SCHEMA_VERSION = 1
KIND = "steamclienttermux-pressure-vessel-direct"
MAX_FRAME = 16 * 1024 * 1024
MAX_FDS = 64
MAX_ARGS_DATA = 16 * 1024 * 1024
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FD_SOURCE_OPTIONS = {
    "--bind-data",
    "--bind-fd",
    "--file",
    "--ro-bind-data",
    "--ro-bind-fd",
    "--seccomp",
    "--sync-fd",
    "--info-fd",
    "--json-status-fd",
    "--userns",
}
BIND_OPTIONS = {
    "--bind",
    "--bind-try",
    "--dev-bind",
    "--dev-bind-try",
    "--ro-bind",
    "--ro-bind-try",
}
FEX_2605_OFFLINE_COMPILER_SHA256 = (
    "7efb8f8e51e74a33f9633cac25031247d888c74c5f3ac5bce21597fd9954879b"
)
FEX_2605_OFFLINE_COMPILER_DLL_SHA256 = {
    "libc++.dll": "ed9edb58ea9f8ed633082e3636e130bac5b05b5d5c1aa4ed05f53780725b6126",
    "libunwind.dll": "535c6c8626c75f2b57cba17e0b550131d5fd699119d274290116fbe31e5b6046",
}
FEX_OFFLINE_CACHE_NAME = "tombraider-203160-offline-7efb8f8e"
DXVK_X32_VARIANTS = {
    "dxvk-1.10.3-x32": (
        "tombraider-dxvk-1.10.3-x32-8d1a3c91",
        {
            "d3d10core.dll": (1114126, "83d3e6155c04f31aaaef92303e89f5065db0fee56ea0f09f6c433302b30da959"),
            "d3d11.dll": (3526670, "da35effaadeb4d09455a315de7352320d5445aca386c0d8e0a1094a48d585246"),
            "d3d9.dll": (3305486, "b6cfa2cd62af73b80d461085d126004b0e22dd3944c9246c58e3a68e747b56b6"),
            "dxgi.dll": (2338830, "7674136f2e894cf5a2fbb24ff283215301c591e08b6fc787aff27654afe34c49"),
        },
    ),
    "dxvk-2.4.1-x32": (
        "tombraider-dxvk-2.4.1-x32-7b23db4e",
        {
            "d3d10core.dll": (196622, "e7a4d2b8d32124b3768e0c958fdcda4dcf97fcdd2b983917689c321d4e3c162c"),
            "d3d11.dll": (4517902, "0b560b0d24b14ac2ee3dbc05a12d480eed341a575d713647305d7a040f33abb9"),
            "d3d8.dll": (1662990, "e661906de521a5b0a44525b7eccc43ecf3556326326f900a6038341503f05811"),
            "d3d9.dll": (4124686, "cc556331fc3388989749620bceead4c2da95c3932ed38cf5cc24f3f0a878866e"),
            "dxgi.dll": (2998286, "4b5d6275d5987de5e64f6ce42f5f7b888fb75bd414326d2ecc792effd9a385da"),
        },
    ),
}


class DispatchError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise DispatchError(message)


def private_directory(path: Path, description: str, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"{description} is not a real directory: {path}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        fail(f"{description} is not privately owned: {path}")
    return path


def validated_base(value: str) -> Path:
    if not value.startswith("/"):
        fail("Steam base must be absolute")
    base = Path(value)
    metadata = base.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or base.is_symlink():
        fail(f"Steam base is not a real directory: {base}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        fail(f"Steam base is not privately owned: {base}")
    return base


def validated_host_vulkan_icd(base: Path) -> Path:
    bvb = os.environ.get("STEAM_ARM64_BVB_VULKAN", "0")
    if bvb not in ("0", "1"):
        fail("STEAM_ARM64_BVB_VULKAN must be 0 or 1")
    path = (
        base / "bvb/icd.d/bvb_icd.aarch64.json"
        if bvb == "1"
        else base / "mesa-kgsl/icd.d/freedreno-private.json"
    )
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"selected Vulkan ICD is unavailable: {error}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        fail(f"selected Vulkan ICD is not a private regular file: {path}")
    return path


def bvb_vulkan_environment() -> dict[str, str]:
    bvb = os.environ.get("STEAM_ARM64_BVB_VULKAN", "0")
    command_stream = os.environ.get(
        "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM", "strict"
    )
    mapped_memory = os.environ.get(
        "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY", "strict"
    )
    descriptor_journal = os.environ.get(
        "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL", "strict"
    )
    first_rejection_diagnostic = os.environ.get(
        "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC", "0"
    )
    frame_profile = os.environ.get("BVB_FRAME_PROFILE", "0")
    if command_stream not in ("strict", "shared"):
        fail("STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM must be strict or shared")
    if mapped_memory not in ("strict", "shared", "direct"):
        fail(
            "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY must be strict, shared, or direct"
        )
    if descriptor_journal not in ("strict", "shared"):
        fail("STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL must be strict or shared")
    if first_rejection_diagnostic not in ("0", "1"):
        fail(
            "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC must be 0 or 1"
        )
    if frame_profile not in ("0", "1"):
        fail("BVB_FRAME_PROFILE must be 0 or 1")
    if bvb != "1":
        if command_stream == "shared":
            fail("shared BVB command stream requires STEAM_ARM64_BVB_VULKAN=1")
        if mapped_memory != "strict":
            fail(
                f"{mapped_memory} BVB mapped memory requires "
                "STEAM_ARM64_BVB_VULKAN=1"
            )
        if descriptor_journal == "shared":
            fail("shared BVB descriptor journal requires STEAM_ARM64_BVB_VULKAN=1")
        if first_rejection_diagnostic == "1":
            fail("BVB first-rejection diagnostic requires STEAM_ARM64_BVB_VULKAN=1")
        return {}
    socket_path = os.environ.get("BVB_BRIDGE_SOCKET", "")
    if not socket_path.startswith("/"):
        fail("BVB_BRIDGE_SOCKET must be absolute when BVB Vulkan is enabled")
    diagnostics = os.environ.get("BVB_ICD_DIAGNOSTICS", "1")
    if diagnostics not in ("0", "1"):
        fail("BVB_ICD_DIAGNOSTICS must be 0 or 1")
    probe_wsi = os.environ.get("BVB_ICD_PROBE_WSI", "0")
    if probe_wsi not in ("0", "1"):
        fail("BVB_ICD_PROBE_WSI must be 0 or 1")
    environment = {
        "BVB_BRIDGE_SOCKET": socket_path,
        "BVB_ICD_PROBE_WSI": probe_wsi,
    }
    if diagnostics == "1":
        environment["BVB_ICD_DIAGNOSTICS"] = "1"
    if command_stream == "shared":
        environment["BVB_COMMAND_STREAM"] = "shared"
    if mapped_memory != "strict":
        environment["BVB_MAPPED_MEMORY"] = mapped_memory
    if descriptor_journal == "shared":
        environment["BVB_DESCRIPTOR_JOURNAL"] = "shared"
    if first_rejection_diagnostic == "1":
        environment["BVB_FIRST_REJECTION_DIAGNOSTIC"] = "1"
    if frame_profile == "1":
        environment["BVB_FRAME_PROFILE"] = "1"
    if diagnostics == "1":
        environment["VK_LOADER_DEBUG"] = "error,warn,driver"
    return environment


def validated_raknet_recv_backoff(
    base: Path, command_mode: str
) -> tuple[Path, dict[str, str]] | None:
    sleep_us = os.environ.get("STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US", "0")
    if sleep_us not in ("0", "1000"):
        fail("STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US must be 0 or 1000")
    if sleep_us == "0":
        return None
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        fail("RakNet receive backoff is valid only for Tomb Raider")
    shim = base / "compat-bin/libtgcompat-raknet-recv.so"
    try:
        metadata = shim.lstat()
        contents = shim.read_bytes()
    except OSError as error:
        fail(f"RakNet receive backoff shim is unavailable: {error}")
    required_markers = (
        b"Raknet-RecvFrom",
        b"TGCOMPAT_RAKNET_RECV_SLEEP_US",
        b"sched_yield",
    )
    if (
        not stat.S_ISREG(metadata.st_mode)
        or shim.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or not all(marker in contents for marker in required_markers)
    ):
        fail(f"RakNet receive backoff shim is not a private validated file: {shim}")
    return shim, {"TGCOMPAT_RAKNET_RECV_SLEEP_US": sleep_us}


def apply_fex_code_cache(
    environment: dict[str, str], base: Path, command_mode: str
) -> None:
    selector = os.environ.get("STEAM_ARM64_DIRECT_FEX_CODE_CACHE", "off")
    if selector not in ("off", "on", "compiled"):
        fail("STEAM_ARM64_DIRECT_FEX_CODE_CACHE must be off, on, or compiled")
    environment.pop("FEX_ENABLECODECACHINGWIP", None)
    environment.pop("FEX_APP_CACHE_LOCATION", None)
    if selector == "off":
        return
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        fail("FEX code cache is valid only for Tomb Raider")
    if selector == "compiled":
        cache = validated_fex_compiled_cache(base)
    else:
        cache = private_directory(
            base / "cache/fex-code-cache/tombraider-203160",
            "Tomb Raider FEX code cache",
            create=True,
        )
    environment.update(
        {
            "FEX_ENABLECODECACHINGWIP": "1",
            # FEX appends paths such as "codemap/new" directly to this value.
            "FEX_APP_CACHE_LOCATION": f"{cache}/",
        }
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_fex_offline_root(base: Path, before_compile: bool) -> Path:
    root = private_directory(
        base / "cache/fex-code-cache" / FEX_OFFLINE_CACHE_NAME,
        "Tomb Raider compiled FEX cache candidate",
    )
    new = private_directory(root / "codemap/new", "pending FEX code maps")
    ready = private_directory(root / "codemap/ready", "aggregated FEX code maps")
    cache = private_directory(root / "cache", "compiled FEX cache files")
    new_files = sorted(new.iterdir())
    ready_files = sorted(ready.iterdir())
    cache_files = sorted(cache.iterdir())

    def validate_files(
        paths: list[Path], description: str, *, allow_zero: bool = False
    ) -> None:
        if len(paths) > 128:
            fail(f"{description} contains too many files")
        for path in paths:
            metadata = path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or path.is_symlink()
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o022
                or (metadata.st_size <= 0 and not allow_zero)
                or metadata.st_size > 64 * 1024 * 1024
            ):
                fail(f"{description} contains an unsafe file: {path}")

    validate_files(new_files, "pending FEX code maps", allow_zero=before_compile)
    validate_files(ready_files, "aggregated FEX code maps")
    validate_files(cache_files, "compiled FEX cache files")

    def validate_compiled_identity() -> tuple[Path, dict]:
        if not ready_files or not cache_files:
            fail("FEX offline candidate has no complete compiled-cache result")
        expected_hash = bytes.fromhex(
            "a04b0241c2fe3911729842205cd8643981108aad"
        )
        for path in cache_files:
            with path.open("rb") as stream:
                header = stream.read(32)
            if len(header) != 32:
                fail(f"compiled FEX cache has a truncated header: {path}")
            magic, version, fex_hash, blocks = struct.unpack(
                "<4sI20sI", header
            )
            if (
                magic != b"FXCC"
                or version != 1
                or fex_hash != expected_hash
                or blocks == 0
            ):
                fail(f"compiled FEX cache has an incompatible header: {path}")
        result_path = root / "result.json"
        try:
            result_metadata = result_path.lstat()
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError) as error:
            fail(f"compiled FEX cache result is unavailable: {error}")
        if (
            not stat.S_ISREG(result_metadata.st_mode)
            or result_path.is_symlink()
            or result_metadata.st_uid != os.geteuid()
            or result_metadata.st_mode & 0o022
            or result.get("status") != "verified"
            or result.get("fex_commit")
            != "a04b0241c2fe3911729842205cd8643981108aad"
            or result.get("compiler_sha256")
            != FEX_2605_OFFLINE_COMPILER_SHA256
        ):
            fail("compiled FEX cache result failed identity validation")
        return result_path, result

    if before_compile:
        if not 1 <= len(new_files) <= 128:
            fail("FEX offline candidate has no runtime maps to compile")
        refreshing = bool(ready_files or cache_files)
        if refreshing:
            if not ready_files or not cache_files:
                fail("FEX offline refresh has incomplete compiled state")
            result_path, result = validate_compiled_identity()
            refresh_path = root / "refresh.json"
            try:
                refresh_metadata = refresh_path.lstat()
                refresh = json.loads(refresh_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError) as error:
                fail(f"FEX offline refresh manifest is unavailable: {error}")
            generation = result.get("generation", 1)
            if (
                not stat.S_ISREG(refresh_metadata.st_mode)
                or refresh_path.is_symlink()
                or refresh_metadata.st_uid != os.geteuid()
                or refresh_metadata.st_mode & 0o022
                or refresh.get("status") != "refresh-prepared"
                or refresh.get("generation") != generation + 1
                or refresh.get("previous_result_sha256")
                != sha256_file(result_path)
            ):
                fail("FEX offline refresh manifest failed identity validation")
            pending_manifest = refresh.get("pending_maps")
            observed_pending = [
                {
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in new_files
            ]
            if pending_manifest != observed_pending:
                fail("FEX offline refresh maps changed after preparation")
        else:
            result_path = root / "result.json"
            if result_path.exists() or result_path.is_symlink():
                fail("pristine FEX offline candidate unexpectedly has a result")
        for path in new_files:
            match = re.fullmatch(
                r"(steam|tombraider)\.exe-[0-9a-f]{16}\.[0-9]+\.bin",
                path.name,
            )
            if match is None or (path.stat().st_size == 0 and match.group(1) != "steam"):
                fail(f"pending FEX code map has an unexpected shape: {path.name}")
            if not refreshing and match.group(1) != "tombraider":
                fail(f"pristine FEX code map has an unexpected name: {path.name}")
    elif new_files:
        fail("FEX offline candidate has uncompiled runtime maps")
    else:
        validate_compiled_identity()
    return root


def validated_fex_offline_compiler(base: Path) -> Path:
    compiler = (
        base
        / "compat-bin/fex-2605-offline-compiler-native-arm64/FEXOfflineCompiler.exe"
    )
    try:
        metadata = compiler.lstat()
    except FileNotFoundError:
        fail(f"FEX offline compiler is unavailable: {compiler}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or compiler.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not 1024 * 1024 <= metadata.st_size <= 16 * 1024 * 1024
        or sha256_file(compiler) != FEX_2605_OFFLINE_COMPILER_SHA256
    ):
        fail(f"FEX offline compiler failed identity validation: {compiler}")
    for name, expected_sha256 in FEX_2605_OFFLINE_COMPILER_DLL_SHA256.items():
        runtime = compiler.parent / name
        try:
            runtime_metadata = runtime.lstat()
        except FileNotFoundError:
            fail(f"FEX offline compiler runtime is unavailable: {runtime}")
        if (
            not stat.S_ISREG(runtime_metadata.st_mode)
            or runtime.is_symlink()
            or runtime_metadata.st_uid != os.geteuid()
            or runtime_metadata.st_mode & 0o022
            or not 32 * 1024 <= runtime_metadata.st_size <= 4 * 1024 * 1024
            or sha256_file(runtime) != expected_sha256
        ):
            fail(f"FEX offline compiler runtime failed identity validation: {runtime}")
    return compiler


def validated_fex_compiled_cache(base: Path) -> Path:
    return validated_fex_offline_root(base, before_compile=False)


def apply_fex_smc_checks(
    environment: dict[str, str], command_mode: str
) -> None:
    selector = os.environ.get("STEAM_ARM64_DIRECT_FEX_SMC_CHECKS", "mtrack")
    if selector not in ("mtrack", "none"):
        fail("STEAM_ARM64_DIRECT_FEX_SMC_CHECKS must be mtrack or none")
    environment.pop("FEX_SMC_CHECKS", None)
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        if selector != "mtrack":
            fail("FEX SMC-check override is valid only for Tomb Raider")
        return
    environment["FEX_SMC_CHECKS"] = selector


def apply_dxvk_relaxed_graphics_barriers(
    environment: dict[str, str], command_mode: str
) -> None:
    selector = os.environ.get(
        "STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS", "off"
    )
    if selector not in ("off", "on"):
        fail(
            "STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS "
            "must be off or on"
        )
    environment.pop("DXVK_CONFIG", None)
    environment.pop("DXVK_CONFIG_FILE", None)
    if selector == "off":
        return
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        fail("DXVK relaxed graphics barriers are valid only for Tomb Raider")
    environment["DXVK_CONFIG"] = "d3d11.relaxedGraphicsBarriers = True"


def apply_dxvk_compiler_threads(
    environment: dict[str, str], command_mode: str
) -> None:
    selector = os.environ.get("STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS", "0")
    if re.fullmatch(r"(?:0|[1-9]|1[0-6])", selector) is None:
        fail("STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS must be 0 through 16")
    environment.pop("STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS", None)
    threads = int(selector)
    if threads == 0:
        return
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        fail("DXVK compiler-thread override is valid only for Tomb Raider")
    setting = f"dxvk.numCompilerThreads = {threads}"
    existing = environment.get("DXVK_CONFIG")
    environment["DXVK_CONFIG"] = f"{existing}; {setting}" if existing else setting
    environment["STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS"] = str(threads)


def apply_dxvk_variant(
    environment: dict[str, str], base: Path, command_mode: str
) -> None:
    selector = os.environ.get("STEAM_ARM64_DIRECT_DXVK_VARIANT", "bundled")
    if selector != "bundled" and selector not in DXVK_X32_VARIANTS:
        fail(
            "STEAM_ARM64_DIRECT_DXVK_VARIANT must be bundled, "
            "dxvk-1.10.3-x32, or dxvk-2.4.1-x32"
        )
    environment.pop("WINEDLLPATH", None)
    if selector == "bundled":
        return
    if command_mode not in ("tombraider", "tombraider-benchmark"):
        fail("DXVK variant override is valid only for Tomb Raider")

    candidate_name, candidate_files = DXVK_X32_VARIANTS[selector]
    candidate = private_directory(
        base / "candidates" / candidate_name / "x32",
        "Tomb Raider DXVK candidate",
    )
    for name, (expected_size, expected_sha256) in candidate_files.items():
        path = candidate / name
        try:
            metadata = path.lstat()
        except OSError as error:
            fail(f"Tomb Raider DXVK candidate is unavailable: {error}")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or metadata.st_size != expected_size
            or sha256_file(path) != expected_sha256
        ):
            fail(f"Tomb Raider DXVK candidate failed validation: {path}")
    # A selected candidate always gets a small DXVK info log. This proves the
    # actual loaded version without enabling the enormous WINEDEBUG diagnostic
    # trace that perturbs FPS and thermal state.
    environment.update(direct_dxvk_environment(base))
    environment["STEAMCLIENTTERMUX_DXVK_VARIANT"] = selector
    # The transactional game-local overlay supplies one coherent x86 DXVK
    # family. Tomb Raider's benchmark uses D3D11 through DXGI; retain D3D9 for
    # its launcher and d3d10core so no module can fall back to bundled DXVK.
    environment["WINEDLLOVERRIDES"] = (
        "d3d9,d3d10core,d3d11,dxgi=n"
    )


def validated_vulkan_trace(base: Path) -> tuple[Path, Path] | None:
    preload_value = os.environ.get("STEAM_ARM64_VULKAN_TRACE_PRELOAD")
    trace_value = os.environ.get("STEAM_ARM64_VULKAN_TRACE_FILE")
    if preload_value is None and trace_value is None:
        return None
    if not preload_value or not trace_value:
        fail("Vulkan trace preload and output must be supplied together")

    expected_preload = (
        Path.home()
        / "bionic-vulkan-bridge/out/glibc/libbvb-vulkan-resolve-trace.so"
    )
    preload = Path(preload_value)
    if preload != expected_preload:
        fail(f"Vulkan trace preload is not the pinned bridge artifact: {preload}")
    try:
        preload_metadata = preload.lstat()
    except OSError as error:
        fail(f"Vulkan trace preload is unavailable: {error}")
    if (
        not stat.S_ISREG(preload_metadata.st_mode)
        or preload.is_symlink()
        or preload_metadata.st_uid != os.geteuid()
        or preload_metadata.st_mode & 0o022
    ):
        fail(f"Vulkan trace preload is not a private regular file: {preload}")

    trace = Path(trace_value)
    if trace.parent != base / "logs" or not re.fullmatch(
        r"tombraider-vulkan-resolve-\d{8}T\d{6}Z-\d+\.tsv", trace.name
    ):
        fail(f"Vulkan trace output is outside the controlled log path: {trace}")
    try:
        trace_metadata = trace.lstat()
    except OSError as error:
        fail(f"Vulkan trace output is unavailable: {error}")
    if (
        not stat.S_ISREG(trace_metadata.st_mode)
        or trace.is_symlink()
        or trace_metadata.st_uid != os.geteuid()
        or trace_metadata.st_mode & 0o077
    ):
        fail(f"Vulkan trace output is not a private regular file: {trace}")
    return preload, trace


def dispatch_socket(base: Path) -> Path:
    run = private_directory(base / "run", "Steam run directory", create=True)
    directory = private_directory(
        run / "native-runtime-dispatch", "Runtime dispatch directory", create=True
    )
    return directory / "dispatch.sock"


def wait_for_direct_start_gate(base: Path) -> None:
    value = os.environ.get("STEAM_ARM64_DIRECT_START_GATE")
    if value is None:
        return
    gate = Path(value)
    directory = private_directory(
        base / "run/bvb", "BVB launch-gate directory"
    )
    if (
        not gate.is_absolute()
        or gate.parent != directory
        or not re.fullmatch(
            r"tombraider-start-\d{8}T\d{6}Z-\d+\.gate", gate.name
        )
    ):
        fail(f"direct start gate is outside the controlled path: {gate}")
    waiting = Path(f"{gate}.waiting")
    for path in (gate, waiting):
        if path.exists() or path.is_symlink():
            fail(f"direct start gate path already exists: {path}")
    descriptor = os.open(
        waiting,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    os.close(descriptor)
    print(f"START_GATE_WAITING={waiting}", flush=True)
    timeout_value = os.environ.get("STEAM_ARM64_DIRECT_START_GATE_TIMEOUT", "300")
    if not timeout_value.isdecimal() or not 1 <= int(timeout_value) <= 600:
        waiting.unlink()
        fail("STEAM_ARM64_DIRECT_START_GATE_TIMEOUT must be 1 through 600")
    deadline = time.monotonic() + int(timeout_value)
    try:
        while time.monotonic() < deadline:
            if gate.is_symlink():
                fail("direct start gate must not be a symbolic link")
            try:
                metadata = gate.lstat()
            except FileNotFoundError:
                time.sleep(0.05)
                continue
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_size != 0
            ):
                fail(f"direct start gate is unsafe: {gate}")
            gate.unlink()
            print("START_GATE_RELEASED=1", flush=True)
            return
        fail("direct start gate timed out")
    finally:
        try:
            metadata = waiting.lstat()
        except FileNotFoundError:
            pass
        else:
            if (
                stat.S_ISREG(metadata.st_mode)
                and not waiting.is_symlink()
                and metadata.st_uid == os.geteuid()
            ):
                waiting.unlink()


def locate_args_fd(arguments: list[str]) -> tuple[int, int, int]:
    for index, argument in enumerate(arguments):
        if argument == "--args":
            if index + 1 >= len(arguments):
                fail("--args is missing its fd")
            value = arguments[index + 1]
            payload_start = index + 2
            break
        if argument.startswith("--args="):
            value = argument[7:]
            payload_start = index + 1
            break
    else:
        fail("Pressure Vessel invocation has no --args fd")
    if not value.isdecimal():
        fail("invalid --args fd")
    return int(value), index, payload_start


def read_nul_arguments(descriptor: int) -> list[str]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_ARGS_DATA:
        fail("unexpected --args fd type or size")
    data = os.pread(descriptor, metadata.st_size, 0)
    if len(data) != metadata.st_size or not data.endswith(b"\0"):
        fail("malformed --args data")
    return [os.fsdecode(value) for value in data[:-1].split(b"\0")]


def parse_nonnegative_fd(value: str, description: str) -> int:
    if not value.isdecimal():
        fail(f"invalid fd for {description}")
    descriptor = int(value)
    if descriptor < 0:
        fail(f"invalid fd for {description}")
    return descriptor


def referenced_fd_numbers(bwrap_arguments: list[str], payload: list[str]) -> list[int]:
    descriptors: set[int] = set()
    for index, argument in enumerate(bwrap_arguments[:-1]):
        if argument in FD_SOURCE_OPTIONS:
            descriptors.add(
                parse_nonnegative_fd(bwrap_arguments[index + 1], argument)
            )
    for index, argument in enumerate(payload):
        if argument == "--fd":
            if index + 1 >= len(payload):
                fail("pv-adverb --fd is missing its value")
            descriptors.add(parse_nonnegative_fd(payload[index + 1], "--fd"))
        elif argument.startswith("--fd="):
            descriptors.add(parse_nonnegative_fd(argument[5:], "--fd"))
        elif argument.startswith("--assign-fd="):
            assignment = argument[12:]
            destination, separator, source = assignment.partition("=")
            if not separator:
                fail("invalid pv-adverb --assign-fd")
            parse_nonnegative_fd(destination, "--assign-fd destination")
            descriptors.add(parse_nonnegative_fd(source, "--assign-fd source"))
    ordered = sorted(descriptors)
    if len(ordered) > MAX_FDS:
        fail("Pressure Vessel request references too many fds")
    for descriptor in ordered:
        os.fstat(descriptor)
    return ordered


def encode_frame(payload: dict[str, object]) -> bytes:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if not data or len(data) > MAX_FRAME:
        fail("dispatch frame has an invalid size")
    return data


def send_request(
    connection: socket.socket, payload: dict[str, object], descriptors: list[int]
) -> None:
    data = encode_frame(payload)
    ancillary = []
    if descriptors:
        packed = array.array("i", descriptors)
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, packed)]
    header = struct.pack("!I", len(data))
    sent = connection.sendmsg([header], ancillary)
    if sent <= 0:
        fail("unable to send dispatch header")
    if sent < len(header):
        connection.sendall(header[sent:])
    connection.sendall(data)


def receive_request(connection: socket.socket) -> tuple[dict[str, object], list[int]]:
    header, ancillary, flags, _ = connection.recvmsg(
        4, socket.CMSG_SPACE(MAX_FDS * array.array("i").itemsize)
    )
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        fail("truncated dispatch request")
    while len(header) < 4:
        chunk = connection.recv(4 - len(header))
        if not chunk:
            fail("incomplete dispatch header")
        header += chunk
    length = struct.unpack("!I", header)[0]
    if not 0 < length <= MAX_FRAME:
        fail("dispatch frame has an invalid size")
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            fail("incomplete dispatch frame")
        chunks.extend(chunk)
    descriptors: list[int] = []
    for level, kind, value in ancillary:
        if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
            continue
        received = array.array("i")
        usable = len(value) - (len(value) % received.itemsize)
        received.frombytes(value[:usable])
        descriptors.extend(received.tolist())
    if len(descriptors) > MAX_FDS:
        fail("dispatch request supplied too many fds")
    try:
        payload = json.loads(chunks.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"invalid dispatch JSON: {error}")
    if not isinstance(payload, dict):
        fail("dispatch payload is not an object")
    return payload, descriptors


def send_response(connection: socket.socket, status: int, tracer_pid: int = -1) -> None:
    data = encode_frame({"status": status, "tracer_pid": tracer_pid})
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive_response(connection: socket.socket) -> tuple[int, int]:
    header = connection.recv(4, socket.MSG_WAITALL)
    if len(header) != 4:
        fail("incomplete dispatch response")
    length = struct.unpack("!I", header)[0]
    if not 0 < length <= 4096:
        fail("invalid dispatch response size")
    data = connection.recv(length, socket.MSG_WAITALL)
    if len(data) != length:
        fail("incomplete dispatch response")
    response = json.loads(data.decode("utf-8"))
    status = response.get("status")
    tracer_pid = response.get("tracer_pid", -1)
    if not isinstance(status, int) or not 0 <= status <= 255:
        fail("invalid dispatch response status")
    if not isinstance(tracer_pid, int):
        fail("invalid dispatch tracer pid")
    return status, tracer_pid


def path_has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def plan_mappings(arguments: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    binds: dict[str, str] = {}
    symlinks: dict[str, str] = {}
    for index, argument in enumerate(arguments):
        if argument in BIND_OPTIONS and index + 2 < len(arguments):
            source, destination = arguments[index + 1 : index + 3]
            if source.startswith("/") and destination.startswith("/"):
                binds[destination.rstrip("/") or "/"] = source.rstrip("/") or "/"
        elif argument == "--symlink" and index + 2 < len(arguments):
            target, destination = arguments[index + 1 : index + 3]
            if destination.startswith("/"):
                symlinks[destination.rstrip("/") or "/"] = target
    return binds, symlinks


def translated_path(path: str, binds: dict[str, str], symlinks: dict[str, str]) -> str:
    if not path.startswith("/"):
        fail(f"container path is not absolute: {path}")
    current = str(PurePosixPath(path))
    for _ in range(32):
        candidates = [prefix for prefix in symlinks if path_has_prefix(current, prefix)]
        if candidates:
            prefix = max(candidates, key=len)
            suffix = current[len(prefix) :]
            target = symlinks[prefix]
            if target.startswith("/"):
                current = str(PurePosixPath(target + suffix))
            else:
                current = str(
                    PurePosixPath(prefix).parent
                    / target.lstrip("/")
                    / suffix.lstrip("/")
                )
            continue
        candidates = [prefix for prefix in binds if path_has_prefix(current, prefix)]
        if candidates:
            prefix = max(candidates, key=len)
            suffix = current[len(prefix) :]
            return str(PurePosixPath(binds[prefix] + suffix))
        return current
    fail(f"container path mapping loops: {path}")


def validate_request(payload: dict[str, object], descriptors: list[int]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != KIND:
        fail("unsupported dispatch request")
    for name in ("bwrap_args", "payload_argv", "environment"):
        value = payload.get(name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            fail(f"dispatch {name} is invalid")
    numbers = payload.get("fd_numbers")
    if not isinstance(numbers, list) or not all(isinstance(item, int) for item in numbers):
        fail("dispatch fd_numbers is invalid")
    if len(numbers) != len(descriptors) or len(set(numbers)) != len(numbers):
        fail("dispatch fd metadata does not match received fds")


def tracer_pid(process: int) -> int:
    try:
        lines = Path(f"/proc/{process}/status").read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return -1
    for line in lines:
        if line.startswith("TracerPid:"):
            value = line.split(":", 1)[1].strip()
            return int(value) if value.isdecimal() else -1
    return -1


def selected_runtime(base: Path) -> tuple[Path, Path, str]:
    runtime_root = (base / "runtime/SteamLinuxRuntime_4-arm64-direct/current").resolve(
        strict=True
    )
    glibc_root = (Path.home() / ".local/share/tgcompat/glibc/current").resolve(
        strict=True
    )
    loader = glibc_root / "lib/ld-linux-aarch64.so.1"
    if not loader.is_file() or not os.access(loader, os.X_OK):
        fail(f"patched glibc loader is unavailable: {loader}")
    libraries = ":".join(
        str(path)
        for path in (
            glibc_root / "lib",
            runtime_root / "usr/lib/aarch64-linux-gnu",
            runtime_root / "usr/lib/aarch64-linux-gnu/pulseaudio",
            runtime_root / "usr/lib",
        )
    )
    return runtime_root, loader, libraries


def remap_descriptors(received: list[int], targets: list[int]) -> None:
    if len(received) != len(targets):
        fail("received descriptor count changed before execution")
    minimum = max([64, *received, *targets]) + 1
    temporary: list[tuple[int, int]] = []
    try:
        for source, target in zip(received, targets):
            duplicate = fcntl.fcntl(source, fcntl.F_DUPFD_CLOEXEC, minimum)
            temporary.append((duplicate, target))
            minimum = duplicate + 1
        for source in received:
            os.close(source)
        for duplicate, target in temporary:
            os.dup2(duplicate, target, inheritable=True)
    finally:
        for duplicate, _ in temporary:
            try:
                os.close(duplicate)
            except OSError:
                pass


def run_loader_child(
    loader: Path,
    arguments: list[str],
    environment: dict[str, str],
    descriptors: list[int],
    target_numbers: list[int],
    trace_path: Path | None = None,
    trace_stacks: bool = True,
    working_directory: Path | None = None,
    cpu_affinity: set[int] | None = None,
    match_proton_cpu_topology: bool = False,
    minimum_cpu_affinity_count: int = 0,
) -> tuple[int, int]:
    if minimum_cpu_affinity_count < 0:
        fail("minimum CPU affinity count must not be negative")
    if (
        cpu_affinity is not None
        and minimum_cpu_affinity_count > len(cpu_affinity)
    ):
        fail("minimum CPU affinity count exceeds the requested CPU set")
    if working_directory is not None:
        try:
            working_metadata = working_directory.lstat()
        except FileNotFoundError:
            fail(f"working directory is unavailable: {working_directory}")
        if not stat.S_ISDIR(working_metadata.st_mode) or working_directory.is_symlink():
            fail(f"working directory is unsafe: {working_directory}")
    executable = loader
    execution_arguments = arguments
    execution_environment = environment
    if trace_path is not None:
        prefix = os.environ.get("PREFIX", "")
        strace = Path(prefix) / "bin/strace"
        metadata = strace.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or strace.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or not os.access(strace, os.X_OK)
        ):
            fail(f"Termux strace is unavailable or unsafe: {strace}")
        execution_environment = environment.copy()
        forwarded: list[str] = []
        for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "GLIBC_LD_LIBRARY_PATH"):
            value = execution_environment.pop(name, None)
            if value is not None:
                forwarded.extend(["-E", f"{name}={value}"])
        executable = strace
        trace_arguments = [
            str(strace),
            "-f",
            "-qq",
            "-s",
            "256",
            "-o",
            str(trace_path),
            "-e",
            (
                "trace=%file,%process,%memory"
                if trace_stacks
                else "trace=%process,%signal,%network"
            ),
        ]
        if trace_stacks:
            trace_arguments.append("-k")
        execution_arguments = [
            *trace_arguments,
            *forwarded,
            *arguments,
        ]
    ready_read, ready_write = os.pipe()
    process = os.fork()
    if process == 0:
        try:
            os.close(ready_write)
            if os.read(ready_read, 1) != b"x":
                os._exit(125)
            os.close(ready_read)
            remap_descriptors(descriptors, target_numbers)
            if working_directory is not None:
                os.chdir(working_directory)
            if cpu_affinity is not None:
                affinity_deadline = time.monotonic() + 15.0
                while True:
                    os.sched_setaffinity(0, cpu_affinity)
                    actual_affinity = os.sched_getaffinity(0)
                    if not actual_affinity or not actual_affinity.issubset(
                        cpu_affinity
                    ):
                        os._exit(125)
                    if len(actual_affinity) >= minimum_cpu_affinity_count:
                        break
                    if time.monotonic() >= affinity_deadline:
                        os._exit(125)
                    time.sleep(0.05)
                if match_proton_cpu_topology:
                    execution_environment["PROTON_CPU_TOPOLOGY"] = (
                        f"{len(actual_affinity)}:"
                        + ",".join(str(cpu) for cpu in sorted(actual_affinity))
                    )
                elif actual_affinity != cpu_affinity:
                    os._exit(125)
            os.execve(executable, execution_arguments, execution_environment)
        except BaseException:
            os._exit(125)
    os.close(ready_read)
    observed_tracer = tracer_pid(process)
    os.write(ready_write, b"x")
    os.close(ready_write)
    _, wait_status = os.waitpid(process, 0)
    if observed_tracer != 0:
        return 125, observed_tracer
    if os.WIFEXITED(wait_status):
        return os.WEXITSTATUS(wait_status), observed_tracer
    if os.WIFSIGNALED(wait_status):
        return 128 + os.WTERMSIG(wait_status), observed_tracer
    return 125, observed_tracer


def require_full_startup_topology() -> bool:
    mode = os.environ.get("STEAM_ARM64_DIRECT_STARTUP_TOPOLOGY", "available")
    if mode not in ("available", "full"):
        fail(
            "STEAM_ARM64_DIRECT_STARTUP_TOPOLOGY must be available or full"
        )
    return mode == "full"


def runtime_true_from_plan(base: Path, payload: dict[str, object]) -> tuple[Path, Path, str]:
    bwrap_arguments = payload["bwrap_args"]
    payload_arguments = payload["payload_argv"]
    assert isinstance(bwrap_arguments, list)
    assert isinstance(payload_arguments, list)
    if "--" not in payload_arguments:
        fail("pv-adverb payload has no command boundary")
    boundary = payload_arguments.index("--")
    command = payload_arguments[boundary + 1 :]
    if command != ["/bin/true"]:
        fail("direct dispatcher smoke accepts only /bin/true")
    binds, symlinks = plan_mappings(bwrap_arguments)
    program = Path(translated_path(command[0], binds, symlinks)).resolve(strict=True)
    runtime_root, loader, libraries = selected_runtime(base)
    expected = (runtime_root / "usr/bin/true").resolve(strict=True)
    if program != expected or not program.is_file() or not os.access(program, os.X_OK):
        fail(f"translated smoke payload is not Runtime true: {program}")
    return program, loader, libraries


def clean_loader_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "GLIBC_LD_LIBRARY_PATH"):
        environment.pop(name, None)
    return environment


def request_environment(payload: dict[str, object]) -> dict[str, str]:
    entries = payload["environment"]
    assert isinstance(entries, list)
    environment: dict[str, str] = {}
    for entry in entries:
        name, separator, value = entry.partition("=")
        if not separator or not ENVIRONMENT_NAME.fullmatch(name):
            fail("dispatch environment contains an invalid assignment")
        environment[name] = value
    for name in (
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "GLIBC_LD_LIBRARY_PATH",
        "TGCOMPAT_LD_SO",
        "TGCOMPAT_LIBRARY_PATH",
        "TGCOMPAT_EXEC_LD_PRELOAD",
        "TGCOMPAT_PROC_SELF_EXE",
        "TGCOMPAT_USERFAULTFD_ENOSYS",
        "BVB_VULKAN_TRACE_FILE",
        "STEAM_ARM64_VULKAN_TRACE_PRELOAD",
        "STEAM_ARM64_VULKAN_TRACE_FILE",
        "BVB_COMMAND_STREAM",
        "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM",
        "TOMB_RAIDER_BVB_COMMAND_STREAM",
        "BVB_MAPPED_MEMORY",
        "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY",
        "TOMB_RAIDER_BVB_MAPPED_MEMORY",
        "BVB_DESCRIPTOR_JOURNAL",
        "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL",
        "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL",
        "BVB_FIRST_REJECTION_DIAGNOSTIC",
        "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC",
        "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC",
        "BVB_ICD_DIAGNOSTICS",
        "TOMB_RAIDER_BVB_ICD_DIAGNOSTICS",
        "VK_LOADER_DEBUG",
        "BVB_FRAME_PROFILE",
        "TOMB_RAIDER_BVB_FRAME_PROFILE",
        "TGCOMPAT_RAKNET_RECV_SLEEP_US",
        "STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US",
        "TOMB_RAIDER_RAKNET_RECV_SLEEP_US",
        "FEX_ENABLECODECACHINGWIP",
        "FEX_APP_CACHE_LOCATION",
        "STEAM_ARM64_DIRECT_FEX_CODE_CACHE",
        "TOMB_RAIDER_FEX_CODE_CACHE",
        "FEX_SMC_CHECKS",
        "STEAM_ARM64_DIRECT_FEX_SMC_CHECKS",
        "TOMB_RAIDER_FEX_SMC_CHECKS",
        "DXVK_CONFIG",
        "DXVK_CONFIG_FILE",
        "WINEDLLPATH",
        "STEAMCLIENTTERMUX_DXVK_VARIANT",
        "STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS",
        "STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS",
        "TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS",
        "STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS",
        "STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS",
        "TOMB_RAIDER_DXVK_COMPILER_THREADS",
        "STEAM_ARM64_DIRECT_DXVK_VARIANT",
        "STEAM_ARM64_BWRAP_DXVK_VARIANT",
        "TOMB_RAIDER_DXVK_VARIANT",
        "STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET",
        "TOMB_RAIDER_BENCHMARK_PRESET",
    ):
        environment.pop(name, None)
    return environment


def tombraider_benchmark_arguments(base: Path, preset: str) -> list[str]:
    if preset == "registry":
        return ["-benchmark"]
    try:
        resolution, quality = preset.split("-", 1)
        width, height = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
        }[resolution]
        registry_quality = (
            preset == "1080p-ultra-no-tessellation-ssao1-dof1-lod3"
        )
        overrides = []
        if quality == "ultra-no-tessellation-ssao1-dof1-lod3":
            quality = "ultra"
            overrides = [
                "EnableTessellation = 0",
                "SSAOMode = 1",
                "DOFQuality = 1",
                "LODScale = 3",
            ]
        if quality == "ultra-no-tessellation-ssao1-dof1":
            quality = "ultra"
            overrides = [
                "EnableTessellation = 0",
                "SSAOMode = 1",
                "DOFQuality = 1",
            ]
        if quality == "ultra-no-tessellation-ssao1":
            quality = "ultra"
            overrides = ["EnableTessellation = 0", "SSAOMode = 1"]
        if quality == "ultra-no-tessellation":
            quality = "ultra"
            overrides = ["EnableTessellation = 0"]
        quality_level = {"high": 2, "ultra": 3, "ultimate": 4}[quality]
    except (KeyError, ValueError):
        fail(
            "STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET must be "
            "registry or a supported resolution-quality pair"
        )
    benchmark_ini = base / "run" / f"tombraider-benchmark-{preset}.ini"
    try:
        metadata = benchmark_ini.lstat()
        contents = benchmark_ini.read_bytes()
    except OSError as error:
        fail(f"controlled Tomb Raider benchmark INI is unavailable: {error}")
    expected = (
        ("" if registry_quality else f"QualityLevel = {quality_level}\n")
        + "Fullscreen = 1\n"
        "ExclusiveFullscreen = 1\n"
        "VSyncMode = 0\n"
        f"FullscreenWidth = {width}\n"
        f"FullscreenHeight = {height}\n"
        "FullscreenRefreshRate = 60\n"
        "EnableMotionBlur = 0\n"
        + (
            "" if registry_quality else "".join(f"{line}\n" for line in overrides)
        )
    ).encode()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or benchmark_ini.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or contents != expected
    ):
        fail(f"controlled Tomb Raider benchmark INI failed validation: {benchmark_ini}")
    windows_path = "Z:" + str(benchmark_ini).replace("/", "\\")
    return ["-benchmarkini", windows_path]


def validated_tombraider_command(
    base: Path,
    payload_arguments: list[str],
    benchmark: bool = False,
    benchmark_preset: str | None = None,
) -> tuple[Path, Path]:
    if "--" not in payload_arguments:
        fail("Tomb Raider payload has no command boundary")
    boundary = payload_arguments.index("--")
    command = payload_arguments[boundary + 1 :]
    proton = (
        base
        / "client/steamapps/common/Proton 11.0 (ARM64)/proton"
    )
    game = (
        base
        / "removable-library/steamapps/common/Tomb Raider/TombRaider.exe"
    )
    game_arguments = ["-nolauncher"]
    if benchmark:
        if benchmark_preset is None:
            benchmark_preset = os.environ.get(
                "STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET", "registry"
            )
        game_arguments.extend(
            tombraider_benchmark_arguments(base, benchmark_preset)
        )
    expected = [str(proton), "waitforexitandrun", str(game), *game_arguments]
    if command != expected:
        fail("direct Proton smoke received an unexpected game command")
    return proton, game


def validate_owned_executable(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        fail(f"validated {description} executable is unavailable: {path}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not os.access(path, os.X_OK)
    ):
        fail(f"validated {description} executable is unsafe: {path}")


def validate_removable_windows_file(path: Path, description: str) -> None:
    """Validate an exact PE path without applying Linux FUSE access bits."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        fail(f"validated {description} executable is unavailable: {path}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_size <= 0
    ):
        fail(f"validated {description} file is unsafe: {path}")


def validate_runtime_executable(
    path: Path, runtime_root: Path, description: str
) -> None:
    """Allow a Runtime-owned version symlink that cannot escape its root."""
    try:
        metadata = path.lstat()
        resolved_root = runtime_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (FileNotFoundError, ValueError):
        fail(f"validated {description} executable escapes its Runtime: {path}")
    if metadata.st_uid != os.geteuid():
        fail(f"validated {description} link has an unexpected owner: {path}")
    validate_owned_executable(resolved, description)


def proton_smoke_command(
    base: Path, runtime_root: Path, proton: Path, command_mode: str
) -> list[str]:
    runtime_python = runtime_root / "usr/bin/python3"
    if not runtime_python.is_file() or not os.access(runtime_python, os.X_OK):
        fail(f"Runtime Python is unavailable: {runtime_python}")
    if not proton.is_file() or not os.access(proton, os.X_OK):
        fail(f"validated Proton entry point is unavailable: {proton}")
    if command_mode == "proton-entry":
        return [str(runtime_python), str(proton), "steamclienttermux-probe"]
    if command_mode in ("proton-cmd", "proton-arm64-cmd"):
        architecture = (
            "x86_64-windows"
            if command_mode == "proton-cmd"
            else "aarch64-windows"
        )
        command = (
            base
            / "client/steamapps/common/Proton 11.0 (ARM64)"
            / f"files/lib/wine/{architecture}/cmd.exe"
        )
        if not command.is_file() or command.is_symlink():
            fail(f"validated Proton command is unavailable: {command}")
        return [
            str(runtime_python),
            str(proton),
            "waitforexitandrun",
            str(command),
            "/d",
            "/c",
            "exit",
            "/b",
            "0",
        ]
    fail(f"unsupported Proton smoke mode: {command_mode}")


def proton_smoke_environment(
    command_mode: str, diagnostics: bool = False
) -> dict[str, str]:
    if command_mode == "proton-entry":
        return {}
    if command_mode in (
        "proton-cmd",
        "proton-arm64-cmd",
        "fex-offline-compile",
        "tombraider",
        "tombraider-benchmark",
    ):
        if diagnostics:
            return {
                "WINEDEBUG": (
                    "+timestamp,+pid,+tid,+process,+module,+loaddll,+seh,+vulkan,"
                    "+winsock,+wininet,+winhttp,+iphlpapi,+nsi,"
                    "+secur32,+schannel"
                )
            }
        return {"WINEDEBUG": "-all"}
    fail(f"unsupported Proton smoke mode: {command_mode}")


def direct_audio_environment(base: Path, runtime_root: Path) -> dict[str, str]:
    alsa_data = runtime_root / "usr/share/alsa"
    alsa_config = alsa_data / "alsa.conf"
    pulse_config = alsa_data / "alsa.conf.d/50-pulseaudio.conf"
    plugin_directory = runtime_root / "usr/lib/aarch64-linux-gnu/alsa-lib"
    for path, description in (
        (alsa_config, "Runtime ALSA configuration"),
        (pulse_config, "Runtime PulseAudio ALSA configuration"),
    ):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            fail(f"{description} is unavailable: {path}")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_size <= 0
        ):
            fail(f"{description} is unsafe: {path}")
    try:
        plugin_metadata = plugin_directory.lstat()
    except FileNotFoundError:
        fail(f"Runtime ALSA plugin directory is unavailable: {plugin_directory}")
    if (
        not stat.S_ISDIR(plugin_metadata.st_mode)
        or plugin_directory.is_symlink()
    ):
        fail(f"Runtime ALSA plugin directory is unsafe: {plugin_directory}")

    run = private_directory(
        base / "run/native-runtime-dispatch", "Runtime dispatch directory", create=True
    )
    direct_config = run / "alsa-direct.conf"
    if direct_config.exists() or direct_config.is_symlink():
        metadata = direct_config.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
            or direct_config.is_symlink()
        ):
            fail(f"refusing unsafe direct ALSA configuration: {direct_config}")
    content = (
        f"<{alsa_config}>\n"
        f"<{pulse_config}>\n"
        "pcm.!default {\n"
        "    type pulse\n"
        "}\n"
        "ctl.!default {\n"
        "    type pulse\n"
        "}\n"
    ).encode("utf-8")
    descriptor = os.open(
        direct_config,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_TRUNC
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(content):
            offset += os.write(descriptor, content[offset:])
    finally:
        os.close(descriptor)
    return {
        "ALSA_CONFIG_PATH": str(direct_config),
        "ALSA_CONFIG_DIR": str(alsa_data),
        "ALSA_PLUGIN_DIR": str(plugin_directory),
    }


def direct_dxvk_environment(base: Path) -> dict[str, str]:
    logs = private_directory(base / "logs", "Steam log directory", create=True)
    directory = Path(tempfile.mkdtemp(prefix="dxvk-direct-", dir=logs))
    directory.chmod(0o700)
    private_directory(directory, "Direct DXVK log directory")
    print(f"DXVK_LOG_PATH={directory}", flush=True)
    return {
        "DXVK_LOG_LEVEL": "info",
        "DXVK_LOG_PATH": str(directory),
    }


def direct_game_environment(
    base: Path, runtime_root: Path, diagnostics: bool = False
) -> dict[str, str]:
    environment = direct_audio_environment(base, runtime_root)
    environment["TZ"] = "UTC0"
    if diagnostics:
        environment.update(direct_dxvk_environment(base))
    return environment


DIRECT_FEX_KEYS = {
    "FEX_MAXINST",
    "FEX_PROFILESTATS",
    "FEX_DISABLEL2CACHE",
    "FEX_DYNAMICL1CACHE",
    "FEX_X87REDUCEDPRECISION",
    "FEX_MULTIBLOCK",
    "FEX_VECTORTSOENABLED",
    "FEX_MEMCPYSETTSOENABLED",
    "FEX_SMALLTSCSCALE",
    "FEX_SMC_CHECKS",
    "FEX_VOLATILEMETADATA",
    "FEX_MONOHACKS",
    "FEX_HIDEHYPERVISORBIT",
    "FEX_TSOENABLED",
    "FEX_HALFBARRIERTSOENABLED",
    "STEAM_FEX_MULTIBLOCK",
    "STEAM_FEX_TSOENABLED",
    "STEAM_ARM64_FEX_PROFILE",
}


def apply_direct_fex_profile(environment: dict[str, str], profile: str) -> None:
    if profile not in ("proton", "safe", "fast"):
        fail(f"unsupported direct FEX profile: {profile}")
    for name in DIRECT_FEX_KEYS:
        environment.pop(name, None)
    environment["STEAM_ARM64_FEX_PROFILE"] = profile
    if profile == "proton":
        return
    environment.update(
        {
            "FEX_MAXINST": "5000",
            "FEX_PROFILESTATS": "0",
            "FEX_DISABLEL2CACHE": "0",
            "FEX_DYNAMICL1CACHE": "0",
            "FEX_X87REDUCEDPRECISION": "1",
            "FEX_MULTIBLOCK": "1",
            "FEX_VECTORTSOENABLED": "0",
            "FEX_MEMCPYSETTSOENABLED": "0",
            "FEX_SMALLTSCSCALE": "1",
            "FEX_SMC_CHECKS": "mtrack",
            "FEX_VOLATILEMETADATA": "1",
            "FEX_MONOHACKS": "1",
            "FEX_HIDEHYPERVISORBIT": "0",
            "FEX_TSOENABLED": "0" if profile == "fast" else "1",
            "FEX_HALFBARRIERTSOENABLED": "0" if profile == "fast" else "1",
            "STEAM_FEX_MULTIBLOCK": "1",
            "STEAM_FEX_TSOENABLED": "0" if profile == "fast" else "1",
        }
    )
def validated_proc_net_shadow(base: Path) -> Path:
    shadow = private_directory(
        base / "config/proc-net", "synthetic proc-net directory"
    )
    expected = {"route", "ipv6_route"}
    try:
        entries = {entry.name for entry in shadow.iterdir()}
    except OSError as error:
        fail(f"cannot scan synthetic proc-net directory: {error}")
    if entries != expected:
        fail("synthetic proc-net directory has unexpected entries")
    for name in sorted(expected):
        path = shadow / name
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            fail(f"synthetic proc-net file is unavailable: {path}")
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
        ):
            fail(f"synthetic proc-net file is unsafe: {path}")
    return shadow


def validated_proc_stat_shadow(base: Path) -> Path:
    shadow = base / "config/proc-stat"
    try:
        metadata = shadow.lstat()
    except FileNotFoundError:
        fail(f"synthetic proc-stat file is unavailable: {shadow}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or shadow.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or metadata.st_size < 1
        or metadata.st_size > 1024 * 1024
    ):
        fail(f"synthetic proc-stat file is unsafe: {shadow}")
    try:
        lines = shadow.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        fail(f"cannot read synthetic proc-stat file: {error}")
    cpu_rows: list[int] = []
    aggregate_seen = False
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "cpu":
            if aggregate_seen or len(fields) < 5:
                fail("synthetic proc-stat has an invalid aggregate CPU row")
            aggregate_seen = True
        elif re.fullmatch(r"cpu[0-9]+", fields[0]):
            cpu_rows.append(int(fields[0][3:]))
        else:
            continue
        if any(not value.isdecimal() for value in fields[1:]):
            fail("synthetic proc-stat CPU row has a non-decimal field")
    if (
        not aggregate_seen
        or not cpu_rows
        or len(cpu_rows) > 256
        or cpu_rows != list(range(len(cpu_rows)))
    ):
        fail("synthetic proc-stat CPU rows are incomplete or non-sequential")
    return shadow


def run_final_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    program, loader, libraries = runtime_true_from_plan(base, payload)
    arguments = [
        str(loader),
        "--inhibit-cache",
        "--library-path",
        libraries,
        str(program),
    ]
    return run_loader_child(
        loader,
        arguments,
        clean_loader_environment(),
        descriptors,
        payload["fd_numbers"],
    )


def pv_smoke_invocation(
    base: Path,
    payload: dict[str, object],
    command_mode: str = "runtime-true",
    diagnostics: bool = False,
) -> tuple[Path, list[str], dict[str, str]]:
    final_path_prefix: Path | None = None
    fex_offline_root: Path | None = None
    runtime_root, loader, runtime_libraries = selected_runtime(base)
    proc_net_shadow = validated_proc_net_shadow(base)
    proc_stat_shadow = validated_proc_stat_shadow(base)
    bwrap_arguments = payload["bwrap_args"]
    payload_arguments = payload["payload_argv"]
    assert isinstance(bwrap_arguments, list)
    assert isinstance(payload_arguments, list)
    if "--" not in payload_arguments:
        fail("pv-adverb payload has no command boundary")
    binds, symlinks = plan_mappings(bwrap_arguments)
    boundary = payload_arguments.index("--")
    pv_path = Path(translated_path(payload_arguments[0], binds, symlinks))
    expected_pv = (
        base
        / "client/steamapps/common/SteamLinuxRuntime_4-arm64/pressure-vessel"
        / "libexec/steam-runtime-tools-0/pv-adverb"
    )
    if not pv_path.is_file() or not os.access(pv_path, os.X_OK):
        fail(f"translated pv-adverb is unavailable: {pv_path}")
    if not expected_pv.exists() or not os.path.samefile(pv_path, expected_pv):
        fail(f"translated pv-adverb is unexpected: {pv_path}")
    pv_library = (
        expected_pv.parent.parent.parent
        / "lib/aarch64-linux-gnu/steam-runtime-tools-0"
    )
    glibc_library, separator, remaining_libraries = runtime_libraries.partition(":")
    if not separator:
        fail("Runtime library path is incomplete")
    libraries = f"{glibc_library}:{pv_library}:{remaining_libraries}"
    rewritten = [str(pv_path)]
    index = 1
    removed_flags = {"--generate-locales"}
    removed_pairs = {
        "--regenerate-ld.so-cache",
        "--add-ld.so-path",
        "--set-ld-library-path",
        "--overrides-path",
    }
    while index < boundary:
        argument = payload_arguments[index]
        if argument in removed_flags:
            index += 1
            continue
        if argument in removed_pairs:
            if index + 1 >= boundary:
                fail(f"pv-adverb option is missing its value: {argument}")
            index += 2
            continue
        if argument.startswith("--prefix="):
            rewritten.append(f"--prefix={expected_pv.parent.parent.parent}")
        else:
            rewritten.append(argument)
        index += 1
    if command_mode == "runtime-true":
        program, _, _ = runtime_true_from_plan(base, payload)
        command = [str(program)]
        preserve_assignments = True
    elif command_mode in (
        "proton-entry",
        "proton-cmd",
        "proton-arm64-cmd",
        "fex-offline-compile",
        "tombraider",
        "tombraider-benchmark",
    ):
        benchmark = command_mode == "tombraider-benchmark"
        benchmark_preset = os.environ.get(
            "STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET", "registry"
        )
        proton, game = validated_tombraider_command(
            base,
            payload_arguments,
            benchmark=benchmark,
            benchmark_preset=benchmark_preset,
        )
        final_path_prefix = proton.parent
        if command_mode in ("tombraider", "tombraider-benchmark"):
            runtime_python = runtime_root / "usr/bin/python3"
            validate_runtime_executable(
                runtime_python, runtime_root, "Runtime Python"
            )
            validate_owned_executable(proton, "Proton entry point")
            validate_removable_windows_file(game, "Tomb Raider")
            command = [
                str(runtime_python),
                str(proton),
                "waitforexitandrun",
                str(game),
                "-nolauncher",
                *(
                    tombraider_benchmark_arguments(base, benchmark_preset)
                    if benchmark
                    else []
                ),
            ]
            preserve_assignments = True
        elif command_mode == "fex-offline-compile":
            runtime_python = runtime_root / "usr/bin/python3"
            validate_runtime_executable(
                runtime_python, runtime_root, "Runtime Python"
            )
            validate_owned_executable(proton, "Proton entry point")
            compiler = validated_fex_offline_compiler(base)
            fex_offline_root = validated_fex_offline_root(
                base, before_compile=True
            )
            command = [
                str(runtime_python),
                str(proton),
                "waitforexitandrun",
                str(compiler),
                "process-all",
            ]
            preserve_assignments = True
        else:
            command = proton_smoke_command(base, runtime_root, proton, command_mode)
            preserve_assignments = False
    else:
        fail(f"unsupported pv-adverb command mode: {command_mode}")
    if not preserve_assignments:
        rewritten = [
            argument
            for argument in rewritten
            if not argument.startswith("--assign-fd=")
        ]
    rewritten.extend(["--set-ld-library-path", libraries, "--", *command])
    compat_repo = Path.home() / "workspace/termux-glibc-compat"
    entry_preloads = [
        base / "compat-bin/steam-arm64-native-tmp.so",
        compat_repo / "build/libtgcompat-android-root.so",
        compat_repo / "build/libtgcompat-exec.so",
        compat_repo / "build/libtgcompat-robust.so",
        compat_repo / "build/libtgcompat-mprotect.so",
    ]
    if any(not path.is_file() for path in entry_preloads):
        fail("pv-adverb compatibility preload is unavailable")
    child_preload_profile = os.environ.get(
        "STEAM_ARM64_DIRECT_CHILD_PRELOAD", "full"
    )
    vulkan_trace = validated_vulkan_trace(base)
    raknet_recv_backoff = validated_raknet_recv_backoff(base, command_mode)
    if child_preload_profile == "full":
        child_preloads = entry_preloads
        final_preloads = None
    elif child_preload_profile in ("lean", "lean-tmp-only", "lean-debug-wait"):
        child_preloads = [
            entry_preloads[0],
            entry_preloads[2],
            entry_preloads[3],
        ]
        if child_preload_profile == "lean-tmp-only":
            final_preloads = [entry_preloads[0]]
        else:
            final_preloads = [
                entry_preloads[0],
                entry_preloads[1],
                entry_preloads[3],
                entry_preloads[4],
            ]
        if child_preload_profile == "lean-debug-wait":
            debug_wait = base / "compat-bin/steam-arm64-debug-wait.so"
            if not debug_wait.is_file() or debug_wait.is_symlink():
                fail("Tomb Raider debug-wait preload is unavailable")
            final_preloads.append(debug_wait)
        if final_path_prefix is None:
            fail("lean child preload requires a validated Proton path")
    else:
        fail(
            "STEAM_ARM64_DIRECT_CHILD_PRELOAD must be full, lean, "
            "lean-tmp-only, or lean-debug-wait"
        )
    if vulkan_trace is not None:
        if final_preloads is None:
            fail("Vulkan tracing requires a lean final-process preload profile")
        final_preloads.append(vulkan_trace[0])
    if raknet_recv_backoff is not None:
        if final_preloads is None:
            fail("RakNet receive backoff requires a lean final-process preload")
        final_preloads.append(raknet_recv_backoff[0])
    entry_preload = ":".join(str(path) for path in entry_preloads)
    child_preload = ":".join(str(path) for path in child_preloads)
    final_preload = (
        None
        if final_preloads is None
        else ":".join(str(path) for path in final_preloads)
    )
    environment = request_environment(payload)
    if command_mode in (
        "proton-entry",
        "proton-cmd",
        "proton-arm64-cmd",
        "fex-offline-compile",
        "tombraider",
        "tombraider-benchmark",
    ):
        environment.update(proton_smoke_environment(command_mode, diagnostics))
    if command_mode == "fex-offline-compile":
        assert fex_offline_root is not None
        apply_direct_fex_profile(environment, "safe")
        # The compiler needs the target cache location, but enabling runtime
        # recording here makes its own Wine/FEX bootstrap deposit a zero-byte
        # steam.exe map into codemap/new before process-all can consume the
        # real game maps.
        environment.pop("FEX_ENABLECODECACHINGWIP", None)
        environment["FEX_APP_CACHE_LOCATION"] = f"{fex_offline_root}/"
    if command_mode in ("tombraider", "tombraider-benchmark"):
        environment.update(
            direct_game_environment(base, runtime_root, diagnostics)
        )
        direct_fex_profile = os.environ.get("STEAM_ARM64_DIRECT_FEX_PROFILE")
        if direct_fex_profile is not None:
            apply_direct_fex_profile(environment, direct_fex_profile)
        apply_fex_code_cache(environment, base, command_mode)
        apply_fex_smc_checks(environment, command_mode)
        apply_dxvk_relaxed_graphics_barriers(environment, command_mode)
        apply_dxvk_compiler_threads(environment, command_mode)
        apply_dxvk_variant(environment, base, command_mode)
    prefix = os.environ.get("PREFIX", "")
    if not prefix.startswith("/"):
        fail("Termux PREFIX is unavailable to the direct dispatcher")
    vulkan_icd = validated_host_vulkan_icd(base)
    environment.update(
        {
            "LD_PRELOAD": entry_preload,
            "TGCOMPAT_ANDROID_ROOT_O_PATH": "1",
            "TGCOMPAT_PROC_NET": str(proc_net_shadow),
            "TGCOMPAT_PROC_STAT": str(proc_stat_shadow),
            "TGCOMPAT_PROC_SELF_EXE": str(pv_path),
            "TGCOMPAT_LD_SO": str(loader),
            "TGCOMPAT_LIBRARY_PATH": libraries,
            "TGCOMPAT_EXEC_LD_PRELOAD": child_preload,
            "TGCOMPAT_EXEC_SHELL": str(runtime_root / "usr/bin/sh"),
            "TGCOMPAT_USERFAULTFD_ENOSYS": "1",
            "STEAM_ARM64_TMP_ROOT": prefix + "/tmp",
            "STEAM_ARM64_SHM_ROOT": str(base / "run/native-steam/shm"),
            "STEAM_ARM64_LINUX_ROOT": str(
                Path(prefix) / "var/lib/proot-distro/containers/debian/rootfs"
            ),
            "PATH": ":".join(
                (
                    str(base / "compat-bin"),
                    str(runtime_root / "usr/bin"),
                    str(runtime_root / "usr/sbin"),
                    prefix + "/bin",
                )
            ),
            "VK_DRIVER_FILES": str(vulkan_icd),
            "VK_ICD_FILENAMES": str(vulkan_icd),
        }
    )
    environment.update(bvb_vulkan_environment())
    if raknet_recv_backoff is not None:
        environment.update(raknet_recv_backoff[1])
    if final_preload is not None and final_path_prefix is not None:
        environment.update(
            {
                "TGCOMPAT_EXEC_FINAL_PATH_PREFIX": str(final_path_prefix) + "/",
                "TGCOMPAT_EXEC_FINAL_LD_PRELOAD": final_preload,
                "TGCOMPAT_EXEC_FINAL_PROC_SELF_EXE": "",
            }
        )
    if vulkan_trace is not None:
        environment["BVB_VULKAN_TRACE_FILE"] = str(vulkan_trace[1])
    loader_arguments = [
        str(loader),
        "--inhibit-cache",
        "--library-path",
        libraries,
        "--argv0",
        str(pv_path),
        *rewritten,
    ]
    return loader, loader_arguments, environment


def run_pv_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(base, payload)
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_proton_entry_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-entry"
    )
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_proton_cmd_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-cmd"
    )
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def direct_diagnostics_enabled() -> bool:
    diagnostics = os.environ.get("STEAM_ARM64_DIRECT_DIAGNOSTICS", "0")
    if diagnostics not in ("0", "1"):
        fail("STEAM_ARM64_DIRECT_DIAGNOSTICS must be 0 or 1")
    return diagnostics == "1"


def run_proton_arm64_cmd_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    diagnostics = direct_diagnostics_enabled()
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-arm64-cmd", diagnostics
    )
    trace_path = None
    if diagnostics:
        logs = private_directory(base / "logs", "Steam log directory")
        trace_path = logs / f"proton-arm64-wine-{os.getpid()}.strace"
        print(f"STRACE_LOG={trace_path}", flush=True)
    return run_loader_child(
        loader,
        arguments,
        environment,
        descriptors,
        payload["fd_numbers"],
        trace_path,
    )


def run_fex_offline_compile(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base,
        payload,
        "fex-offline-compile",
        direct_diagnostics_enabled(),
    )
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_tombraider(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    wait_for_direct_start_gate(base)
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "tombraider", direct_diagnostics_enabled()
    )
    return run_loader_child(
        loader,
        arguments,
        environment,
        descriptors,
        payload["fd_numbers"],
        working_directory=(
            base / "removable-library/steamapps/common/Tomb Raider"
        ),
        cpu_affinity=set(range(8)),
        match_proton_cpu_topology=True,
        minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0),
    )


def run_tombraider_benchmark(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    wait_for_direct_start_gate(base)
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "tombraider-benchmark", direct_diagnostics_enabled()
    )
    return run_loader_child(
        loader,
        arguments,
        environment,
        descriptors,
        payload["fd_numbers"],
        working_directory=(
            base / "removable-library/steamapps/common/Tomb Raider"
        ),
        cpu_affinity=set(range(8)),
        match_proton_cpu_topology=True,
        minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0),
    )


def run_tombraider_diagnostic(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    wait_for_direct_start_gate(base)
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "tombraider", True
    )
    logs = private_directory(base / "logs", "Steam log directory")
    trace_path = logs / f"tombraider-direct-process-{os.getpid()}.strace"
    print(f"PROCESS_TRACE_LOG={trace_path}", flush=True)
    return run_loader_child(
        loader,
        arguments,
        environment,
        descriptors,
        payload["fd_numbers"],
        trace_path,
        False,
        working_directory=(
            base / "removable-library/steamapps/common/Tomb Raider"
        ),
        cpu_affinity=set(range(8)),
        match_proton_cpu_topology=True,
        minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0),
    )


def verify_peer(connection: socket.socket) -> None:
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    _, uid, _ = struct.unpack("3i", credentials)
    if uid != os.geteuid():
        fail("dispatch peer uid does not match")


def serve(base: Path, mode: str) -> int:
    path = dispatch_socket(base)
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
            fail(f"refusing unsafe existing dispatch socket: {path}")
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    status = 125
    try:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen(1)
        print(f"READY={path}", flush=True)
        connection, _ = listener.accept()
        with connection:
            verify_peer(connection)
            payload, descriptors = receive_request(connection)
            try:
                validate_request(payload, descriptors)
                print(f"REQUEST_RECEIVED=1 FD_COUNT={len(descriptors)}", flush=True)
                if mode == "final-smoke":
                    status, observed_tracer = run_final_smoke(
                        base, payload, descriptors
                    )
                elif mode == "pv-smoke":
                    status, observed_tracer = run_pv_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-entry-smoke":
                    status, observed_tracer = run_proton_entry_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-cmd-smoke":
                    status, observed_tracer = run_proton_cmd_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-arm64-cmd-smoke":
                    status, observed_tracer = run_proton_arm64_cmd_smoke(
                        base, payload, descriptors
                    )
                elif mode == "fex-offline-compile":
                    status, observed_tracer = run_fex_offline_compile(
                        base, payload, descriptors
                    )
                elif mode == "tombraider":
                    status, observed_tracer = run_tombraider(
                        base, payload, descriptors
                    )
                elif mode == "tombraider-benchmark":
                    status, observed_tracer = run_tombraider_benchmark(
                        base, payload, descriptors
                    )
                elif mode == "tombraider-diagnostic":
                    status, observed_tracer = run_tombraider_diagnostic(
                        base, payload, descriptors
                    )
                else:
                    fail(f"unsupported server mode: {mode}")
                print(
                    f"DISPATCH_STATUS={status} TRACER_PID={observed_tracer}",
                    flush=True,
                )
                send_response(connection, status, observed_tracer)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
    finally:
        listener.close()
        if path.exists() and not path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.geteuid():
                path.unlink()
    return status


def delegate_probe(arguments: list[str], base: Path) -> NoReturn:
    selected = os.environ.get("STEAM_ARM64_DIRECT_REAL_BWRAP", "")
    expected = (
        base
        / "runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec"
        / "steam-runtime-tools-0/srt-bwrap"
    )
    if selected != str(expected):
        fail("direct probe delegate is not the expected srt-bwrap")
    metadata = expected.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or expected.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not os.access(expected, os.X_OK)
    ):
        fail(f"direct probe delegate is not protected: {expected}")
    os.execv(expected, [str(expected), *arguments])
    fail("cannot execute direct probe delegate")


def client(arguments: list[str], base: Path) -> int:
    if not any(argument == "--args" or argument.startswith("--args=") for argument in arguments):
        delegate_probe(arguments, base)
    args_fd, _, payload_start = locate_args_fd(arguments)
    bwrap_arguments = read_nul_arguments(args_fd)
    payload_arguments = arguments[payload_start:]
    descriptors = referenced_fd_numbers(bwrap_arguments, payload_arguments)
    request = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "cwd": os.getcwd(),
        "bwrap_args": bwrap_arguments,
        "payload_argv": payload_arguments,
        "environment": [f"{name}={value}" for name, value in os.environ.items()],
        "fd_numbers": descriptors,
    }
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    with connection:
        connection.connect(str(dispatch_socket(base)))
        send_request(connection, request, descriptors)
        status, observed_tracer = receive_response(connection)
    if status == 0:
        print(f"direct Runtime smoke: PASS tracer_pid={observed_tracer}")
    return status


def main() -> int:
    try:
        arguments = sys.argv[1:]
        base_value = os.environ.get("STEAM_ARM64_BASE", str(Path.home() / "steam-arm64"))
        if arguments and arguments[0] == "serve":
            parser = argparse.ArgumentParser()
            parser.add_argument("serve", nargs="?")
            parser.add_argument("--base", default=base_value)
            parser.add_argument(
                "--mode",
                choices=(
                    "final-smoke",
                    "pv-smoke",
                    "proton-entry-smoke",
                    "proton-cmd-smoke",
                    "proton-arm64-cmd-smoke",
                    "fex-offline-compile",
                    "tombraider",
                    "tombraider-benchmark",
                    "tombraider-diagnostic",
                ),
                default="final-smoke",
            )
            options = parser.parse_args(arguments)
            return serve(validated_base(options.base), options.mode)
        if arguments and arguments[0] == "client":
            arguments = arguments[1:]
        return client(arguments, validated_base(base_value))
    except (DispatchError, OSError, ValueError) as error:
        print(f"pressure-vessel-direct-dispatch: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
