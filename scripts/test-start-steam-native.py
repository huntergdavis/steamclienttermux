#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-steam-native.sh")


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="start-steam-native.") as directory:
        root = Path(directory)
        base = root / "base"
        logs = base / "logs"
        logs.mkdir(parents=True)
        capture = root / "capture"
        launcher = root / "steam-arm-native"
        start_script = root / "start-steam.sh"
        webhelper_patch = base / "patch-steamwebhelper-native.sh"
        executable(launcher, "#!/bin/sh\nexit 0\n")
        executable(webhelper_patch, "#!/bin/sh\nexit 0\n")
        executable(
            start_script,
            "#!/bin/sh\n"
            'printf "proton_log=%s\\n" "${PROTON_LOG-}" > "$CAPTURE"\n'
            'printf "proton_log_dir=%s\\n" "${PROTON_LOG_DIR-}" >> "$CAPTURE"\n'
            'printf "launcher=%s\\n" "$STEAM_ARM64_LAUNCHER" >> "$CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n',
        )
        environment = {
            **os.environ,
            "CAPTURE": str(capture),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_LAUNCHER": str(launcher),
            "STEAM_START_SCRIPT": str(start_script),
        }

        subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--proton-log",
                "--appid",
                "203160",
                "--",
                "-nolauncher",
            ],
            env=environment,
            check=True,
        )
        assert capture.read_text(encoding="utf-8").splitlines() == [
            "proton_log=1",
            f"proton_log_dir={logs}",
            f"launcher={launcher}",
            "arg=--appid",
            "arg=203160",
            "arg=--",
            "arg=-nolauncher",
        ]

    print("native Steam wrapper tests: PASS")


if __name__ == "__main__":
    main()
