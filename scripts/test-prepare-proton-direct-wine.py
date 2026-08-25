#!/usr/bin/env python3

from pathlib import Path
import json
import os
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("prepare-proton-direct-wine.py")
TARGETS = (
    Path("client/steamapps/common/Proton 11.0 (ARM64)/files/bin-arm64/wine"),
    Path("client/steamapps/common/Proton 11.0 (ARM64)/files/bin-arm64/wineserver"),
    Path(
        "client/steamapps/common/Proton 11.0 (ARM64)"
        "/files/lib/wine/aarch64-unix/wine"
    ),
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="prepare-proton-wine.") as directory:
        root = Path(directory)
        base = root / "base"
        originals = {}
        for index, relative in enumerate(TARGETS):
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            original = (
                b"INTERP=/lib/ld-linux-aarch64.so.1\nfixture-"
                + str(index).encode("ascii")
                + b"\n"
            )
            target.write_bytes(original)
            target.chmod(0o500)
            originals[relative] = original
        loader = root / "ld-linux-aarch64.so.1"
        loader.write_bytes(b"loader")
        loader.chmod(0o700)
        patchelf = root / "patchelf"
        patchelf.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import sys\n"
            "if sys.argv[1] == '--print-interpreter':\n"
            "    print(Path(sys.argv[2]).read_text().splitlines()[0].split('=', 1)[1])\n"
            "elif sys.argv[1] == '--set-interpreter':\n"
            "    path = Path(sys.argv[3])\n"
            "    lines = path.read_text().splitlines()\n"
            "    path.write_text('INTERP=' + sys.argv[2] + '\\n' + '\\n'.join(lines[1:]) + '\\n')\n"
            "else:\n"
            "    raise SystemExit(2)\n",
            encoding="utf-8",
        )
        patchelf.chmod(0o700)
        readelf_target = root / "llvm-readobj"
        readelf_target.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import sys\n"
            "if Path(sys.argv[0]).name != 'readelf':\n"
            "    print('LLVM readobj personality')\n"
            "    raise SystemExit(0)\n"
            "value = Path(sys.argv[2]).read_text().splitlines()[0].split('=', 1)[1]\n"
            "print('      [Requesting program interpreter: ' + value + ']')\n",
            encoding="utf-8",
        )
        readelf_target.chmod(0o700)
        readelf = root / "readelf"
        readelf.symlink_to(readelf_target)
        prefix = base / "removable-library-compatdata/203160/pfx"
        prefix.mkdir(parents=True)
        user_registry = prefix / "user.reg"
        original_registry = (
            "WINE REGISTRY Version 2\n\n"
            "[Control Panel\\\\Colors] 1\n"
            '"Window"="255 255 255"\n'
            '"WindowText"="0 0 0"\n'
            "\n[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\ThemeManager\\\\Control Panel\\\\Colors] 1\n"
            '"Window"="255 255 255"\n'
        )
        user_registry.write_text(original_registry, encoding="utf-8")
        user_registry.chmod(0o600)
        command = [
            os.sys.executable,
            str(SCRIPT),
            "--base",
            str(base),
            "--loader",
            str(loader),
            "--patchelf",
            str(patchelf),
            "--readelf",
            str(readelf),
            "--wine-prefix",
            str(prefix),
            "--window-background",
            "0 0 0",
            "--wine-app",
            "NMS.exe",
            "--mouse-warp-override",
            "disable",
        ]
        prepared = subprocess.run(command, text=True, capture_output=True, check=False)
        assert prepared.returncode == 0, prepared.stderr
        for relative in TARGETS:
            target = base / relative
            assert target.read_text().splitlines()[0] == f"INTERP={loader}"
            assert target.stat().st_mode & 0o777 == 0o500
        backups = list((base / "backups/proton-direct-wine").glob("*.original"))
        assert len(backups) == len(TARGETS)
        assert {backup.read_bytes() for backup in backups} == set(originals.values())
        state = json.loads(
            (base / "backups/proton-direct-wine/state.json").read_text()
        )
        assert state["schema_version"] == "2"
        assert len(state["targets"]) == len(TARGETS)
        assert not list((base / "backups/proton-direct-wine").glob(".backup.*"))
        assert '"Window"="0 0 0"' in user_registry.read_text(encoding="utf-8")
        assert user_registry.read_text(encoding="utf-8").count(
            '"Window"="255 255 255"'
        ) == 1
        assert (
            "[Software\\\\Wine\\\\AppDefaults\\\\NMS.exe\\\\DirectInput]"
            in user_registry.read_text(encoding="utf-8")
        )
        assert '"MouseWarpOverride"="disable"' in user_registry.read_text(
            encoding="utf-8"
        )
        appearance_states = list(
            (base / "backups/wine-prefix-appearance").glob("*/state.json")
        )
        assert len(appearance_states) == 1
        appearance = json.loads(appearance_states[0].read_text(encoding="utf-8"))
        assert appearance["original_value"] == "255 255 255"
        checked = subprocess.run(
            [*command[:2], "check", *command[2:]],
            text=True,
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr
        restored = subprocess.run(
            [*command[:2], "restore", *command[2:]],
            text=True,
            capture_output=True,
            check=False,
        )
        assert restored.returncode == 0, restored.stderr
        for relative in TARGETS:
            target = base / relative
            assert target.read_bytes() == originals[relative]
            assert target.stat().st_mode & 0o777 == 0o500
        assert user_registry.read_text(encoding="utf-8") == original_registry
        restored_again = subprocess.run(
            [*command[:2], "restore", *command[2:]],
            text=True,
            capture_output=True,
            check=False,
        )
        assert restored_again.returncode == 0, restored_again.stderr
        prepared_again = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        assert prepared_again.returncode == 0, prepared_again.stderr
        for relative in TARGETS:
            target = base / relative
            assert target.read_text().splitlines()[0] == f"INTERP={loader}"
        assert '"Window"="0 0 0"' in user_registry.read_text(encoding="utf-8")
        assert user_registry.read_text(encoding="utf-8").count(
            '"Window"="255 255 255"'
        ) == 1
        state = json.loads(
            (base / "backups/proton-direct-wine/state.json").read_text()
        )
        assert all("target_ctime_ns" in record for record in state["targets"])

        # The unchanged fast path must not invoke readelf or re-hash payloads.
        # Replacing the fixture readelf also proves that its execution is skipped.
        readelf_target.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
        readelf_target.chmod(0o700)
        cached = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        assert cached.returncode == 0, cached.stderr
        assert cached.stdout.count("identity cached") == len(TARGETS)

        # A metadata change invalidates the receipt and returns to full checking.
        changed_target = base / TARGETS[0]
        os.utime(changed_target, None)
        rejected_stale = subprocess.run(
            command, text=True, capture_output=True, check=False
        )
        assert rejected_stale.returncode != 0
        assert "readelf failed (91)" in rejected_stale.stderr

    print("Proton direct Wine preparation tests: PASS")


if __name__ == "__main__":
    main()
