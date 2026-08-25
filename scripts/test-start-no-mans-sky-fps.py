#!/usr/bin/env python3
"""Host contract for the opt-in No Man's Sky FPS launcher."""

from pathlib import Path
import os
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-no-mans-sky-fps.sh")


with tempfile.TemporaryDirectory(prefix="nms-fps-launcher.") as directory:
    root = Path(directory)
    home = root / "home"
    home.mkdir()
    bin_directory = root / "bin"
    bin_directory.mkdir()
    launcher = home / "start-no-mans-sky-direct"
    launcher.write_text(
        "#!/usr/bin/env sh\n"
        "test \"$NO_MANS_SKY_MANGOHUD\" = 1\n"
        "printf 'FPS-LAUNCH-PASS\\n'\n",
        encoding="utf-8",
    )
    launcher.chmod(0o700)
    query = bin_directory / "dpkg-query"
    query.write_text(
        "#!/usr/bin/env sh\nprintf 'install ok installed'\n",
        encoding="utf-8",
    )
    query.chmod(0o700)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_directory}:{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "FPS-LAUNCH-PASS\n"

    query.write_text("#!/usr/bin/env sh\nexit 1\n", encoding="utf-8")
    missing = subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "pkg install mangohud-glibc" in missing.stderr

print("No Man's Sky FPS launcher tests: PASS")
