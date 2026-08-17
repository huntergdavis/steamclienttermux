#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-direct-dispatch.sh")


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-direct.") as directory:
        root = Path(directory)
        base = root / "base"
        (base / "run/native-runtime-dispatch").mkdir(parents=True)
        (base / "logs").mkdir()
        dispatcher = root / "dispatcher.py"
        executable(
            dispatcher,
            "#!/usr/bin/env python3\n"
            "import argparse, pathlib, socket\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('serve')\n"
            "parser.add_argument('--base')\n"
            "parser.add_argument('--mode')\n"
            "args = parser.parse_args()\n"
            "path = pathlib.Path(args.base) / 'run/native-runtime-dispatch/dispatch.sock'\n"
            "with socket.socket(socket.AF_UNIX) as listener:\n"
            "    listener.bind(str(path))\n"
            "    listener.listen(1)\n"
            "    connection, _ = listener.accept()\n"
            "    connection.close()\n",
        )
        result_file = root / "launcher-environment"
        launcher = root / "launcher"
        executable(
            launcher,
            "#!/bin/bash\n"
            "printf '%s\\n' \"${STEAM_ARM64_BWRAP_DIRECT:-}\" \"$*\" >\"$FIXTURE_RESULT\"\n"
            "python3 - <<'PY'\n"
            "import os, socket\n"
            "with socket.socket(socket.AF_UNIX) as connection:\n"
            "    connection.connect(os.environ['FIXTURE_SOCKET'])\n"
            "PY\n"
            "exit 1\n",
        )
        environment = {
            **os.environ,
            "STEAM_ARM64_BASE": str(base),
            "TOMB_RAIDER_DIRECT_DISPATCHER": str(dispatcher),
            "TOMB_RAIDER_DIRECT_PYTHON": str(Path(os.sys.executable).resolve()),
            "TOMB_RAIDER_DIRECT_LAUNCHER": str(launcher),
            "FIXTURE_RESULT": str(result_file),
            "FIXTURE_SOCKET": str(
                base / "run/native-runtime-dispatch/dispatch.sock"
            ),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1, result.stderr
        assert result_file.read_text().splitlines() == [
            "1",
            "--appid 203160 -- -nolauncher",
        ]
        state = (base / "run/tombraider-direct-dispatch.state").read_text()
        assert "mode=proton-entry-smoke" in state
        assert "status=complete" in state
        assert "launcher_status=1" in state
        assert "server_status=0" in state

        python_link = root / "python3-link"
        python_link.symlink_to(Path(os.sys.executable).resolve())
        rejected_environment = {
            **environment,
            "TOMB_RAIDER_DIRECT_PYTHON": str(python_link),
        }
        rejected = subprocess.run(
            ["bash", str(SCRIPT)],
            env=rejected_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 1
        assert "Termux Python is unavailable" in rejected.stderr

    print("Tomb Raider direct-dispatch wrapper tests: PASS")


if __name__ == "__main__":
    main()
