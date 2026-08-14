#!/usr/bin/env python3

import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "bin" / "steam-arm64-removable-library.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("steam_arm64_removable_library", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(temporary):
    storage = temporary / "storage"
    external = storage / "7376-B000/Android/data/com.termux/files"
    external.mkdir(parents=True)
    link = temporary / "external-1"
    link.symlink_to(external)
    base = temporary / "steam-arm64"
    base.mkdir()
    steamapps = base / "client" / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_bytes(
        b'"libraryfolders"\r\n{\r\n\t"0"\r\n\t{\r\n'
        b'\t\t"path"\t\t"/internal/client"\r\n'
        b'\t\t"label"\t\t""\r\n'
        b'\t\t"contentid"\t\t"123"\r\n'
        b'\t\t"apps"\r\n\t\t{\r\n'
        b'\t\t\t"732430"\t\t"1"\r\n'
        b'\t\t}\r\n\t}\r\n}\r\n'
    )
    return storage, external, link, base


def protobuf_varint(value):
    rendered = bytearray()
    while value >= 0x80:
        rendered.append((value & 0x7F) | 0x80)
        value >>= 7
    rendered.append(value)
    return bytes(rendered)


def write_depot_manifest(path, depot_id, manifest_gid, original_size):
    metadata = b"".join(
        (
            protobuf_varint(1 << 3),
            protobuf_varint(depot_id),
            protobuf_varint(2 << 3),
            protobuf_varint(manifest_gid),
            protobuf_varint(5 << 3),
            protobuf_varint(original_size),
        )
    )
    path.write_bytes(
        struct.pack("<II", 0x71F617D0, 0)
        + struct.pack("<II", 0x1F4812BE, len(metadata))
        + metadata
    )


def test_prepare_and_idempotence(module, temporary):
    storage, external, link, base = fixture(temporary)
    paths, backup = module.prepare_layout(base, link, storage)
    assert backup is None
    assert paths["source"] == external / module.LIBRARY_NAME
    assert paths["target"].is_dir()
    assert paths["steamapps_control"].is_dir()
    assert paths["external_common"].is_dir()
    assert paths["external_staging"].is_dir()
    assert paths["compatdata"].is_dir()
    assert paths["download_state"].is_dir()
    assert (paths["steamapps_control"] / "common").is_dir()
    assert (paths["steamapps_control"] / "compatdata").is_dir()
    assert (paths["steamapps_control"] / "downloading").is_dir()
    config = paths["config"]
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert json.loads(config.read_text()) == {
        "source": str(external / module.LIBRARY_NAME),
        "staging_binds": {},
        "version": 2,
    }
    loaded = module.load_layout(base, storage)
    assert loaded == paths
    second_paths, second_backup = module.prepare_layout(base, link, storage)
    assert second_paths == paths
    assert second_backup is None
    assert not (base / "backups").exists()


def test_reconfiguration_backup(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    original = paths["config"].read_bytes()
    other = storage / "ABCD-1234/Android/data/com.termux/files"
    other.mkdir(parents=True)
    other_link = temporary / "external-2"
    other_link.symlink_to(other)
    _new_paths, backup = module.prepare_layout(base, other_link, storage)
    assert backup is not None
    assert (backup / module.CONFIG_NAME).read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700


def test_hidden_data_refusals(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    compatdata_mount = paths["steamapps_control"] / "compatdata"
    downloads_mount = paths["steamapps_control"] / "downloading"
    common_mount = paths["steamapps_control"] / "common"
    (compatdata_mount / "588950").mkdir()
    (downloads_mount / "588951").mkdir()
    (common_mount / "Kingsway").mkdir()
    assert module.load_layout(base, storage) == paths
    (compatdata_mount / "588950" / "unexpected-prefix").write_text("unsafe")
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "internal compatdata mount point contains non-directory data" in str(
            error
        )
    else:
        raise AssertionError("internal compatdata file was accepted")
    (compatdata_mount / "588950" / "unexpected-prefix").unlink()
    (downloads_mount / "588951" / "unexpected-download").write_text("unsafe")
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "internal downloads mount point contains non-directory data" in str(error)
    else:
        raise AssertionError("internal downloads file was accepted")
    (downloads_mount / "588951" / "unexpected-download").unlink()
    (common_mount / "Kingsway" / "unexpected-payload").write_text("unsafe")
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "internal common mount point contains non-directory data" in str(error)
    else:
        raise AssertionError("internal common file was accepted")
    (common_mount / "Kingsway" / "unexpected-payload").unlink()
    unsafe_target = temporary / "unsafe-target"
    unsafe_target.mkdir()
    (common_mount / "unsafe-link").symlink_to(unsafe_target)
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "internal common mount point contains non-directory data" in str(error)
    else:
        raise AssertionError("internal common symlink was accepted")
    (common_mount / "unsafe-link").unlink()
    (paths["external_steamapps"] / "appmanifest_unsafe.acf").write_text("unsafe")
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "external Steam control data would be hidden" in str(error)
    else:
        raise AssertionError("external control data was accepted")
    (paths["external_steamapps"] / "appmanifest_unsafe.acf").unlink()
    (paths["target"] / "unexpected-host-data").write_text("unsafe")
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "internal library mount point must be empty" in str(error)
    else:
        raise AssertionError("nonempty internal mount point was accepted")


def test_configuration_refusals(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    config = paths["config"]
    config.chmod(0o644)
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "permissions are too broad" in str(error)
    else:
        raise AssertionError("broad configuration permissions were accepted")
    config.chmod(0o600)
    config.unlink()
    target = temporary / "config-target"
    target.write_text("{}")
    config.symlink_to(target)
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "non-symlink" in str(error)
    else:
        raise AssertionError("symlink configuration was accepted")


def test_removed_card(module, temporary):
    storage, external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    library = paths["source"]
    control = paths["steamapps_control"]
    (control / "common").rmdir()
    (control / "compatdata").rmdir()
    (control / "downloading").rmdir()
    control.rmdir()
    paths["external_common"].rmdir()
    paths["external_steamapps"].rmdir()
    paths["external_staging"].rmdir()
    library.rmdir()
    assert external.is_dir()
    try:
        module.load_layout(base, storage)
    except RuntimeError as error:
        assert "removable library is unavailable" in str(error)
    else:
        raise AssertionError("missing removable library was accepted")


def test_disabled(module, temporary):
    base = temporary / "steam-arm64"
    base.mkdir()
    assert module.load_layout(base, temporary / "storage") is None


def test_staging_bind(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    appid = "12210"
    external_staging = paths["external_staging"] / appid
    internal_staging = paths["download_state"] / appid
    external_staging.mkdir()
    internal_staging.mkdir()
    (external_staging / "GTAIV").mkdir()
    (internal_staging / "GTAIV").mkdir()
    payload = b"verified staging payload"
    (external_staging / "GTAIV/game.bin").write_bytes(payload)
    (internal_staging / "GTAIV/game.bin").write_bytes(payload)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    manifest_bytes = f"{digest}  ./GTAIV/game.bin\n".encode()
    source_manifest = temporary / "source.sha256"
    target_manifest = temporary / "target.sha256"
    source_manifest.write_bytes(manifest_bytes)
    target_manifest.write_bytes(manifest_bytes)
    staging, backup = module.enable_staging_bind(
        base, paths, appid, source_manifest, target_manifest, storage
    )
    assert backup is not None
    assert staging["source"] == external_staging
    assert staging["target"] == internal_staging
    assert staging["files"] == 1
    assert staging["bytes"] == len(payload)
    assert staging["manifest_sha256"] == __import__("hashlib").sha256(
        manifest_bytes
    ).hexdigest()
    loaded = module.load_layout(base, storage)
    assert loaded["staging_binds"][appid] == staging
    assert module.staging_mounts(loaded) == [
        (
            external_staging,
            paths["target"] / "steamapps" / "downloading" / appid,
        )
    ]
    assert module.staging_mounts(loaded)[0][1] != internal_staging
    disable_backup = module.disable_staging_bind(base, loaded, appid, storage)
    assert disable_backup is not None
    disabled = module.load_layout(base, storage)
    assert disabled["staging_binds"] == {}
    assert module.staging_mounts(disabled) == []
    assert module.disable_staging_bind(base, disabled, appid, storage) is None
    staging, _backup = module.enable_staging_bind(
        base, disabled, appid, source_manifest, target_manifest, storage
    )
    (external_staging / "GTAIV/game.bin").unlink()
    assert module.load_layout(base, storage)["staging_binds"][appid] == staging
    target_manifest.write_bytes(b"different\n")
    try:
        module.enable_staging_bind(
            base, loaded, appid, source_manifest, target_manifest, storage
        )
    except RuntimeError as error:
        assert "manifests do not match" in str(error)
    else:
        raise AssertionError("mismatched staging manifests were accepted")


def test_commit_staging(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    appid = "12210"
    external_staging = paths["external_staging"] / appid
    internal_staging = paths["download_state"] / appid
    install_target = paths["external_common"] / "Grand Theft Auto IV"
    external_staging.mkdir()
    internal_staging.mkdir()
    install_target.mkdir()
    payloads = {
        "GTAIV/game.bin": b"game payload",
        "Redistributables/setup.exe": b"setup payload",
    }
    manifest_lines = []
    for relative, payload in payloads.items():
        for root in (external_staging, internal_staging):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        digest = __import__("hashlib").sha256(payload).hexdigest()
        manifest_lines.append(f"{digest}  ./{relative}\n")
    manifest_bytes = "".join(sorted(manifest_lines)).encode()
    source_manifest = temporary / "source.sha256"
    target_manifest = temporary / "target.sha256"
    source_manifest.write_bytes(manifest_bytes)
    target_manifest.write_bytes(manifest_bytes)
    _staging, _backup = module.enable_staging_bind(
        base, paths, appid, source_manifest, target_manifest, storage
    )
    reused = install_target / "GTAIV/game.bin"
    reused.parent.mkdir(parents=True)
    reused.write_bytes(payloads["GTAIV/game.bin"])
    loaded = module.load_layout(base, storage)
    source_stats, final_stats, reused_files = module.commit_staging(
        loaded, appid, "Grand Theft Auto IV", source_manifest
    )
    assert source_stats == (2, sum(map(len, payloads.values())))
    assert final_stats == source_stats
    assert reused_files == 1
    assert not any(external_staging.iterdir())
    for relative, payload in payloads.items():
        assert (install_target / relative).read_bytes() == payload
        assert (internal_staging / relative).read_bytes() == payload

    depot_manifests = []
    for depot_id, (relative, payload) in zip((12211, 12212), payloads.items()):
        manifest_gid = depot_id * 1000003
        depot_manifest = temporary / f"{depot_id}_{manifest_gid}.manifest"
        write_depot_manifest(depot_manifest, depot_id, manifest_gid, len(payload))
        depot_manifests.append(depot_manifest)
    appmanifest = paths["steamapps_control"] / "appmanifest_12210.acf"
    appmanifest_original = (
        '"AppState"\r\n{\r\n'
        '\t"appid"\t\t"12210"\r\n'
        '\t"StateFlags"\t\t"1026"\r\n'
        '\t"installdir"\t\t"Grand Theft Auto IV"\r\n'
        '\t"lastupdated"\t\t"0"\r\n'
        '\t"SizeOnDisk"\t\t"0"\r\n'
        f'\t"StagingSize"\t\t"{source_stats[1]}"\r\n'
        '\t"buildid"\t\t"0"\r\n'
        '\t"DownloadType"\t\t"1"\r\n'
        '\t"BytesToDownload"\t\t"19"\r\n'
        '\t"BytesDownloaded"\t\t"19"\r\n'
        f'\t"BytesToStage"\t\t"{source_stats[1]}"\r\n'
        f'\t"BytesStaged"\t\t"{source_stats[1]}"\r\n'
        '\t"TargetBuildID"\t\t"14009960"\r\n'
        '\t"ScheduledAutoUpdate"\t\t"123"\r\n'
        '\t"InstalledDepots"\r\n\t{\r\n\t}\r\n'
        '}\r\n'
    ).encode()
    appmanifest.write_bytes(appmanifest_original)
    backup, build, finalized_stats, records = module.finalize_staging_manifest(
        base,
        loaded,
        appid,
        "Grand Theft Auto IV",
        depot_manifests,
    )
    assert build == "14009960"
    assert finalized_stats == source_stats
    assert len(records) == 2
    assert (backup / appmanifest.name).read_bytes() == appmanifest_original
    finalized = appmanifest.read_bytes()
    assert b'\t"StateFlags"\t\t"4"\r\n' in finalized
    assert b'\t"SizeOnDisk"\t\t"25"\r\n' in finalized
    assert b'\t"StagingSize"\t\t"0"\r\n' in finalized
    assert b'\t"buildid"\t\t"14009960"\r\n' in finalized
    for depot_id, manifest_gid, size in records:
        assert f'\t\t"{depot_id}"\r\n'.encode() in finalized
        assert f'\t\t\t"manifest"\t\t"{manifest_gid}"\r\n'.encode() in finalized
        assert f'\t\t\t"size"\t\t"{size}"\r\n'.encode() in finalized


def test_commit_staging_rejects_mismatched_overlap(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    appid = "12210"
    external_staging = paths["external_staging"] / appid
    internal_staging = paths["download_state"] / appid
    install_target = paths["external_common"] / "Grand Theft Auto IV"
    payload = b"verified payload"
    for root in (external_staging, internal_staging):
        path = root / "GTAIV/game.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
    installed = install_target / "GTAIV/game.bin"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"different bytes")
    digest = __import__("hashlib").sha256(payload).hexdigest()
    manifest_bytes = f"{digest}  ./GTAIV/game.bin\n".encode()
    source_manifest = temporary / "source.sha256"
    target_manifest = temporary / "target.sha256"
    source_manifest.write_bytes(manifest_bytes)
    target_manifest.write_bytes(manifest_bytes)
    module.enable_staging_bind(
        base, paths, appid, source_manifest, target_manifest, storage
    )
    loaded = module.load_layout(base, storage)
    try:
        module.commit_staging(
            loaded, appid, "Grand Theft Auto IV", source_manifest
        )
    except RuntimeError as error:
        assert "installed target differs from manifest" in str(error)
    else:
        raise AssertionError("mismatched installed overlap was accepted")
    assert (external_staging / "GTAIV/game.bin").read_bytes() == payload
    assert installed.read_bytes() == b"different bytes"


def test_registration(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    libraryfolders = base / "client/steamapps/libraryfolders.vdf"
    original = libraryfolders.read_bytes()
    backup, index = module.register_library(base, paths)
    assert index == 1
    assert backup is not None
    assert (backup / "libraryfolders.vdf").read_bytes() == original
    rendered = libraryfolders.read_bytes()
    assert rendered.count(str(paths["target"]).encode()) == 1
    assert b'"microSD Windows games"' in rendered
    assert rendered.endswith(b"}\r\n")
    second_backup, second_index = module.register_library(base, paths)
    assert second_backup is None
    assert second_index is None
    assert libraryfolders.read_bytes() == rendered


def test_registration_refusals(module, temporary):
    storage, _external, link, base = fixture(temporary)
    paths, _backup = module.prepare_layout(base, link, storage)
    libraryfolders = base / "client/steamapps/libraryfolders.vdf"
    before = libraryfolders.read_bytes()
    try:
        module.render_libraryfolders(b'"wrong"\n{\n}\n', paths["target"], "123")
    except RuntimeError as error:
        assert "no libraryfolders root" in str(error)
    else:
        raise AssertionError("invalid library root was accepted")
    target = temporary / "library-target"
    target.write_bytes(before)
    libraryfolders.unlink()
    libraryfolders.symlink_to(target)
    try:
        module.register_library(base, paths)
    except RuntimeError as error:
        assert "non-symlink" in str(error)
    else:
        raise AssertionError("symlink library configuration was accepted")
    assert target.read_bytes() == before


def main():
    module = load_tool()
    tests = (
        test_prepare_and_idempotence,
        test_reconfiguration_backup,
        test_hidden_data_refusals,
        test_configuration_refusals,
        test_removed_card,
        test_disabled,
        test_staging_bind,
        test_commit_staging,
        test_commit_staging_rejects_mismatched_overlap,
        test_registration,
        test_registration_refusals,
    )
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            test(module, Path(directory))
    print("Steam ARM64 removable-library tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
