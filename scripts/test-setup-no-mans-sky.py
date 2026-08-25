#!/usr/bin/env python3
"""Host contract for the one-command No Man's Sky setup."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("setup-no-mans-sky.sh")


def executable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    path.chmod(0o700)


with tempfile.TemporaryDirectory(prefix="setup-nms.") as temporary:
    root = Path(temporary)
    home = root / "home"
    base = home / "steam-arm64"
    log = root / "calls.log"
    executable(
        base / "compat-bin/prepare-no-mans-sky-proton.py",
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "with pathlib.Path(os.environ['CALL_LOG']).open('a') as stream: "
        "stream.write('prepare ' + ' '.join(sys.argv[1:]) + '\\n')\n",
    )
    executable(
        home / "bin/configure-steam-app-proton",
        "#!/usr/bin/env sh\n"
        "printf 'map %s\\n' \"$*\" >>\"$CALL_LOG\"\n",
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "CALL_LOG": str(log),
            "HOME": str(home),
            "NO_MANS_SKY_SETUP_PYTHON": str(Path(sys.executable).resolve()),
            "STEAM_ARM64_BASE": str(base),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        f"prepare prepare --base {base}",
        (
            "map 275850 --tool "
            "steamclienttermux_nms_proton_11_arm64_b00a3dcd "
            f"--base {base}"
        ),
    ]
    assert "Restart Steam" in result.stdout

print("one-command No Man's Sky setup tests: PASS")
