#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import stat
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "configure-gtaiv-service-timeout.py"


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "configure_gtaiv_service_timeout", TOOL
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(with_control=False):
    control = b""
    if with_control:
        control = (
            b"[System\\\\ControlSet001\\\\Control] 2\n"
            b"#time=2\n"
            b'"Preserve"="yes"\n\n'
        )
    return (
        b"WINE REGISTRY Version 2\n"
        b";; All keys relative to REGISTRY\\\\Machine\n\n"
        b"#arch=win64\n\n"
        b"[Software\\\\Before] 1\n"
        b"#time=1\n"
        b'"preserve"="yes"\n\n'
        + control
        + b"[System\\\\MountedDevices] 3\n#time=3\n\n"
    )


def test_render(module):
    original = fixture()
    rendered, changed = module.render(original, now=100)
    assert changed is True
    assert rendered.count(b"[" + module.SECTION + b"] ") == 1
    assert rendered.count(module.VALUE) == 1
    again, changed = module.render(rendered, now=200)
    assert changed is False
    assert again == rendered

    original = fixture(with_control=True)
    rendered, changed = module.render(original, now=100)
    assert changed is True
    assert b'"Preserve"="yes"' in rendered
    assert rendered.count(module.VALUE) == 1


def test_refusals(module):
    unexpected = fixture(with_control=True).replace(
        b'"Preserve"="yes"', b'"ServicesPipeTimeout"="30000"'
    )
    try:
        module.render(unexpected, now=100)
    except RuntimeError as error:
        assert "unexpected ServicesPipeTimeout value" in str(error)
    else:
        raise AssertionError("unexpected timeout was overwritten")

    duplicate = fixture(with_control=True).replace(
        b'"Preserve"="yes"',
        module.VALUE + b"\n" + module.VALUE,
    )
    try:
        module.render(duplicate, now=100)
    except RuntimeError as error:
        assert "duplicate ServicesPipeTimeout" in str(error)
    else:
        raise AssertionError("duplicate timeout was accepted")


def test_atomic_apply(module, temporary):
    registry = temporary / "pfx/system.reg"
    backups = temporary / "backups"
    registry.parent.mkdir()
    original = fixture()
    registry.write_bytes(original)
    registry.chmod(0o600)

    backup, digest = module.apply(
        registry, backups, module.digest(original)
    )
    assert backup.read_bytes() == original
    assert module.digest(registry.read_bytes()) == digest
    assert module.VALUE in registry.read_bytes()
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700

    try:
        module.apply(registry, backups, "0" * 64)
    except RuntimeError as error:
        assert "registry changed after validation" in str(error)
    else:
        raise AssertionError("stale registry digest was accepted")


def test_symlink_refusal(module, temporary):
    target = temporary / "real-system.reg"
    target.write_bytes(fixture())
    link = temporary / "system.reg"
    link.symlink_to(target)
    try:
        module.apply(link, temporary / "backups", module.digest(fixture()))
    except RuntimeError as error:
        assert "regular non-symlink" in str(error)
    else:
        raise AssertionError("symlink registry was accepted")


def main():
    module = load_tool()
    test_render(module)
    test_refusals(module)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_atomic_apply(module, temporary)
        test_symlink_refusal(module, temporary)
    print("GTA IV service-timeout configurator tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
