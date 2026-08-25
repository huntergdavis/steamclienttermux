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


TOOL_NAME = "steamclienttermux_nms_proton_11_arm64_4fd95452"
TOOL_DIRECTORY = "steamclienttermux-nms-proton-11-arm64-4fd95452"
SOURCE_VERSION = b"1787334524 proton-11.0-2-arm64\n"
DLL_RELATIVE = Path("files/lib/wine/aarch64-windows/lsteamclient.dll")
MARKER_NAME = ".steamclienttermux-nms-proton.json"
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
    patched_sha256="4fd95452dceb72b2238ab71e5822b852c5e82ab65dcb2c4883993211e8070dc1",
    offset=0x80090,
    before=bytes.fromhex("ffc300d1fd7b02a9"),
    after=bytes.fromhex("20008052c0035fd6"),
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
        "patch_offset": spec.offset,
        "patched_lsteamclient_sha256": spec.patched_sha256,
        "schema_version": 1,
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


def replace_dll(stage: Path, spec: PatchSpec) -> None:
    dll = stage / DLL_RELATIVE
    metadata = regular_owned(dll, "staged lsteamclient DLL")
    temporary = dll.with_name(f".{dll.name}.new")
    if temporary.exists() or temporary.is_symlink():
        raise ToolError(f"staged patch temporary already exists: {temporary}")
    with dll.open("rb") as source, temporary.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    temporary.chmod(stat.S_IMODE(metadata.st_mode))
    with temporary.open("r+b") as stream:
        stream.seek(spec.offset)
        if stream.read(len(spec.before)) != spec.before:
            raise ToolError("staged lsteamclient patch site changed")
        stream.seek(spec.offset)
        stream.write(spec.after)
        stream.flush()
        os.fsync(stream.fileno())
    if sha256(temporary) != spec.patched_sha256:
        raise ToolError("patched lsteamclient DLL hash is unexpected")
    os.replace(temporary, dll)


def prepare_tool(
    source: Path,
    destination_root: Path,
    spec: PatchSpec = NMS_INPUT_PATCH,
) -> tuple[Path, bool]:
    validate_source(source, spec)
    owned_directory(destination_root, "compatibility-tools directory")
    destination = destination_root / TOOL_DIRECTORY
    if destination.exists() or destination.is_symlink():
        validate_tool(destination, spec)
        return destination, False
    stage = Path(
        tempfile.mkdtemp(prefix=f".{TOOL_DIRECTORY}.", dir=destination_root)
    )
    stage.rmdir()
    try:
        copied_files = {source / "proton", source / DLL_RELATIVE}

        def overlay_file(source_name: str, destination_name: str) -> str:
            source_path = Path(source_name)
            destination_path = Path(destination_name)
            if source_path in copied_files:
                return shutil.copy2(source_path, destination_path)
            os.symlink(source_path, destination_path)
            return str(destination_path)

        shutil.copytree(
            source,
            stage,
            copy_function=overlay_file,
            symlinks=True,
        )
        replace_dll(stage, spec)
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
        os.replace(stage, destination)
        descriptor = os.open(destination_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
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
    try:
        if arguments.action == "prepare":
            running = active_processes()
            if running:
                detail = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise ToolError(f"Steam/Wine must be stopped: {detail}")
            destination, changed = prepare_tool(source, destination_root)
        else:
            validate_source(source, NMS_INPUT_PATCH)
            validate_tool(destination)
            changed = False
    except (OSError, ToolError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "changed": changed,
                "path": str(destination),
                "tool": TOOL_NAME,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
