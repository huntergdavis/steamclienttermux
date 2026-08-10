#!/usr/bin/env python3

import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "configure-gtaiv-registry.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("configure_gtaiv_registry", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return (
        b"WINE REGISTRY Version 2\n"
        b";; All keys relative to REGISTRY\\\\Machine\n\n"
        b"#arch=win64\n\n"
        b"[Software\\\\Before] 1\n#time=1\n\"preserve\"=\"yes\"\n\n"
        b"[Software\\\\Wine] 2\n#time=2\n\n"
        b"[System\\\\After] 3\n#time=3\n"
    )


def assert_targets(module, rendered):
    assert rendered.count(b"[" + module.PARENT_SECTION + b"] ") == 1
    assert rendered.count(b"[" + module.VERSION_SECTION + b"] ") == 1
    assert rendered.count(module.INSTALL_FOLDER_LINE) == 1
    assert rendered.index(module.PARENT_SECTION) < rendered.index(b"Software\\\\Wine")


def test_render(module):
    original = fixture()
    rendered, changed = module.render_registry(original, now=100)
    assert len(changed) == 2
    assert_targets(module, rendered)
    assert b'\"preserve\"=\"yes\"' in rendered
    again, pending = module.render_registry(rendered, now=200)
    assert again == rendered
    assert pending == []


def test_refusals(module):
    original = fixture()
    rendered, _changed = module.render_registry(original, now=100)
    version_start = rendered.index(b"[" + module.VERSION_SECTION + b"] ")
    version_end = rendered.index(b"[Software\\\\Wine]", version_start)
    partial = rendered[:version_start] + rendered[version_end:]
    try:
        module.render_registry(partial)
    except RuntimeError as error:
        assert "partial GTA IV registry state" in str(error)
    else:
        raise AssertionError("partial GTA IV state was accepted")

    wrong = rendered.replace(module.INSTALL_FOLDER_LINE, b'"InstallFolder"="C:\\\\wrong"')
    try:
        module.render_registry(wrong)
    except RuntimeError as error:
        assert "unexpected GTA IV InstallFolder" in str(error)
    else:
        raise AssertionError("wrong InstallFolder was accepted")

    duplicate = rendered + b"\n[" + module.PARENT_SECTION + b"] 200\n"
    try:
        module.render_registry(duplicate)
    except RuntimeError as error:
        assert "duplicate GTA IV registry sections" in str(error)
    else:
        raise AssertionError("duplicate GTA IV section was accepted")


def test_inputs(module, temporary):
    installscript = temporary / "installscript.vdf"
    installscript.write_bytes(b"signed fixture")
    digest = hashlib.sha256(installscript.read_bytes()).hexdigest()
    assert module.validate_installscript(installscript, expected_digest=digest) == digest
    try:
        module.validate_installscript(installscript, expected_digest="0" * 64)
    except RuntimeError as error:
        assert "SHA-256 mismatch" in str(error)
    else:
        raise AssertionError("wrong installscript hash was accepted")

    expected = temporary / "library/steamapps"
    dosdevice = temporary / "s:"
    dosdevice.symlink_to(expected)
    assert module.validate_dosdevice(dosdevice, expected) == str(expected)
    try:
        module.validate_dosdevice(dosdevice, temporary / "wrong")
    except RuntimeError as error:
        assert "target mismatch" in str(error)
    else:
        raise AssertionError("wrong S: target was accepted")


def test_atomic_apply(module, temporary):
    registry = temporary / "pfx/system.reg"
    backups = temporary / "backups"
    registry.parent.mkdir()
    original = fixture()
    registry.write_bytes(original)
    registry.chmod(0o600)

    backup, changed, digest = module.apply_registry(registry, backups, now=100)
    assert backup is not None
    assert len(changed) == 2
    rendered = registry.read_bytes()
    assert digest == module.sha256_bytes(rendered)
    assert_targets(module, rendered)
    assert (backup / "system.reg").read_bytes() == original
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700

    before = sorted(backups.iterdir())
    second_backup, second_changed, second_digest = module.apply_registry(
        registry, backups, now=200
    )
    assert second_backup is None
    assert second_changed == []
    assert second_digest == digest
    assert sorted(backups.iterdir()) == before


def test_process_guard(module, temporary):
    proc_root = temporary / "proc"
    process = proc_root / "123"
    process.mkdir(parents=True)
    (process / "comm").write_text("wineserver\n")
    (process / "cmdline").write_bytes(b"/path/wineserver\0")
    matches = module.find_running_prefix_processes(proc_root)
    assert [(pid, comm) for pid, comm, _cmdline in matches] == [(123, "wineserver")]


def test_symlink_refusal(module, temporary):
    target = temporary / "real-system.reg"
    target.write_bytes(fixture())
    link = temporary / "system.reg"
    link.symlink_to(target)
    try:
        module.apply_registry(link, temporary / "backups-symlink", now=100)
    except RuntimeError as error:
        assert "non-symlink" in str(error)
    else:
        raise AssertionError("symlink registry was accepted")


def main():
    module = load_tool()
    test_render(module)
    test_refusals(module)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_inputs(module, temporary)
        test_atomic_apply(module, temporary)
        test_process_guard(module, temporary)
        test_symlink_refusal(module, temporary)
    print("GTA IV registry configurator tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
