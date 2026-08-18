#!/usr/bin/env python3

import hashlib
import importlib.util
from pathlib import Path
import stat
import tempfile


TOOL = Path(__file__).with_name("configure-tombraider-cpu-topology.py")
SPEC = importlib.util.spec_from_file_location("tombraider_cpu_topology", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    data = bytearray(MODULE.PATCH_OFFSET + len(MODULE.SOURCE_BYTES) + 32)
    data[MODULE.PATCH_OFFSET : MODULE.PATCH_OFFSET + len(MODULE.SOURCE_BYTES)] = (
        MODULE.SOURCE_BYTES
    )
    return bytes(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    original = fixture()
    rendered = bytearray(original)
    rendered[
        MODULE.PATCH_OFFSET : MODULE.PATCH_OFFSET + len(MODULE.SOURCE_BYTES)
    ] = MODULE.PATCHED_BYTES
    patched = bytes(rendered)

    with tempfile.TemporaryDirectory(prefix="tombraider-topology-test.") as directory:
        root = Path(directory)
        game = root / "TombRaider.exe"
        backups = root / "backups"
        game.write_bytes(original)
        game.chmod(0o700)

        assert MODULE.classify(original, sha(original), sha(patched)) == "disabled"
        backup, state, installed_sha = MODULE.apply(
            game, backups, True, sha(original), sha(patched)
        )
        assert state == "enabled"
        assert installed_sha == sha(patched)
        assert game.read_bytes() == patched
        assert backup.read_bytes() == original
        assert stat.S_IMODE(game.stat().st_mode) == 0o700
        assert stat.S_IMODE(backup.parent.stat().st_mode) == 0o700

        no_backup, state, installed_sha = MODULE.apply(
            game, backups, True, sha(original), sha(patched)
        )
        assert no_backup is None and state == "enabled"
        assert installed_sha == sha(patched)

        backup, state, installed_sha = MODULE.apply(
            game, backups, False, sha(original), sha(patched)
        )
        assert state == "disabled"
        assert installed_sha == sha(original)
        assert game.read_bytes() == original
        assert backup.read_bytes() == patched

        link = root / "linked.exe"
        link.symlink_to(game)
        try:
            MODULE.apply(link, backups, True, sha(original), sha(patched))
        except RuntimeError as error:
            assert "regular non-symlink" in str(error)
        else:
            raise AssertionError("symlink game was accepted")

        unknown = bytearray(original)
        unknown[MODULE.PATCH_OFFSET] ^= 0xFF
        try:
            MODULE.classify(bytes(unknown), sha(original), sha(patched))
        except RuntimeError as error:
            assert "unsupported Tomb Raider executable state" in str(error)
        else:
            raise AssertionError("unknown game state was accepted")

    print("Tomb Raider CPU-topology configurator tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
