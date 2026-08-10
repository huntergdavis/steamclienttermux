#!/usr/bin/env python3

import importlib.util
import json
import os
from pathlib import Path
import stat
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


def test_prepare_and_idempotence(module, temporary):
    storage, external, link, base = fixture(temporary)
    paths, backup = module.prepare_layout(base, link, storage)
    assert backup is None
    assert paths["source"] == external / module.LIBRARY_NAME
    assert paths["target"].is_dir()
    assert paths["steamapps_control"].is_dir()
    assert paths["external_common"].is_dir()
    assert paths["compatdata"].is_dir()
    assert paths["download_state"].is_dir()
    assert (paths["steamapps_control"] / "common").is_dir()
    assert (paths["steamapps_control"] / "compatdata").is_dir()
    assert (paths["steamapps_control"] / "downloading").is_dir()
    config = paths["config"]
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert json.loads(config.read_text()) == {
        "source": str(external / module.LIBRARY_NAME),
        "version": 1,
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
