#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import stat
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "configure-gtaiv-socialclub-wined3d.py"


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "configure_gtaiv_socialclub_wined3d", TOOL
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return (
        b"WINE REGISTRY Version 2\n"
        b";; All keys relative to REGISTRY\\\\User\\\\S-1-5-21-fixture\n\n"
        b"#arch=win64\n\n"
        b"[Software\\\\Before] 1\n#time=1\n\"preserve\"=\"yes\"\n\n"
        b"[Software\\\\Wine] 2\n#time=2\n\"other\"=\"value\"\n\n"
    )


def test_round_trip(module):
    original = fixture()
    enabled, changes = module.render_registry(original, now=100)
    assert len(changes) == 2
    assert enabled.count(b"[" + module.SECTION + b"] ") == 1
    assert b'"d3d11"="builtin"' in enabled
    assert b'"dxgi"="builtin"' in enabled
    again, pending = module.render_registry(enabled, now=200)
    assert again == enabled
    assert pending == []
    disabled, removed = module.render_registry(enabled, enable=False)
    assert len(removed) == 2
    assert disabled == original


def test_existing_section(module):
    original = fixture().replace(
        b"[Software\\\\Wine] 2\n",
        b"[Software\\\\Wine\\\\AppDefaults\\\\SocialClubHelper.exe\\\\DllOverrides] 2\n"
        b"#time=2\n\"keep\"=\"native\"\n\n"
        b"[Software\\\\Wine] 2\n",
    )
    enabled, changes = module.render_registry(original, now=100)
    assert len(changes) == 2
    assert b'"keep"="native"' in enabled
    disabled, removed = module.render_registry(enabled, enable=False)
    assert len(removed) == 2
    assert b'"keep"="native"' in disabled
    assert module.SECTION in disabled


def test_legacy_cleanup(module):
    legacy = fixture().replace(
        b"[Software\\\\Wine] 2\n",
        b"[SoftwareWineAppDefaultsSocialClubHelper.exeDllOverrides] 2\n"
        b"#time=2\n\"d3d11\"=\"builtin\"\n\"dxgi\"=\"builtin\"\n\n"
        b"[Software\\\\Wine] 2\n",
    )
    cleaned, changes = module.render_registry(legacy, enable=False)
    assert len(changes) == 2
    assert cleaned == fixture()

    migrated, changes = module.render_registry(legacy, now=100)
    assert len(changes) == 4
    assert module.LEGACY_SECTION not in migrated
    assert migrated.count(b"[" + module.SECTION + b"] ") == 1


def test_refusals(module):
    enabled, _changes = module.render_registry(fixture(), now=100)
    wrong = enabled.replace(b'"dxgi"="builtin"', b'"dxgi"="native"')
    try:
        module.render_registry(wrong, enable=False)
    except RuntimeError as error:
        assert "unexpected Wine registry value" in str(error)
    else:
        raise AssertionError("unexpected DXGI override was removed")

    duplicate = enabled.replace(
        b'"d3d11"="builtin"\n',
        b'"d3d11"="builtin"\n"d3d11"="native"\n',
    )
    try:
        module.render_registry(duplicate)
    except RuntimeError as error:
        assert "duplicate Wine registry value" in str(error)
    else:
        raise AssertionError("duplicate d3d11 override was accepted")


def test_atomic_apply(module, temporary):
    registry = temporary / "pfx/user.reg"
    backups = temporary / "backups"
    registry.parent.mkdir()
    original = fixture()
    registry.write_bytes(original)
    registry.chmod(0o600)
    backup, changes, digest = module.apply_registry(
        registry, backups, now=100
    )
    assert backup is not None
    assert len(changes) == 2
    assert (backup / "user.reg").read_bytes() == original
    assert digest == module.COMMON.sha256_bytes(registry.read_bytes())
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700


def test_symlink_refusal(module, temporary):
    target = temporary / "real-user.reg"
    target.write_bytes(fixture())
    link = temporary / "user.reg"
    link.symlink_to(target)
    try:
        module.apply_registry(link, temporary / "backups", now=100)
    except RuntimeError as error:
        assert "non-symlink" in str(error)
    else:
        raise AssertionError("symlink registry was accepted")


def main():
    module = load_tool()
    test_round_trip(module)
    test_existing_section(module)
    test_legacy_cleanup(module)
    test_refusals(module)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_atomic_apply(module, temporary)
        test_symlink_refusal(module, temporary)
    print("GTA IV Social Club WineD3D configurator tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
