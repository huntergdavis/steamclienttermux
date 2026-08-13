#!/usr/bin/env python3

"""Select WineD3D only for GTA IV's Social Club renderer."""

import argparse
import datetime
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


COMMON_PATH = Path(__file__).with_name("configure-gtaiv-virtual-desktop.py")
SPEC = importlib.util.spec_from_file_location("gtaiv_registry_common", COMMON_PATH)
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)

SECTION = br"Software\\Wine\\AppDefaults\\SocialClubHelper.exe\\DllOverrides"
LEGACY_SECTION = br"SoftwareWineAppDefaultsSocialClubHelper.exeDllOverrides"
OVERRIDES = ((b"d3d11", b"builtin"), (b"dxgi", b"builtin"))


def render_registry(original, enable=True, now=None):
    if not original.startswith(b"WINE REGISTRY Version 2\n"):
        raise RuntimeError("user.reg does not have the expected Wine registry header")
    rendered = original
    changes = []
    for key, value in reversed(OVERRIDES):
        expected = COMMON.value_line(key, value)
        rendered, changed = COMMON.disable_value(
            rendered, LEGACY_SECTION, key, expected
        )
        if changed:
            changes.append(
                f"removed malformed SocialClubHelper.exe {key.decode()} override"
            )
    if enable:
        for key, value in OVERRIDES:
            desired = COMMON.value_line(key, value)
            rendered, changed = COMMON.enable_value(
                rendered, SECTION, key, desired, now=now
            )
            if changed:
                changes.append(f"SocialClubHelper.exe {key.decode()}={value.decode()}")
    else:
        for key, value in reversed(OVERRIDES):
            expected = COMMON.value_line(key, value)
            rendered, changed = COMMON.disable_value(
                rendered, SECTION, key, expected
            )
            if changed:
                changes.append(f"removed SocialClubHelper.exe {key.decode()} override")
    return rendered, changes


def apply_registry(registry, backups_dir, enable=True, now=None):
    metadata = COMMON.inspect_regular(registry, "user.reg")
    original = registry.read_bytes()
    rendered, changes = render_registry(original, enable=enable, now=now)
    if not changes:
        return None, changes, COMMON.sha256_bytes(original)

    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(
        tempfile.mkdtemp(
            prefix=f"gtaiv-socialclub-wined3d-{stamp}-", dir=backups_dir
        )
    )
    backup_registry = backup / "user.reg"
    shutil.copy2(registry, backup_registry, follow_symlinks=False)
    if backup_registry.read_bytes() != original:
        raise RuntimeError(f"registry backup verification failed: {backup_registry}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".user.reg.gtaiv-socialclub-wined3d-", dir=registry.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(metadata.st_mode))
        COMMON.write_all(descriptor, rendered)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if temporary.read_bytes() != rendered:
            raise RuntimeError(f"staged registry verification failed: {temporary}")
        os.replace(temporary, registry)
        COMMON.fsync_directory(registry.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    if registry.read_bytes() != rendered:
        raise RuntimeError(f"installed registry verification failed: {registry}")
    return backup, changes, COMMON.sha256_bytes(rendered)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=str(Path.home() / "steam-arm64"))
    parser.add_argument("--registry")
    parser.add_argument("--backups-dir")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", action="store_true")
    action.add_argument("--disable", action="store_true")
    action.add_argument("--check", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    base = Path(args.base)
    registry = (
        Path(args.registry)
        if args.registry
        else base / "removable-library-compatdata/12210/pfx/user.reg"
    )
    backups_dir = Path(args.backups_dir) if args.backups_dir else base / "backups"
    try:
        COMMON.inspect_regular(registry, "user.reg")
        original = registry.read_bytes()
        _rendered, pending = render_registry(original, enable=True)
        if args.check:
            if pending:
                for change in pending:
                    print(f"pending: {change}")
                return 1
            print(
                "GTA IV Social Club WineD3D override: current "
                f"({COMMON.sha256_bytes(original)})"
            )
            return 0

        running = COMMON.find_running_prefix_processes()
        if running:
            details = ", ".join(f"{pid}:{comm}" for pid, comm, _cmdline in running)
            raise RuntimeError(
                f"refusing while Wine/Proton/container processes are active: {details}"
            )
        backup, changes, digest = apply_registry(
            registry, backups_dir, enable=args.enable
        )
        if not changes:
            state = "enabled" if args.enable else "disabled"
            print(f"GTA IV Social Club WineD3D override already {state} ({digest})")
            return 0
        for change in changes:
            print(f"changed: {change}")
        print(f"Backup: {backup}")
        print(f"Installed user.reg SHA-256: {digest}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"configure-gtaiv-socialclub-wined3d: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
