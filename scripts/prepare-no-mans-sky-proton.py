#!/usr/bin/env python3
"""Build and verify the contained Proton tool required by No Man's Sky."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile


TOOL_NAME = "steamclienttermux_nms_proton_11_arm64_45a9ed5f"
TOOL_DIRECTORY = "steamclienttermux-nms-proton-11-arm64-45a9ed5f"
SOURCE_VERSION = b"1787334524 proton-11.0-2-arm64\n"
DLL_RELATIVE = Path("files/lib/wine/aarch64-windows/lsteamclient.dll")
NTOSKRNL_RELATIVE = Path("files/lib/wine/aarch64-windows/ntoskrnl.exe")
LOADER_CHAIN_SHA256 = {
    Path("files/bin-arm64/wine"): (
        "75e9fd2766067c5fe828067bfe54960b04c1a43ac93ab7b234873b1b10a36bbb"
    ),
    Path("files/bin-arm64/wineserver"): (
        "6aea2df358ac81cb00cd57a2e791a5ce21e7576fa78b2480746044dc111589aa"
    ),
    Path("files/lib/wine/aarch64-unix/ntdll.so"): (
        "9c618d49c9926f55d8a28f10c4cfd514d26e654d5bc36a1c639730abf61dd1ff"
    ),
    Path("files/lib/wine/aarch64-unix/wine"): (
        "37231b4f9f54f3fccfa39fa51e659398f4d761a4a97687a783052105be52fa46"
    ),
    Path("files/lib/wine/aarch64-unix/wine-preloader"): (
        "50261d334faf41c5414edfcd8f3d1dfa26f0aa5a15c5efc655fac1c1690d709c"
    ),
}
MARKER_NAME = ".steamclienttermux-nms-proton.json"
OPENVR_SOURCE_RELATIVE = Path(
    "compat-bin/nms-openvr-stub/openvr_api.dll"
)
OPENVR_SHA256 = "4fce1e22a0fe044b86862d45fc007269e1681214229d7d1ff1eedac0ceabfed5"
OPENVR_SIZE = 2048
OPENVR_WINE_BUILTIN_SHA256 = (
    "bebc9793a03038c425ff275c280d217a307044d0b2aeed0691eb58d3f28c8243"
)
OPENVR_WINE_BUILTIN_SIZE = 77824
OPENVR_CANDIDATE_DIRECTORY = "nms-openvr-flat-stub-4fce1e22"
OPENVR_DLL_RELATIVE = Path("aarch64-windows/openvr_api.dll")
OPENVR_MARKER_NAME = ".steamclienttermux-nms-openvr.json"
GAME_OPENVR_RELATIVE = Path(
    "removable-library/steamapps/common/No Man's Sky/Binaries/openvr_api.dll"
)
GAME_OPENVR_BACKUP_NAME = "openvr_api.dll.steamclienttermux-original-bab8ac6e"
GAME_OPENVR_ORIGINAL_SHA256 = (
    "bab8ac6ef64e68a9ca53315b0014d131088584b2efdfa6db511d67ec03cfcb4a"
)
GAME_OPENVR_ORIGINAL_SIZE = 837272
XINPUT_SOURCE_RELATIVE = Path("compat-bin/nms-xinput")
GAME_BINARY_RELATIVE = Path(
    "removable-library/steamapps/common/No Man's Sky/Binaries"
)
XINPUT_DLLS = {
    "xinput1_4.dll": (
        17408,
        "3fc6d898a3f1f0e66ea3b7428409eff3e2abb10e4401aa7209e9d214524e3534",
    ),
    "xinput9_1_0.dll": (
        16896,
        "11e928f5e337680efa6baa6e2a839795a79bd752387b1e0956ea805f1a25fa43",
    ),
}
RUNNING_COMMS = {"steam", "steamwebhelper", "wineserver"}


@dataclass(frozen=True)
class PatchSpec:
    source_sha256: str
    patched_sha256: str
    offset: int
    before: bytes
    after: bytes


NMS_INPUT_PATCH = PatchSpec(
    source_sha256="9d5289451c94e1eb8df5043f7c0341c1d817a74cc43ad1518099281a9c27f7a5",
    patched_sha256="b00a3dcdcfceb60f1b0fc68347558d7933c15ac07bcac5cff703bbdff014501f",
    offset=0x800E8,
    before=bytes.fromhex("7256fe97a0000035"),
    after=bytes.fromhex("2000805202000014"),
)

NMS_NTOSKRNL_DEVICE_MANAGER_PATCH = PatchSpec(
    source_sha256="68d0dad49c977b0e14d4d832668bc2208fb9e2fb7ce6856cfd960286b1a33857",
    patched_sha256="11a47bc7b1a5dd21e457dc87aca4d43873dc83d218691741284aa2ec4f87252e",
    offset=0x2ABA0,
    before=bytes.fromhex("681f8052"),  # mov w8, #0xfb
    after=bytes.fromhex("a81f8052"),   # mov w8, #0xfd
)

NMS_NTOSKRNL_GET_REQUEST_PATCH = PatchSpec(
    source_sha256="11a47bc7b1a5dd21e457dc87aca4d43873dc83d218691741284aa2ec4f87252e",
    patched_sha256="f7852cc100cf9d81e25524197d52f633829124c7dd7979a0964712cd051baf04",
    offset=0x2ACBC,
    before=bytes.fromhex("c91f8052"),  # mov w9, #0xfe
    after=bytes.fromhex("09208052"),   # mov w9, #0x100
)

NMS_NTOSKRNL_OBJECT_POINTER_PATCH = PatchSpec(
    source_sha256="f7852cc100cf9d81e25524197d52f633829124c7dd7979a0964712cd051baf04",
    patched_sha256="d9f25b23654d6928bdafe68b28fbed264d15da52b51778dbaa35dc01315e373b",
    offset=0x2A318,
    before=bytes.fromhex("e91f8052"),  # mov w9, #0xff
    after=bytes.fromhex("29208052"),   # mov w9, #0x101
)


class ToolError(RuntimeError):
    pass


def active_processes(proc_root: Path = Path("/proc")) -> list[tuple[int, str]]:
    result = []
    try:
        entries = proc_root.iterdir()
    except FileNotFoundError:
        return result
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm in RUNNING_COMMS:
            result.append((int(entry.name), comm))
    return sorted(result)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_owned(path: Path, description: str, executable: bool = False) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ToolError(f"{description} is unavailable: {path}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or (executable and not os.access(path, os.X_OK))
    ):
        raise ToolError(f"{description} is unsafe: {path}")
    return metadata


def regular_removable(path: Path, description: str) -> os.stat_result:
    """Validate a file whose FAT-backed mode bits are fixed by Android."""
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ToolError(f"{description} is unavailable: {path}") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ToolError(f"{description} is unsafe: {path}")
    return metadata


def owned_directory(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ToolError(f"{description} is unavailable: {path}") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise ToolError(f"{description} is unsafe: {path}")


def expected_marker(spec: PatchSpec = NMS_INPUT_PATCH) -> dict[str, object]:
    return {
        "loader_chain_sha256": {
            str(path): digest for path, digest in LOADER_CHAIN_SHA256.items()
        },
        "patch_offset": spec.offset,
        "ntoskrnl_protocol_patch_offsets": [
            NMS_NTOSKRNL_DEVICE_MANAGER_PATCH.offset,
            NMS_NTOSKRNL_GET_REQUEST_PATCH.offset,
            NMS_NTOSKRNL_OBJECT_POINTER_PATCH.offset,
        ],
        "patched_ntoskrnl_sha256": (
            NMS_NTOSKRNL_OBJECT_POINTER_PATCH.patched_sha256
        ),
        "patched_lsteamclient_sha256": spec.patched_sha256,
        "schema_version": 6,
        "source_ntoskrnl_sha256": NMS_NTOSKRNL_DEVICE_MANAGER_PATCH.source_sha256,
        "source_lsteamclient_sha256": spec.source_sha256,
        "source_version": SOURCE_VERSION.decode().strip(),
        "tool": TOOL_NAME,
    }


def legacy_marker(spec: PatchSpec = NMS_INPUT_PATCH) -> dict[str, object]:
    """Return the exact schema written before the ntoskrnl correction."""
    return {
        "loader_chain_sha256": {
            str(path): digest for path, digest in LOADER_CHAIN_SHA256.items()
        },
        "patch_offset": spec.offset,
        "patched_lsteamclient_sha256": spec.patched_sha256,
        "schema_version": 3,
        "source_lsteamclient_sha256": spec.source_sha256,
        "source_version": SOURCE_VERSION.decode().strip(),
        "tool": TOOL_NAME,
    }


def manifest() -> bytes:
    return f'''"compatibilitytools"
{{
  "compat_tools"
  {{
    "{TOOL_NAME}"
    {{
      "display_name"        "SteamClientTermux NMS Proton 11 ARM64"
      "install_path"        "."
      "require_tool_appid"  "4185400"
      "from_oslist"         "windows"
      "to_oslist"           "linux"
    }}
  }}
}}
'''.encode()


def validate_source(source: Path, spec: PatchSpec) -> Path:
    owned_directory(source, "stock Proton directory")
    regular_owned(source / "proton", "stock Proton entry point", executable=True)
    version = source / "version"
    regular_owned(version, "stock Proton version")
    if version.read_bytes() != SOURCE_VERSION:
        raise ToolError("stock Proton version is not the reviewed ARM64 build")
    dll = source / DLL_RELATIVE
    metadata = regular_owned(dll, "stock lsteamclient DLL")
    if metadata.st_size <= spec.offset + len(spec.before):
        raise ToolError("stock lsteamclient DLL is truncated")
    if sha256(dll) != spec.source_sha256:
        raise ToolError("stock lsteamclient DLL hash is not reviewed")
    with dll.open("rb") as stream:
        stream.seek(spec.offset)
        if stream.read(len(spec.before)) != spec.before:
            raise ToolError("stock lsteamclient patch site is unexpected")
    ntoskrnl = source / NTOSKRNL_RELATIVE
    metadata = regular_owned(ntoskrnl, "stock Wine ntoskrnl")
    nt_patch = NMS_NTOSKRNL_DEVICE_MANAGER_PATCH
    if metadata.st_size <= nt_patch.offset + len(nt_patch.before):
        raise ToolError("stock Wine ntoskrnl is truncated")
    if sha256(ntoskrnl) != nt_patch.source_sha256:
        raise ToolError("stock Wine ntoskrnl hash is not reviewed")
    with ntoskrnl.open("rb") as stream:
        stream.seek(nt_patch.offset)
        if stream.read(len(nt_patch.before)) != nt_patch.before:
            raise ToolError("stock Wine ntoskrnl patch site is unexpected")
        next_patch = NMS_NTOSKRNL_GET_REQUEST_PATCH
        stream.seek(next_patch.offset)
        if stream.read(len(next_patch.before)) != next_patch.before:
            raise ToolError("stock Wine ntoskrnl request-loop patch site is unexpected")
        pointer_patch = NMS_NTOSKRNL_OBJECT_POINTER_PATCH
        stream.seek(pointer_patch.offset)
        if stream.read(len(pointer_patch.before)) != pointer_patch.before:
            raise ToolError("stock Wine ntoskrnl object-pointer patch site is unexpected")
    for relative, expected_digest in LOADER_CHAIN_SHA256.items():
        loader = source / relative
        regular_owned(loader, f"stock Wine loader {relative}", executable=True)
        if sha256(loader) != expected_digest:
            raise ToolError(f"stock Wine loader hash is not reviewed: {relative}")
    return dll


def validate_tool(tool: Path, spec: PatchSpec = NMS_INPUT_PATCH) -> dict[str, object]:
    owned_directory(tool, "contained NMS Proton directory")
    regular_owned(tool / "proton", "contained Proton entry point", executable=True)
    dll = tool / DLL_RELATIVE
    regular_owned(dll, "contained lsteamclient DLL")
    if sha256(dll) != spec.patched_sha256:
        raise ToolError("contained lsteamclient DLL hash is unexpected")
    with dll.open("rb") as stream:
        stream.seek(spec.offset)
        if stream.read(len(spec.after)) != spec.after:
            raise ToolError("contained lsteamclient patch site is unexpected")
    ntoskrnl = tool / NTOSKRNL_RELATIVE
    regular_owned(ntoskrnl, "contained Wine ntoskrnl")
    nt_patch = NMS_NTOSKRNL_DEVICE_MANAGER_PATCH
    next_patch = NMS_NTOSKRNL_GET_REQUEST_PATCH
    pointer_patch = NMS_NTOSKRNL_OBJECT_POINTER_PATCH
    if sha256(ntoskrnl) != pointer_patch.patched_sha256:
        raise ToolError("contained Wine ntoskrnl hash is unexpected")
    with ntoskrnl.open("rb") as stream:
        stream.seek(nt_patch.offset)
        if stream.read(len(nt_patch.after)) != nt_patch.after:
            raise ToolError("contained Wine ntoskrnl patch site is unexpected")
        stream.seek(next_patch.offset)
        if stream.read(len(next_patch.after)) != next_patch.after:
            raise ToolError("contained Wine ntoskrnl request-loop patch is unexpected")
        stream.seek(pointer_patch.offset)
        if stream.read(len(pointer_patch.after)) != pointer_patch.after:
            raise ToolError("contained Wine ntoskrnl object-pointer patch is unexpected")
    for relative, expected_digest in LOADER_CHAIN_SHA256.items():
        loader = tool / relative
        regular_owned(loader, f"contained Wine loader {relative}", executable=True)
        if sha256(loader) != expected_digest:
            raise ToolError(f"contained Wine loader hash is unexpected: {relative}")
    marker_path = tool / MARKER_NAME
    regular_owned(marker_path, "contained Proton marker")
    try:
        marker = json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError("contained Proton marker is invalid") from error
    if marker != expected_marker(spec):
        raise ToolError("contained Proton marker does not match the reviewed patch")
    manifest_path = tool / "compatibilitytool.vdf"
    regular_owned(manifest_path, "contained Proton manifest")
    if manifest_path.read_bytes() != manifest():
        raise ToolError("contained Proton manifest is unexpected")
    return marker


def validate_legacy_tool(
    tool: Path, source: Path, spec: PatchSpec = NMS_INPUT_PATCH
) -> None:
    """Accept only the exact schema-3 tool that this project previously made."""
    owned_directory(tool, "legacy contained NMS Proton directory")
    regular_owned(tool / "proton", "legacy contained Proton entry point", executable=True)
    dll = tool / DLL_RELATIVE
    regular_owned(dll, "legacy contained lsteamclient DLL")
    if sha256(dll) != spec.patched_sha256:
        raise ToolError("legacy contained lsteamclient DLL hash is unexpected")
    with dll.open("rb") as stream:
        stream.seek(spec.offset)
        if stream.read(len(spec.after)) != spec.after:
            raise ToolError("legacy contained lsteamclient patch site is unexpected")
    ntoskrnl = tool / NTOSKRNL_RELATIVE
    try:
        nt_metadata = ntoskrnl.lstat()
    except FileNotFoundError as error:
        raise ToolError("legacy contained Wine ntoskrnl is unavailable") from error
    source_ntoskrnl = (source / NTOSKRNL_RELATIVE).resolve(strict=True)
    if not stat.S_ISLNK(nt_metadata.st_mode) or ntoskrnl.resolve(strict=True) != source_ntoskrnl:
        raise ToolError("legacy contained Wine ntoskrnl is not the reviewed stock link")
    nt_patch = NMS_NTOSKRNL_DEVICE_MANAGER_PATCH
    if sha256(source_ntoskrnl) != nt_patch.source_sha256:
        raise ToolError("legacy stock Wine ntoskrnl hash is unexpected")
    with source_ntoskrnl.open("rb") as stream:
        stream.seek(nt_patch.offset)
        if stream.read(len(nt_patch.before)) != nt_patch.before:
            raise ToolError("legacy stock Wine ntoskrnl patch site is unexpected")
    for relative, expected_digest in LOADER_CHAIN_SHA256.items():
        loader = tool / relative
        regular_owned(loader, f"legacy contained Wine loader {relative}", executable=True)
        if sha256(loader) != expected_digest:
            raise ToolError(f"legacy contained Wine loader is unexpected: {relative}")
    marker_path = tool / MARKER_NAME
    regular_owned(marker_path, "legacy contained Proton marker")
    try:
        marker = json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError("legacy contained Proton marker is invalid") from error
    if marker != legacy_marker(spec):
        raise ToolError("legacy contained Proton marker is unexpected")
    manifest_path = tool / "compatibilitytool.vdf"
    regular_owned(manifest_path, "legacy contained Proton manifest")
    if manifest_path.read_bytes() != manifest():
        raise ToolError("legacy contained Proton manifest is unexpected")


def openvr_marker() -> dict[str, object]:
    return {
        "dll": str(OPENVR_DLL_RELATIVE),
        "schema_version": 1,
        "sha256": OPENVR_SHA256,
        "size": OPENVR_SIZE,
        "source": str(OPENVR_SOURCE_RELATIVE),
    }


def validate_openvr_candidate(candidate: Path) -> Path:
    owned_directory(candidate, "NMS OpenVR candidate")
    dll = candidate / OPENVR_DLL_RELATIVE
    metadata = regular_owned(dll, "NMS OpenVR compatibility DLL")
    if metadata.st_size != OPENVR_SIZE or sha256(dll) != OPENVR_SHA256:
        raise ToolError("NMS OpenVR compatibility DLL is unexpected")
    marker_path = candidate / OPENVR_MARKER_NAME
    regular_owned(marker_path, "NMS OpenVR marker")
    try:
        marker = json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ToolError("NMS OpenVR marker is invalid") from error
    if marker != openvr_marker():
        raise ToolError("NMS OpenVR marker is unexpected")
    return dll


def prepare_openvr_candidate(base: Path, candidate_root: Path) -> tuple[Path, bool]:
    owned_directory(candidate_root, "candidate directory")
    source_dll = base / OPENVR_SOURCE_RELATIVE
    metadata = regular_owned(source_dll, "NMS flat-screen OpenVR stub")
    if metadata.st_size != OPENVR_SIZE or sha256(source_dll) != OPENVR_SHA256:
        raise ToolError("NMS flat-screen OpenVR stub is unexpected")
    candidate = candidate_root / OPENVR_CANDIDATE_DIRECTORY
    if candidate.exists() or candidate.is_symlink():
        validate_openvr_candidate(candidate)
        return candidate, False
    stage = Path(
        tempfile.mkdtemp(prefix=f".{OPENVR_CANDIDATE_DIRECTORY}.", dir=candidate_root)
    )
    try:
        dll = stage / OPENVR_DLL_RELATIVE
        dll.parent.mkdir(parents=True, mode=0o700)
        shutil.copy2(source_dll, dll)
        dll.chmod(0o600)
        marker = stage / OPENVR_MARKER_NAME
        marker.write_text(json.dumps(openvr_marker(), sort_keys=True) + "\n")
        marker.chmod(0o600)
        validate_openvr_candidate(stage)
        os.replace(stage, candidate)
        descriptor = os.open(candidate_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        if stage.exists() and stage.parent == candidate_root:
            shutil.rmtree(stage)
        raise
    validate_openvr_candidate(candidate)
    return candidate, True


def validate_game_openvr(base: Path) -> tuple[Path, Path]:
    current = base / GAME_OPENVR_RELATIVE
    backup = current.with_name(GAME_OPENVR_BACKUP_NAME)
    current_metadata = regular_removable(current, "active NMS OpenVR DLL")
    backup_metadata = regular_removable(backup, "original NMS OpenVR backup")
    compatible_dlls = {
        (OPENVR_SIZE, OPENVR_SHA256),
        (OPENVR_WINE_BUILTIN_SIZE, OPENVR_WINE_BUILTIN_SHA256),
    }
    if (current_metadata.st_size, sha256(current)) not in compatible_dlls:
        raise ToolError("active NMS OpenVR DLL is not the reviewed compatibility DLL")
    if (
        backup_metadata.st_size != GAME_OPENVR_ORIGINAL_SIZE
        or sha256(backup) != GAME_OPENVR_ORIGINAL_SHA256
    ):
        raise ToolError("original NMS OpenVR backup is unexpected")
    return current, backup


def prepare_game_openvr(base: Path, candidate: Path) -> tuple[Path, bool]:
    source = validate_openvr_candidate(candidate)
    current = base / GAME_OPENVR_RELATIVE
    backup = current.with_name(GAME_OPENVR_BACKUP_NAME)
    if backup.exists() or backup.is_symlink():
        validate_game_openvr(base)
        return current, False
    metadata = regular_removable(current, "stock NMS OpenVR DLL")
    if (
        metadata.st_size != GAME_OPENVR_ORIGINAL_SIZE
        or sha256(current) != GAME_OPENVR_ORIGINAL_SHA256
    ):
        raise ToolError("stock NMS OpenVR DLL is unexpected")
    temporary = current.with_name(f".{current.name}.steamclienttermux-new")
    if temporary.exists() or temporary.is_symlink():
        raise ToolError("stale NMS OpenVR transaction file exists")
    shutil.copy2(source, temporary)
    temporary.chmod(stat.S_IMODE(metadata.st_mode))
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    if temporary.stat().st_size != OPENVR_SIZE or sha256(temporary) != OPENVR_SHA256:
        temporary.unlink()
        raise ToolError("staged NMS OpenVR compatibility DLL is unexpected")
    os.replace(current, backup)
    try:
        os.replace(temporary, current)
    except Exception:
        os.replace(backup, current)
        raise
    descriptor = os.open(current.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    validate_game_openvr(base)
    return current, True


def validate_game_xinput(base: Path) -> list[Path]:
    binary_directory = base / GAME_BINARY_RELATIVE
    result = []
    for name, (expected_size, expected_sha256) in XINPUT_DLLS.items():
        destination = binary_directory / name
        metadata = regular_removable(destination, f"NMS {name}")
        if metadata.st_size != expected_size or sha256(destination) != expected_sha256:
            raise ToolError(f"NMS XInput DLL is unexpected: {destination}")
        result.append(destination)
    return result


def prepare_game_xinput(base: Path) -> tuple[list[Path], bool]:
    source_directory = base / XINPUT_SOURCE_RELATIVE
    binary_directory = base / GAME_BINARY_RELATIVE
    if not binary_directory.is_dir() or binary_directory.is_symlink():
        raise ToolError("NMS binary directory is unavailable")
    changed = False
    for name, (expected_size, expected_sha256) in XINPUT_DLLS.items():
        source = source_directory / name
        source_metadata = regular_owned(source, f"packaged NMS {name}")
        if (
            source_metadata.st_size != expected_size
            or sha256(source) != expected_sha256
        ):
            raise ToolError(f"packaged NMS XInput DLL is unexpected: {source}")
        destination = binary_directory / name
        if destination.exists() or destination.is_symlink():
            metadata = regular_removable(destination, f"active NMS {name}")
            if (
                metadata.st_size != expected_size
                or sha256(destination) != expected_sha256
            ):
                raise ToolError(f"refusing to replace existing NMS DLL: {destination}")
            continue
        temporary = destination.with_name(f".{name}.steamclienttermux-new")
        if temporary.exists() or temporary.is_symlink():
            raise ToolError(f"stale NMS XInput transaction exists: {temporary}")
        shutil.copy2(source, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if temporary.stat().st_size != expected_size or sha256(temporary) != expected_sha256:
            temporary.unlink()
            raise ToolError(f"staged NMS XInput DLL is unexpected: {temporary}")
        os.replace(temporary, destination)
        changed = True
    if changed:
        fsync_directory(binary_directory)
    return validate_game_xinput(base), changed


def replace_binary(
    stage: Path, relative: Path, spec: PatchSpec, description: str
) -> None:
    binary = stage / relative
    metadata = regular_owned(binary, f"staged {description}")
    temporary = binary.with_name(f".{binary.name}.new")
    if temporary.exists() or temporary.is_symlink():
        raise ToolError(f"staged patch temporary already exists: {temporary}")
    with binary.open("rb") as source, temporary.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    temporary.chmod(stat.S_IMODE(metadata.st_mode))
    with temporary.open("r+b") as stream:
        stream.seek(spec.offset)
        if stream.read(len(spec.before)) != spec.before:
            raise ToolError(f"staged {description} patch site changed")
        stream.seek(spec.offset)
        stream.write(spec.after)
        stream.flush()
        os.fsync(stream.fileno())
    if sha256(temporary) != spec.patched_sha256:
        raise ToolError(f"patched {description} hash is unexpected")
    os.replace(temporary, binary)


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def build_tool_stage(
    source: Path, destination_root: Path, spec: PatchSpec
) -> Path:
    stage = Path(
        tempfile.mkdtemp(prefix=f".{TOOL_DIRECTORY}.", dir=destination_root)
    )
    stage.rmdir()
    copied_files = {
        source / "proton",
        source / DLL_RELATIVE,
        source / NTOSKRNL_RELATIVE,
        *(source / relative for relative in LOADER_CHAIN_SHA256),
    }

    def overlay_file(source_name: str, destination_name: str) -> str:
        source_path = Path(source_name)
        destination_path = Path(destination_name)
        if source_path in copied_files:
            return shutil.copy2(source_path, destination_path)
        os.symlink(source_path, destination_path)
        return str(destination_path)

    try:
        shutil.copytree(source, stage, copy_function=overlay_file, symlinks=True)
        replace_binary(stage, DLL_RELATIVE, spec, "lsteamclient DLL")
        replace_binary(
            stage,
            NTOSKRNL_RELATIVE,
            NMS_NTOSKRNL_DEVICE_MANAGER_PATCH,
            "Wine ntoskrnl",
        )
        replace_binary(
            stage,
            NTOSKRNL_RELATIVE,
            NMS_NTOSKRNL_GET_REQUEST_PATCH,
            "Wine ntoskrnl request loop",
        )
        replace_binary(
            stage,
            NTOSKRNL_RELATIVE,
            NMS_NTOSKRNL_OBJECT_POINTER_PATCH,
            "Wine ntoskrnl object pointer",
        )
        marker_path = stage / MARKER_NAME
        marker_path.write_text(json.dumps(expected_marker(spec), sort_keys=True) + "\n")
        marker_path.chmod(0o600)
        manifest_path = stage / "compatibilitytool.vdf"
        manifest_path.write_bytes(manifest())
        manifest_path.chmod(0o600)
        for directory, subdirectories, _files in os.walk(stage):
            Path(directory).chmod(0o700)
            for subdirectory in subdirectories:
                candidate = Path(directory) / subdirectory
                if not candidate.is_symlink():
                    candidate.chmod(0o700)
        validate_tool(stage, spec)
        return stage
    except Exception:
        if stage.exists() and stage.parent == destination_root and stage.name.startswith(
            f".{TOOL_DIRECTORY}."
        ):
            shutil.rmtree(stage)
        raise


def prepare_tool(
    source: Path,
    destination_root: Path,
    spec: PatchSpec = NMS_INPUT_PATCH,
) -> tuple[Path, bool]:
    validate_source(source, spec)
    owned_directory(destination_root, "compatibility-tools directory")
    destination = destination_root / TOOL_DIRECTORY
    if destination.exists() or destination.is_symlink():
        try:
            validate_tool(destination, spec)
            return destination, False
        except ToolError:
            validate_legacy_tool(destination, source, spec)
            stage = build_tool_stage(source, destination_root, spec)
            backup = destination_root / f".{TOOL_DIRECTORY}.schema3-backup"
            if backup.exists() or backup.is_symlink():
                shutil.rmtree(stage)
                raise ToolError(f"stale contained Proton upgrade backup exists: {backup}")
            os.replace(destination, backup)
            try:
                os.replace(stage, destination)
                fsync_directory(destination_root)
                validate_tool(destination, spec)
            except Exception:
                if destination.exists() and not destination.is_symlink():
                    shutil.rmtree(destination)
                os.replace(backup, destination)
                fsync_directory(destination_root)
                raise
            shutil.rmtree(backup)
            fsync_directory(destination_root)
            return destination, True
    stage = build_tool_stage(source, destination_root, spec)
    try:
        os.replace(stage, destination)
        fsync_directory(destination_root)
    except Exception:
        if stage.exists() and stage.parent == destination_root and stage.name.startswith(
            f".{TOOL_DIRECTORY}."
        ):
            shutil.rmtree(stage)
        raise
    validate_tool(destination, spec)
    return destination, True


def default_base() -> Path:
    return Path(os.environ.get("STEAM_ARM64_BASE", Path.home() / "steam-arm64"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare the contained ARM64 Proton tool for No Man's Sky."
    )
    parser.add_argument("action", choices=("prepare", "check"))
    parser.add_argument("--base", type=Path, default=default_base())
    arguments = parser.parse_args()
    source = arguments.base / "client/steamapps/common/Proton 11.0 (ARM64)"
    destination_root = arguments.base / "client/compatibilitytools.d"
    destination = destination_root / TOOL_DIRECTORY
    candidate_root = arguments.base / "candidates"
    openvr_candidate = candidate_root / OPENVR_CANDIDATE_DIRECTORY
    try:
        if arguments.action == "prepare":
            running = active_processes()
            if running:
                detail = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise ToolError(f"Steam/Wine must be stopped: {detail}")
            destination, changed = prepare_tool(source, destination_root)
            openvr_candidate, openvr_changed = prepare_openvr_candidate(
                arguments.base, candidate_root
            )
            _game_openvr, game_openvr_changed = prepare_game_openvr(
                arguments.base, openvr_candidate
            )
            _game_xinput, game_xinput_changed = prepare_game_xinput(arguments.base)
            changed = (
                changed
                or openvr_changed
                or game_openvr_changed
                or game_xinput_changed
            )
        else:
            validate_source(source, NMS_INPUT_PATCH)
            validate_tool(destination)
            validate_openvr_candidate(openvr_candidate)
            validate_game_openvr(arguments.base)
            validate_game_xinput(arguments.base)
            changed = False
    except (OSError, ToolError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "changed": changed,
                "path": str(destination),
                "openvr_path": str(openvr_candidate),
                "tool": TOOL_NAME,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
