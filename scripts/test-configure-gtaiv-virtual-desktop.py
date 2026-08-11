#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import stat
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "configure-gtaiv-virtual-desktop.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("configure_gtaiv_virtual_desktop", TOOL)
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
    enabled, changes = module.render_registry(original, size="1920x1080", now=100)
    assert len(changes) == 2
    assert enabled.count(b"[" + module.EXPLORER_SECTION + b"] ") == 1
    assert enabled.count(b"[" + module.DESKTOPS_SECTION + b"] ") == 1
    assert b'"Desktop"="Default"' in enabled
    assert b'"Default"="1920x1080"' in enabled
    assert enabled.index(b"[Software\\\\Wine]") < enabled.index(module.EXPLORER_SECTION)
    assert enabled.index(module.EXPLORER_SECTION) < enabled.index(module.DESKTOPS_SECTION)
    again, pending = module.render_registry(enabled, size="1920x1080", now=200)
    assert again == enabled
    assert pending == []
    disabled, removed = module.render_registry(enabled, size="1920x1080", enable=False)
    assert len(removed) == 2
    assert disabled == original


def test_existing_sections(module):
    original = fixture().replace(
        b"[Software\\\\Wine] 2\n",
        b"[Software\\\\Wine\\\\Explorer] 2\n#time=2\n\"Keep\"=\"yes\"\n\n"
        b"[Software\\\\Wine\\\\Explorer\\\\Desktops] 2\n#time=2\n\"Keep\"=\"yes\"\n\n"
        b"[Software\\\\Wine] 2\n",
    )
    enabled, changes = module.render_registry(original, size="1280x720", now=100)
    assert len(changes) == 2
    assert enabled.count(b'"Keep"="yes"') == 2
    disabled, removed = module.render_registry(enabled, size="1280x720", enable=False)
    assert len(removed) == 2
    assert disabled.count(b'"Keep"="yes"') == 2
    assert module.EXPLORER_SECTION in disabled
    assert module.DESKTOPS_SECTION in disabled


def test_refusals(module):
    enabled, _changes = module.render_registry(fixture(), size="1920x1080", now=100)
    wrong = enabled.replace(b'"Default"="1920x1080"', b'"Default"="1280x720"')
    try:
        module.render_registry(wrong, size="1920x1080", enable=False)
    except RuntimeError as error:
        assert "unexpected Wine registry value" in str(error)
    else:
        raise AssertionError("unexpected virtual desktop size was removed")

    duplicate = enabled.replace(
        b'"Desktop"="Default"\n',
        b'"Desktop"="Default"\n"Desktop"="Other"\n',
    )
    try:
        module.render_registry(duplicate, size="1920x1080")
    except RuntimeError as error:
        assert "duplicate Wine registry value" in str(error)
    else:
        raise AssertionError("duplicate Desktop value was accepted")

    for invalid in ("1920", "639x480", "1920x90000"):
        try:
            module.parse_size(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid size was accepted: {invalid}")


def test_atomic_apply(module, temporary):
    registry = temporary / "pfx/user.reg"
    backups = temporary / "backups"
    registry.parent.mkdir()
    original = fixture()
    registry.write_bytes(original)
    registry.chmod(0o600)
    backup, changes, digest = module.apply_registry(
        registry, backups, size="1920x1080", now=100
    )
    assert backup is not None
    assert len(changes) == 2
    assert (backup / "user.reg").read_bytes() == original
    assert digest == module.sha256_bytes(registry.read_bytes())
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700


def test_process_guard(module, temporary):
    proc_root = temporary / "proc"
    process = proc_root / "123"
    process.mkdir(parents=True)
    (process / "comm").write_text("Launcher.exe\n")
    (process / "cmdline").write_bytes(b"C:\\Launcher.exe\0")
    matches = module.find_running_prefix_processes(proc_root)
    assert [(pid, comm) for pid, comm, _cmdline in matches] == [(123, "Launcher.exe")]


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
    test_existing_sections(module)
    test_refusals(module)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_atomic_apply(module, temporary)
        test_process_guard(module, temporary)
        test_symlink_refusal(module, temporary)
    print("GTA IV virtual desktop configurator tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
