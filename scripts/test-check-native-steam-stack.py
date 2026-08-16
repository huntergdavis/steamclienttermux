#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parent / "check-native-steam-stack.sh"


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="native-stack-check.") as directory:
        home = Path(directory)
        base = home / "base"
        executable(
            home / "bin" / "steam-arm-native",
            "#!/bin/sh\n"
            "test \"$STEAM_ARM64_NATIVE_CHECK\" = 1\n"
            "printf 'client:%s\\n' \"$STEAM_ARM64_PROOT_DIR\"\n",
        )
        executable(
            base / "compat-bin" / "steam-arm64-native-bwrap",
            "#!/bin/sh\n"
            "test \"$STEAM_ARM64_NATIVE_BWRAP_CHECK\" = 1\n"
            "printf 'boundary:%s\\n' \"$STEAM_ARM64_PROOT_DIR\"\n",
        )
        selected = home / "candidate" / "src"
        environment = os.environ.copy()
        environment.update({"HOME": str(home), "STEAM_ARM64_BASE": str(base)})

        result = subprocess.run(
            ["bash", str(SCRIPT), "--proot-dir", str(selected)],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert f"client:{selected}" in result.stdout
        assert f"boundary:{selected}" in result.stdout
        assert result.stdout.rstrip().endswith("native Steam stack preflight: PASS")

        relative = subprocess.run(
            ["bash", str(SCRIPT), "--proot-dir", "relative/src"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert relative.returncode == 2
        assert "must be absolute" in relative.stderr

        missing_value = subprocess.run(
            ["bash", str(SCRIPT), "--proot-dir"],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert missing_value.returncode == 2
        assert "needs a value" in missing_value.stderr

    print("native Steam stack preflight tests: PASS")


if __name__ == "__main__":
    main()
