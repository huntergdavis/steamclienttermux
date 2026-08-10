#!/usr/bin/env python3

"""Prepare and validate an optional removable Steam game-data library."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import struct
import sys
import tempfile


CONFIG_NAME = "removable-library.json"
LIBRARY_NAME = "steam-arm64-library"
UUID_PATTERN = re.compile(r"^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")
RUNNING_COMMS = {"steam", "steamwebhelper", "wineserver"}


def inspect_directory(path, label, *, require_empty=False):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError(f"{label} is not a real directory: {path}")
    if require_empty and next(path.iterdir(), None) is not None:
        raise RuntimeError(f"{label} must be empty: {path}")
    return metadata


def inspect_directory_skeleton(path, label):
    metadata = inspect_directory(path, label)
    pending = [path]
    while pending:
        current = pending.pop()
        for entry in current.iterdir():
            entry_metadata = entry.lstat()
            if stat.S_ISLNK(entry_metadata.st_mode) or not stat.S_ISDIR(
                entry_metadata.st_mode
            ):
                raise RuntimeError(
                    f"{label} contains non-directory data: {entry}"
                )
            pending.append(entry)
    return metadata


def inspect_config(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"configuration is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"configuration has an unexpected link count: {path}")
    if metadata.st_uid != os.getuid():
        raise RuntimeError(f"configuration has an unexpected owner: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError(f"configuration permissions are too broad: {path}")
    return metadata


def inspect_regular_file(path, label):
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular non-symlink file: {path}")
    if metadata.st_nlink != 1:
        raise RuntimeError(f"{label} has an unexpected link count: {path}")
    return metadata


def validate_external_parent(parent, storage_root=Path("/storage")):
    try:
        resolved = parent.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"removable storage is unavailable: {parent}") from error
    inspect_directory(resolved, "removable app storage")
    try:
        relative = resolved.relative_to(storage_root.resolve())
    except ValueError as error:
        raise RuntimeError(f"removable storage is outside {storage_root}: {resolved}") from error
    parts = relative.parts
    if (
        len(parts) != 5
        or not UUID_PATTERN.fullmatch(parts[0])
        or parts[1:] != ("Android", "data", "com.termux", "files")
    ):
        raise RuntimeError(f"unexpected removable app-storage path: {resolved}")
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"removable app storage is not readable and writable: {resolved}")
    return resolved


def layout_paths(base, source):
    return {
        "source": source,
        "target": base / "removable-library",
        "steamapps_control": base / "removable-library-steamapps",
        "external_steamapps": source / "steamapps",
        "external_common": source / "steamapps" / "common",
        "external_staging": source / "staging",
        "compatdata": base / "removable-library-compatdata",
        "download_state": base / "removable-library-downloads",
        "config": base / "config" / CONFIG_NAME,
    }


def inspect_staging_tree(path, label):
    files, _directories = staging_tree_inventory(path, label)
    return len(files), sum(files.values())


def staging_tree_inventory(path, label):
    inspect_directory(path, label)
    files = {}
    directories = []
    pending = [path]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                relative = Path(entry.path).relative_to(path)
                if stat.S_ISDIR(metadata.st_mode):
                    directories.append(relative)
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(metadata.st_mode):
                    files[relative] = metadata.st_size
                else:
                    raise RuntimeError(
                        f"{label} contains unsupported data: {entry.path}"
                    )
    return files, directories


def validate_staging_binds(paths, staging_binds):
    if not isinstance(staging_binds, dict):
        raise RuntimeError("staging_binds must be an object")
    validated = {}
    for appid, expected in sorted(staging_binds.items()):
        if not isinstance(appid, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", appid):
            raise RuntimeError(f"invalid staging App ID: {appid!r}")
        if not isinstance(expected, dict) or set(expected) != {
            "bytes",
            "files",
            "manifest_sha256",
        }:
            raise RuntimeError(f"invalid staging metadata for App ID {appid}")
        if (
            not isinstance(expected["files"], int)
            or isinstance(expected["files"], bool)
            or expected["files"] < 1
            or not isinstance(expected["bytes"], int)
            or isinstance(expected["bytes"], bool)
            or expected["bytes"] < 0
            or not isinstance(expected["manifest_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected["manifest_sha256"])
        ):
            raise RuntimeError(f"invalid staging metadata for App ID {appid}")
        source = paths["external_staging"] / appid
        target = paths["download_state"] / appid
        source_metadata = inspect_directory(
            source, f"external staging tree for App ID {appid}"
        )
        target_metadata = inspect_directory(
            target, f"internal staging tree for App ID {appid}"
        )
        external_metadata = inspect_directory(
            paths["external_common"], "external common payload"
        )
        internal_metadata = inspect_directory(
            paths["download_state"], "internal removable-library downloads"
        )
        if source_metadata.st_dev != external_metadata.st_dev:
            raise RuntimeError(
                f"external staging tree is on the wrong device for App ID {appid}"
            )
        if target_metadata.st_dev != internal_metadata.st_dev:
            raise RuntimeError(
                f"internal staging mount point is on the wrong device for App ID {appid}"
            )
        validated[appid] = {
            **expected,
            "source": source,
            "target": target,
        }
    return validated


def validate_layout(base, source, storage_root=Path("/storage"), staging_binds=None):
    parent = validate_external_parent(source.parent, storage_root)
    try:
        resolved_source = source.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"removable library is unavailable: {source}") from error
    if source.name != LIBRARY_NAME or resolved_source != parent / LIBRARY_NAME:
        raise RuntimeError(f"unexpected removable library path: {source}")
    paths = layout_paths(base, resolved_source)
    inspect_directory(paths["source"], "removable library")
    inspect_directory(paths["target"], "internal library mount point", require_empty=True)
    inspect_directory(paths["steamapps_control"], "internal Steam control root")
    inspect_directory(paths["external_steamapps"], "external steamapps root")
    unexpected_external = sorted(
        entry.name
        for entry in paths["external_steamapps"].iterdir()
        if entry.name != "common"
    )
    if unexpected_external:
        raise RuntimeError(
            "external Steam control data would be hidden: "
            + ", ".join(unexpected_external)
        )
    inspect_directory(paths["external_common"], "external common payload")
    inspect_directory(paths["external_staging"], "external staging root")
    inspect_directory(paths["compatdata"], "internal removable-library compatdata")
    inspect_directory(paths["download_state"], "internal removable-library downloads")
    inspect_directory_skeleton(
        paths["steamapps_control"] / "common",
        "internal common mount point",
    )
    inspect_directory_skeleton(
        paths["steamapps_control"] / "compatdata",
        "internal compatdata mount point",
    )
    inspect_directory_skeleton(
        paths["steamapps_control"] / "downloading",
        "internal downloads mount point",
    )
    if not os.access(paths["source"], os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(f"removable library is not readable and writable: {resolved_source}")
    free_bytes = os.statvfs(resolved_source).f_bavail * os.statvfs(resolved_source).f_frsize
    if free_bytes < 1024 * 1024 * 1024:
        raise RuntimeError(
            f"removable library has less than 1 GiB free: {resolved_source}"
        )
    paths["staging_binds"] = validate_staging_binds(paths, staging_binds or {})
    return paths


def config_bytes(source, staging_binds=None):
    payload = {
        "version": 2,
        "source": str(source),
        "staging_binds": staging_binds or {},
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def fsync_directory(path):
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace(path, rendered, mode):
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        offset = 0
        while offset < len(rendered):
            written = os.write(descriptor, rendered[offset:])
            if written == 0:
                raise OSError("zero-byte atomic write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError(f"staged file verification failed: {temporary}")
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if path.read_bytes() != rendered:
        raise RuntimeError(f"installed file verification failed: {path}")


def write_config(path, rendered, backups_dir):
    existing = inspect_config(path)
    if existing is not None and path.read_bytes() == rendered:
        return None

    backup = None
    if existing is not None:
        backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = Path(
            tempfile.mkdtemp(prefix=f"removable-library-{stamp}-", dir=backups_dir)
        )
        backup_config = backup / CONFIG_NAME
        shutil.copy2(path, backup_config, follow_symlinks=False)
        if backup_config.read_bytes() != path.read_bytes():
            raise RuntimeError(f"configuration backup verification failed: {backup_config}")

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_replace(path, rendered, 0o600)
    return backup


def find_running_processes(proc_root=Path("/proc")):
    matches = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            comm in RUNNING_COMMS
            or b"steamrtarm64/steam" in cmdline
            or b"/wineserver" in cmdline
        ):
            matches.append((int(entry.name), comm))
    return sorted(matches)


def render_libraryfolders(original, target, content_id):
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("libraryfolders.vdf is not valid UTF-8") from error
    target_text = str(target)
    if any(character in target_text for character in '"\r\n\t\0'):
        raise RuntimeError(f"invalid guest library path: {target}")
    if not re.fullmatch(r"[1-9][0-9]{0,19}", content_id):
        raise RuntimeError(f"invalid library content ID: {content_id}")
    if not re.search(r'^"libraryfolders"\s*$', text, re.MULTILINE):
        raise RuntimeError("libraryfolders.vdf has no libraryfolders root")

    paths = re.findall(r'^\t\t"path"\s+"([^"\r\n]+)"\s*$', text, re.MULTILINE)
    target_count = paths.count(target_text)
    if target_count == 1:
        return original, None
    if target_count != 0:
        raise RuntimeError(f"guest library path appears {target_count} times")

    indexes = [
        int(value)
        for value in re.findall(r'^\t"([0-9]+)"\s*$', text, re.MULTILINE)
    ]
    if not indexes:
        raise RuntimeError("libraryfolders.vdf has no numeric library entries")
    index = max(indexes) + 1
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise RuntimeError("libraryfolders.vdf has no final root closure")
    closing = text.rfind("}", 0, len(stripped))
    newline = "\r\n" if "\r\n" in text else "\n"
    entry = newline.join(
        (
            f'\t"{index}"',
            "\t{",
            f'\t\t"path"\t\t"{target_text}"',
            '\t\t"label"\t\t"microSD Windows games"',
            f'\t\t"contentid"\t\t"{content_id}"',
            '\t\t"totalsize"\t\t"0"',
            '\t\t"update_clean_bytes_tally"\t\t"0"',
            '\t\t"time_last_update_verified"\t\t"0"',
            '\t\t"apps"',
            "\t\t{",
            "\t\t}",
            "\t}",
            "",
        )
    )
    rendered = text[:closing] + entry + text[closing:]
    return rendered.encode(), index


def register_library(base, paths):
    libraryfolders = base / "client" / "steamapps" / "libraryfolders.vdf"
    metadata = inspect_regular_file(libraryfolders, "Steam library configuration")
    original = libraryfolders.read_bytes()
    content_id = str(secrets.randbelow((1 << 62) - 1) + 1)
    rendered, index = render_libraryfolders(original, paths["target"], content_id)
    if index is None:
        return None, None

    backups_dir = base / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(
        tempfile.mkdtemp(prefix=f"removable-library-registration-{stamp}-", dir=backups_dir)
    )
    backup_file = backup / libraryfolders.name
    shutil.copy2(libraryfolders, backup_file, follow_symlinks=False)
    if backup_file.read_bytes() != original:
        raise RuntimeError(f"library configuration backup failed: {backup_file}")
    current = inspect_regular_file(libraryfolders, "Steam library configuration")
    if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise RuntimeError("Steam library configuration changed during registration")
    if libraryfolders.read_bytes() != original:
        raise RuntimeError("Steam library configuration changed during registration")
    atomic_replace(libraryfolders, rendered, stat.S_IMODE(metadata.st_mode))
    return backup, index


def prepare_layout(base, external_parent, storage_root=Path("/storage")):
    inspect_directory(base, "Steam ARM64 base")
    parent = validate_external_parent(external_parent, storage_root)
    source = parent / LIBRARY_NAME
    source.mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps").mkdir(mode=0o700, exist_ok=True)
    (source / "steamapps" / "common").mkdir(mode=0o700, exist_ok=True)
    (source / "staging").mkdir(mode=0o700, exist_ok=True)
    target = base / "removable-library"
    steamapps_control = base / "removable-library-steamapps"
    compatdata = base / "removable-library-compatdata"
    download_state = base / "removable-library-downloads"
    target.mkdir(mode=0o700, exist_ok=True)
    steamapps_control.mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "common").mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "compatdata").mkdir(mode=0o700, exist_ok=True)
    (steamapps_control / "downloading").mkdir(mode=0o700, exist_ok=True)
    compatdata.mkdir(mode=0o700, exist_ok=True)
    download_state.mkdir(mode=0o700, exist_ok=True)
    staging_binds = {}
    config = base / "config" / CONFIG_NAME
    if inspect_config(config) is not None:
        payload = load_config_payload(config)
        if payload["source"] == str(source):
            staging_binds = payload["staging_binds"]
    paths = validate_layout(base, source, storage_root, staging_binds)
    backup = write_config(
        paths["config"],
        config_bytes(paths["source"], staging_binds),
        base / "backups",
    )
    return paths, backup


def load_config_payload(config):
    try:
        payload = json.loads(config.read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid removable-library configuration: {config}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"unsupported removable-library configuration: {config}")
    if payload.get("version") == 1 and set(payload) == {"version", "source"}:
        payload = {**payload, "staging_binds": {}}
    elif payload.get("version") != 2 or set(payload) != {
        "version",
        "source",
        "staging_binds",
    }:
        raise RuntimeError(f"unsupported removable-library configuration: {config}")
    if not isinstance(payload["source"], str) or any(
        character in payload["source"] for character in "\r\n\t\0"
    ):
        raise RuntimeError(f"invalid removable-library source: {config}")
    return payload


def load_layout(base, storage_root=Path("/storage")):
    config = base / "config" / CONFIG_NAME
    if inspect_config(config) is None:
        return None
    payload = load_config_payload(config)
    source = Path(payload["source"])
    if not source.is_absolute():
        raise RuntimeError(f"removable-library source is not absolute: {source}")
    return validate_layout(base, source, storage_root, payload["staging_binds"])


def enable_staging_bind(
    base,
    paths,
    appid,
    source_manifest,
    target_manifest,
    storage_root=Path("/storage"),
):
    if not re.fullmatch(r"[1-9][0-9]{0,9}", appid):
        raise RuntimeError(f"invalid staging App ID: {appid!r}")
    source_manifest_metadata = inspect_regular_file(
        source_manifest, "source staging manifest"
    )
    inspect_regular_file(target_manifest, "target staging manifest")
    if source_manifest_metadata.st_size == 0:
        raise RuntimeError("source staging manifest is empty")
    source_manifest_bytes = source_manifest.read_bytes()
    if target_manifest.read_bytes() != source_manifest_bytes:
        raise RuntimeError("staging SHA-256 manifests do not match")
    source = paths["external_staging"] / appid
    target = paths["download_state"] / appid
    source_stats = inspect_staging_tree(
        source, f"external staging tree for App ID {appid}"
    )
    target_stats = inspect_staging_tree(
        target, f"internal staging tree for App ID {appid}"
    )
    if source_stats != target_stats:
        raise RuntimeError(
            f"staging tree mismatch for App ID {appid}: "
            f"external {source_stats}, internal {target_stats}"
        )
    if source_stats[0] != len(source_manifest_bytes.splitlines()):
        raise RuntimeError("staging manifest file count does not match the trees")
    payload = load_config_payload(paths["config"])
    staging_binds = dict(payload["staging_binds"])
    staging_binds[appid] = {
        "bytes": source_stats[1],
        "files": source_stats[0],
        "manifest_sha256": hashlib.sha256(source_manifest_bytes).hexdigest(),
    }
    backup = write_config(
        paths["config"],
        config_bytes(paths["source"], staging_binds),
        base / "backups",
    )
    loaded = load_layout(base, storage_root)
    return loaded["staging_binds"][appid], backup


def parse_staging_manifest(path, expected_sha256, expected_files):
    inspect_regular_file(path, "staging SHA-256 manifest")
    rendered = path.read_bytes()
    if hashlib.sha256(rendered).hexdigest() != expected_sha256:
        raise RuntimeError("staging manifest does not match registered SHA-256")
    try:
        lines = rendered.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise RuntimeError("staging manifest is not valid UTF-8") from error
    if len(lines) != expected_files:
        raise RuntimeError("staging manifest file count does not match registration")
    records = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if match is None:
            raise RuntimeError("unsupported staging manifest record")
        relative = Path(match.group(2))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise RuntimeError(f"unsafe staging manifest path: {relative}")
        if relative in records:
            raise RuntimeError(f"duplicate staging manifest path: {relative}")
        records[relative] = match.group(1)
    return records


def sha256_regular_file(path, label):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{label} is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def commit_staging(paths, appid, install_dir, manifest):
    staging = paths["staging_binds"].get(appid)
    if staging is None:
        raise RuntimeError(f"no removable staging bind is registered for App ID {appid}")
    if (
        not install_dir
        or install_dir in {".", ".."}
        or any(character in install_dir for character in "/\\\r\n\t\0")
    ):
        raise RuntimeError(f"invalid Steam install directory: {install_dir!r}")
    source = staging["source"]
    target = paths["external_common"] / install_dir
    source_metadata = inspect_directory(source, "external staging source")
    target_metadata = inspect_directory(target, "installed game target")
    if source_metadata.st_dev != target_metadata.st_dev:
        raise RuntimeError("staging source and installed target are on different devices")
    expected_records = parse_staging_manifest(
        manifest, staging["manifest_sha256"], staging["files"]
    )
    expected_paths = set(expected_records)
    source_files, source_directories = staging_tree_inventory(
        source, "external staging source"
    )
    if set(source_files) != expected_paths:
        missing = len(expected_paths - set(source_files))
        unexpected = len(set(source_files) - expected_paths)
        raise RuntimeError(
            f"staging source inventory changed: {missing} missing, "
            f"{unexpected} unexpected"
        )
    source_stats = (len(source_files), sum(source_files.values()))
    expected_stats = (staging["files"], staging["bytes"])
    if source_stats != expected_stats:
        raise RuntimeError(
            f"staging source size changed: expected {expected_stats}, got {source_stats}"
        )
    target_files, _target_directories = staging_tree_inventory(
        target, "installed game target"
    )
    overlap = sorted(set(source_files) & set(target_files), key=str)
    for relative in overlap:
        expected_digest = expected_records[relative]
        source_digest = sha256_regular_file(
            source / relative, "overlapping staging source"
        )
        target_digest = sha256_regular_file(
            target / relative, "overlapping installed target"
        )
        if source_digest != expected_digest:
            raise RuntimeError(
                f"overlapping staging source differs from manifest: {relative}"
            )
        if target_digest != expected_digest:
            raise RuntimeError(
                f"overlapping installed target differs from manifest: {relative}"
            )
    overlap_set = set(overlap)
    before_stats = (len(target_files), sum(target_files.values()))
    for relative in sorted(source_directories, key=lambda item: (len(item.parts), str(item))):
        destination = target / relative
        try:
            metadata = destination.lstat()
        except FileNotFoundError:
            destination.mkdir()
        else:
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError(f"staging destination is not a real directory: {destination}")
    for relative in sorted(source_files, key=str):
        source_file = source / relative
        destination = target / relative
        if relative in overlap_set:
            source_file.unlink()
            continue
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError(f"staging destination appeared during commit: {destination}")
        os.replace(source_file, destination)
    for relative in sorted(
        source_directories, key=lambda item: (-len(item.parts), str(item))
    ):
        (source / relative).rmdir()
    if next(source.iterdir(), None) is not None:
        raise RuntimeError(f"staging source is not empty after commit: {source}")
    final_files, _final_directories = staging_tree_inventory(
        target, "installed game target"
    )
    final_stats = (len(final_files), sum(final_files.values()))
    expected_final = (
        before_stats[0] + source_stats[0] - len(overlap),
        before_stats[1]
        + source_stats[1]
        - sum(source_files[relative] for relative in overlap),
    )
    if final_stats != expected_final:
        raise RuntimeError(
            f"installed target verification failed: expected {expected_final}, "
            f"got {final_stats}"
        )
    os.sync()
    return source_stats, final_stats, len(overlap)


def read_protobuf_varint(data, offset):
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 70:
            break
    raise RuntimeError("invalid depot manifest metadata varint")


def protobuf_uint_fields(data):
    fields = {}
    offset = 0
    while offset < len(data):
        tag, offset = read_protobuf_varint(data, offset)
        number = tag >> 3
        wire_type = tag & 7
        if number == 0:
            raise RuntimeError("invalid depot manifest metadata field")
        if wire_type == 0:
            value, offset = read_protobuf_varint(data, offset)
            fields.setdefault(number, []).append(value)
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = read_protobuf_varint(data, offset)
            offset += length
        elif wire_type == 5:
            offset += 4
        else:
            raise RuntimeError("unsupported depot manifest metadata field")
        if offset > len(data):
            raise RuntimeError("truncated depot manifest metadata")
    return fields


def parse_depot_content_manifest(path):
    inspect_regular_file(path, "Steam depot content manifest")
    data = path.read_bytes()
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != 0x71F617D0:
        raise RuntimeError(f"invalid Steam depot payload marker: {path}")
    payload_size = struct.unpack_from("<I", data, 4)[0]
    metadata_offset = 8 + payload_size
    if metadata_offset + 8 > len(data):
        raise RuntimeError(f"truncated Steam depot payload: {path}")
    if struct.unpack_from("<I", data, metadata_offset)[0] != 0x1F4812BE:
        raise RuntimeError(f"invalid Steam depot metadata marker: {path}")
    metadata_size = struct.unpack_from("<I", data, metadata_offset + 4)[0]
    metadata_start = metadata_offset + 8
    metadata_end = metadata_start + metadata_size
    if metadata_end > len(data):
        raise RuntimeError(f"truncated Steam depot metadata: {path}")
    fields = protobuf_uint_fields(data[metadata_start:metadata_end])
    for number, label in ((1, "depot ID"), (2, "manifest GID"), (5, "size")):
        if len(fields.get(number, ())) != 1:
            raise RuntimeError(f"Steam depot metadata has no unique {label}: {path}")
    depot_id = fields[1][0]
    manifest_gid = fields[2][0]
    original_size = fields[5][0]
    if not depot_id or not manifest_gid or not original_size:
        raise RuntimeError(f"Steam depot metadata contains zero identifiers or size: {path}")
    if path.name != f"{depot_id}_{manifest_gid}.manifest":
        raise RuntimeError(f"Steam depot manifest filename disagrees with metadata: {path}")
    return depot_id, manifest_gid, original_size


def top_level_vdf_fields(rendered):
    try:
        text = rendered.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("Steam appmanifest is not valid UTF-8") from error
    fields = {}
    depth = 0
    for line in text.splitlines():
        if depth == 1:
            match = re.fullmatch(r'\s*"([^"\r\n]+)"\s+"([^"\r\n]*)"\s*', line)
            if match is not None:
                key, value = match.groups()
                if key in fields:
                    raise RuntimeError(f"duplicate top-level appmanifest field: {key}")
                fields[key] = value
        depth += line.count("{") - line.count("}")
        if depth < 0:
            raise RuntimeError("Steam appmanifest has unbalanced braces")
    if depth != 0:
        raise RuntimeError("Steam appmanifest has unbalanced braces")
    return fields


def replace_top_level_vdf_field(text, key, value):
    pattern = re.compile(
        rf'^(\t"{re.escape(key)}"[ \t]+)"[^"\r\n]*"(\r?)$', re.MULTILINE
    )
    if len(pattern.findall(text)) != 1:
        raise RuntimeError(f"Steam appmanifest has no unique top-level {key}")
    return pattern.sub(lambda match: f'{match.group(1)}"{value}"{match.group(2)}', text, 1)


def finalize_staging_manifest(base, paths, appid, install_dir, depot_manifests):
    staging = paths["staging_binds"].get(appid)
    if staging is None:
        raise RuntimeError(f"no removable staging bind is registered for App ID {appid}")
    if next(staging["source"].iterdir(), None) is not None:
        raise RuntimeError(f"external staging source is not empty: {staging['source']}")
    if (
        not install_dir
        or install_dir in {".", ".."}
        or any(character in install_dir for character in "/\\\r\n\t\0")
    ):
        raise RuntimeError(f"invalid Steam install directory: {install_dir!r}")
    target = paths["external_common"] / install_dir
    target_stats = inspect_staging_tree(target, "installed game target")
    records = [parse_depot_content_manifest(path) for path in depot_manifests]
    if not records:
        raise RuntimeError("at least one Steam depot manifest is required")
    depot_ids = [record[0] for record in records]
    if len(set(depot_ids)) != len(depot_ids):
        raise RuntimeError("duplicate Steam depot ID")
    depot_size = sum(record[2] for record in records)
    if target_stats[1] != depot_size:
        raise RuntimeError(
            f"installed target size differs from depot metadata: "
            f"target {target_stats[1]}, depots {depot_size}"
        )

    appmanifest = paths["steamapps_control"] / f"appmanifest_{appid}.acf"
    metadata = inspect_regular_file(appmanifest, "Steam appmanifest")
    original = appmanifest.read_bytes()
    fields = top_level_vdf_fields(original)
    if fields.get("appid") != appid or fields.get("installdir") != install_dir:
        raise RuntimeError("Steam appmanifest identity does not match the requested game")
    target_build = fields.get("TargetBuildID", "")
    if not re.fullmatch(r"[1-9][0-9]*", target_build):
        raise RuntimeError("Steam appmanifest has no target build ID")
    download_size = fields.get("BytesToDownload", "")
    if not re.fullmatch(r"[1-9][0-9]*", download_size):
        raise RuntimeError("Steam appmanifest has no download size")
    allowed = {
        "StateFlags": {"4", "6", "1026"},
        "SizeOnDisk": {"0", str(depot_size)},
        "buildid": {"0", target_build},
        "DownloadType": {"1", "4"},
        "BytesDownloaded": {"0", download_size},
        "BytesToStage": {"0", str(depot_size)},
        "BytesStaged": {"0", str(depot_size)},
    }
    for key, values in allowed.items():
        if fields.get(key) not in values:
            raise RuntimeError(f"unexpected Steam appmanifest {key}: {fields.get(key)!r}")

    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    depot_lines = ['\t"InstalledDepots"', "\t{"]
    for depot_id, manifest_gid, original_size in records:
        depot_lines.extend(
            (
                f'\t\t"{depot_id}"',
                "\t\t{",
                f'\t\t\t"manifest"\t\t"{manifest_gid}"',
                f'\t\t\t"size"\t\t"{original_size}"',
                "\t\t}",
            )
        )
    depot_lines.append("\t}")
    depot_block = newline.join(depot_lines)
    empty_depots = re.compile(
        r'^\t"InstalledDepots"\r?\n\t\{\r?\n\t\}', re.MULTILINE
    )
    if len(empty_depots.findall(text)) != 1:
        raise RuntimeError("Steam appmanifest InstalledDepots is not uniquely empty")
    text = empty_depots.sub(depot_block, text, 1)
    updates = {
        "StateFlags": "4",
        "lastupdated": str(int(datetime.datetime.now().timestamp())),
        "SizeOnDisk": str(depot_size),
        "StagingSize": "0",
        "buildid": target_build,
        "DownloadType": "1",
        "BytesDownloaded": download_size,
        "BytesToStage": str(depot_size),
        "BytesStaged": str(depot_size),
        "ScheduledAutoUpdate": "0",
    }
    for key, value in updates.items():
        text = replace_top_level_vdf_field(text, key, value)
    rendered = text.encode("utf-8")

    backups_dir = base / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(
        tempfile.mkdtemp(prefix=f"appmanifest-{appid}-{stamp}-", dir=backups_dir)
    )
    backup_file = backup / appmanifest.name
    shutil.copy2(appmanifest, backup_file, follow_symlinks=False)
    if backup_file.read_bytes() != original:
        raise RuntimeError(f"Steam appmanifest backup failed: {backup_file}")
    current = inspect_regular_file(appmanifest, "Steam appmanifest")
    if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise RuntimeError("Steam appmanifest changed during finalization")
    if appmanifest.read_bytes() != original:
        raise RuntimeError("Steam appmanifest changed during finalization")
    atomic_replace(appmanifest, rendered, stat.S_IMODE(metadata.st_mode))
    return backup, target_build, target_stats, records


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--storage-root", default="/storage", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument(
        "--external-parent", default=str(Path.home() / "storage" / "external-1")
    )
    subparsers.add_parser("check")
    subparsers.add_parser("mount-info")
    subparsers.add_parser("staging-mount-info")
    subparsers.add_parser("register")
    staging = subparsers.add_parser("enable-staging-bind")
    staging.add_argument("appid")
    staging.add_argument("--source-manifest", required=True)
    staging.add_argument("--target-manifest", required=True)
    commit = subparsers.add_parser("commit-staging")
    commit.add_argument("appid")
    commit.add_argument("--install-dir", required=True)
    commit.add_argument("--manifest", required=True)
    finalize = subparsers.add_parser("finalize-staging")
    finalize.add_argument("appid")
    finalize.add_argument("--install-dir", required=True)
    finalize.add_argument("--depot-manifest", action="append", required=True)
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    storage_root = Path(args.storage_root)
    try:
        if args.action == "prepare":
            paths, backup = prepare_layout(
                base, Path(args.external_parent), storage_root
            )
            print(f"Removable Steam library prepared: {paths['source']}")
            print(f"Guest library path: {paths['target']}")
            print(f"Internal Steam control root: {paths['steamapps_control']}")
            print(f"Internal compatdata: {paths['compatdata']}")
            print(f"Internal download state: {paths['download_state']}")
            if backup is not None:
                print(f"Previous configuration backup: {backup}")
            print("With Steam stopped, run register and deploy the launcher before starting Steam.")
            return 0

        paths = load_layout(base, storage_root)
        if args.action == "mount-info":
            if paths is None:
                print("disabled")
            else:
                print(
                    f"{paths['source']}\t{paths['target']}\t"
                    f"{paths['steamapps_control']}\t{paths['external_common']}\t"
                    f"{paths['compatdata']}\t{paths['download_state']}"
                )
            return 0
        if args.action == "staging-mount-info":
            if paths is not None:
                for staging in paths["staging_binds"].values():
                    print(f"{staging['source']}\t{staging['target']}")
            return 0
        if args.action == "enable-staging-bind":
            if paths is None:
                raise RuntimeError("prepare the removable library before enabling staging")
            running = find_running_processes()
            if running:
                details = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise RuntimeError(
                    f"refusing to edit staging binds while processes are active: {details}"
                )
            staging, backup = enable_staging_bind(
                base,
                paths,
                args.appid,
                Path(args.source_manifest),
                Path(args.target_manifest),
                storage_root,
            )
            print(
                f"Enabled removable staging bind for App ID {args.appid}: "
                f"{staging['source']} -> {staging['target']}"
            )
            print(
                f"Verified {staging['files']} files, {staging['bytes']} bytes, "
                f"manifest {staging['manifest_sha256']}"
            )
            if backup is not None:
                print(f"Previous configuration backup: {backup}")
            return 0
        if args.action == "commit-staging":
            if paths is None:
                raise RuntimeError("prepare the removable library before committing staging")
            running = find_running_processes()
            if running:
                details = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise RuntimeError(
                    f"refusing to commit staging while processes are active: {details}"
                )
            source_stats, final_stats, reused_files = commit_staging(
                paths,
                args.appid,
                args.install_dir,
                Path(args.manifest),
            )
            print(
                f"Reconciled removable staging for App ID {args.appid}: "
                f"{source_stats[0] - reused_files} moved, "
                f"{reused_files} already committed, {source_stats[1]} source bytes"
            )
            print(
                f"Installed target now contains {final_stats[0]} files, "
                f"{final_stats[1]} bytes"
            )
            return 0
        if args.action == "finalize-staging":
            if paths is None:
                raise RuntimeError("prepare the removable library before finalizing staging")
            running = find_running_processes()
            if running:
                details = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise RuntimeError(
                    f"refusing to finalize staging while processes are active: {details}"
                )
            backup, build, target_stats, records = finalize_staging_manifest(
                base,
                paths,
                args.appid,
                args.install_dir,
                [Path(path) for path in args.depot_manifest],
            )
            print(
                f"Finalized removable staging for App ID {args.appid}: "
                f"build {build}, {target_stats[0]} files, {target_stats[1]} bytes, "
                f"{len(records)} depots"
            )
            print(f"Previous appmanifest backup: {backup}")
            return 0
        if args.action == "register":
            if paths is None:
                raise RuntimeError("prepare the removable library before registration")
            running = find_running_processes()
            if running:
                details = ", ".join(f"{pid}:{comm}" for pid, comm in running)
                raise RuntimeError(
                    f"refusing to edit Steam libraries while processes are active: {details}"
                )
            backup, index = register_library(base, paths)
            if index is None:
                print(f"Removable Steam library already registered: {paths['target']}")
            else:
                print(f"Registered removable Steam library as entry {index}: {paths['target']}")
                print(f"Previous library configuration backup: {backup}")
            return 0
        if paths is None:
            print("Removable Steam library: disabled")
            return 1
        print(f"Removable Steam library: ready ({paths['source']})")
        print(f"Guest library path: {paths['target']}")
        print(f"Internal Steam control root: {paths['steamapps_control']}")
        print(f"Internal compatdata: {paths['compatdata']}")
        print(f"Internal download state: {paths['download_state']}")
        for appid, staging in paths["staging_binds"].items():
            print(
                f"External staging App ID {appid}: "
                f"{staging['source']} -> {staging['target']}"
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"steam-arm64-removable-library: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
