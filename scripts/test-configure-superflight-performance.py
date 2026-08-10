#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import stat
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "configure-superflight-performance.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("configure_superflight_performance", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(module):
    values = {
        b"Screenmanager Is Fullscreen mode_h3981298716": b"00000000",
        b"Screenmanager Resolution Height_h2627697771": b"0000036c",
        b"Screenmanager Resolution Width_h182942802": b"00000af0",
        b"UnityGraphicsQuality_h1669003810": b"00000002",
        b"video_antialiasing_h2457061775": b"00000004",
        b"video_motionblur_h3717583676": b"00000001",
        b"video_postprocessing_h645834456": b"00000001",
        b"video_shadowdistance_h911383566": b"00000fa0",
        b"video_shadowquality_h1126408960": b"00000001",
    }
    lines = [
        b"WINE REGISTRY Version 2\r\n",
        b"\r\n",
        b"[Software\\\\Before] 1\r\n",
        b'"preserve"="yes"\r\n',
        b"\r\n",
        module.SECTION + b" 2\r\n",
    ]
    for key, value in values.items():
        lines.append(b'"' + key + b'"=dword:' + value + b"\r\n")
    lines.extend((b"\r\n", b"[Software\\\\After] 3\r\n", b'"preserve"="also"\r\n'))
    return b"".join(lines)


def assert_targets(module, rendered):
    for key, value in module.TARGET_DWORDS.items():
        expected = b'"' + key + b'"=dword:' + value + b"\r\n"
        assert rendered.count(expected) == 1


def test_render(module):
    original = fixture(module)
    rendered, changed = module.render_profile(original)
    assert len(changed) == len(module.TARGET_DWORDS)
    assert_targets(module, rendered)
    assert b'"preserve"="yes"\r\n' in rendered
    assert b'"preserve"="also"\r\n' in rendered
    assert rendered.startswith(b"WINE REGISTRY Version 2\r\n")
    again, pending = module.render_profile(rendered)
    assert again == rendered
    assert pending == []


def test_refusals(module):
    original = fixture(module)
    try:
        module.render_profile(original.replace(module.SECTION, b"[missing]", 1))
    except RuntimeError as error:
        assert "exactly one Superflight registry section" in str(error)
    else:
        raise AssertionError("missing section was accepted")

    duplicate_section = original + b"\r\n" + module.SECTION + b"\r\n"
    try:
        module.render_profile(duplicate_section)
    except RuntimeError as error:
        assert "found 2" in str(error)
    else:
        raise AssertionError("duplicate section was accepted")

    key = next(iter(module.TARGET_DWORDS))
    key_line = b'"' + key + b'"=dword:00000000\r\n'
    duplicate_key = original.replace(module.SECTION + b" 2\r\n", module.SECTION + b" 2\r\n" + key_line)
    try:
        module.render_profile(duplicate_key)
    except RuntimeError as error:
        assert "found 2" in str(error)
    else:
        raise AssertionError("duplicate key was accepted")


def test_atomic_apply(module, temporary):
    registry = temporary / "pfx" / "user.reg"
    backups = temporary / "backups"
    registry.parent.mkdir()
    original = fixture(module)
    registry.write_bytes(original)
    registry.chmod(0o600)

    backup, changed, digest = module.apply_profile(registry, backups)
    assert backup is not None
    assert len(changed) == len(module.TARGET_DWORDS)
    rendered = registry.read_bytes()
    assert digest == module.sha256_bytes(rendered)
    assert_targets(module, rendered)
    assert (backup / "user.reg").read_bytes() == original
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700

    directories_before = sorted(backups.iterdir())
    second_backup, second_changed, second_digest = module.apply_profile(registry, backups)
    assert second_backup is None
    assert second_changed == []
    assert second_digest == digest
    assert sorted(backups.iterdir()) == directories_before


def test_symlink_refusal(module, temporary):
    target = temporary / "real-user.reg"
    target.write_bytes(fixture(module))
    link = temporary / "user.reg"
    link.symlink_to(target)
    before = target.read_bytes()
    try:
        module.apply_profile(link, temporary / "backups-symlink")
    except RuntimeError as error:
        assert "non-symlink" in str(error)
    else:
        raise AssertionError("symlink registry was accepted")
    assert target.read_bytes() == before


def main():
    module = load_tool()
    test_render(module)
    test_refusals(module)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_atomic_apply(module, temporary)
        test_symlink_refusal(module, temporary)
    print("Superflight performance profile tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
