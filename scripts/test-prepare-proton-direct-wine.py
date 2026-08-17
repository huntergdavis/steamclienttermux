#!/usr/bin/env python3

from pathlib import Path
import os
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("prepare-proton-direct-wine.py")
TARGET = Path(
    "client/steamapps/common/Proton 11.0 (ARM64)/files/lib/wine/aarch64-unix/wine"
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="prepare-proton-wine.") as directory:
        root = Path(directory)
        base = root / "base"
        target = base / TARGET
        target.parent.mkdir(parents=True)
        original = b"INTERP=/lib/ld-linux-aarch64.so.1\nfixture\n"
        target.write_bytes(original)
        target.chmod(0o500)
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
        ]
        prepared = subprocess.run(command, text=True, capture_output=True, check=False)
        assert prepared.returncode == 0, prepared.stderr
        assert target.read_text().splitlines()[0] == f"INTERP={loader}"
        assert target.stat().st_mode & 0o777 == 0o500
        backups = list((base / "backups/proton-direct-wine").glob("wine-*.original"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original
        assert not list((base / "backups/proton-direct-wine").glob(".backup.*"))
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
        assert target.read_bytes() == original
        assert target.stat().st_mode & 0o777 == 0o500

    print("Proton direct Wine preparation tests: PASS")


if __name__ == "__main__":
    main()
