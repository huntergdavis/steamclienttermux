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
        prepare_result = root / "prepare-result"
        affinity_result = root / "affinity-result"
        prepare = root / "prepare"
        executable(
            prepare,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os, sys\n"
            "Path(os.environ['FIXTURE_PREPARE_RESULT']).write_text(' '.join(sys.argv[1:]) + '\\n')\n",
        )
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
            "sleep 0.2\n"
            "exit 1\n",
        )
        affinity = root / "affinity"
        executable(
            affinity,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os, sys, time\n"
            "Path(os.environ['FIXTURE_AFFINITY_RESULT']).write_text(' '.join(sys.argv[1:]) + '\\n')\n"
            "time.sleep(30)\n",
        )
        environment = {
            **os.environ,
            "STEAM_ARM64_BASE": str(base),
            "TOMB_RAIDER_DIRECT_DISPATCHER": str(dispatcher),
            "TOMB_RAIDER_DIRECT_PYTHON": str(Path(os.sys.executable).resolve()),
            "TOMB_RAIDER_DIRECT_LAUNCHER": str(launcher),
            "TOMB_RAIDER_DIRECT_PREPARE": str(prepare),
            "TOMB_RAIDER_DIRECT_AFFINITY": str(affinity),
            "FIXTURE_RESULT": str(result_file),
            "FIXTURE_AFFINITY_RESULT": str(affinity_result),
            "FIXTURE_PREPARE_RESULT": str(prepare_result),
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
        assert prepare_result.read_text().splitlines() == [f"prepare --base {base}"]
        assert result_file.read_text().splitlines() == [
            "1",
            "--appid 203160 -- -nolauncher",
        ]
        state = (base / "run/tombraider-direct-dispatch.state").read_text()
        assert "mode=tombraider" in state
        assert "child_preload=full" in state
        assert "status=complete" in state
        assert "launcher_status=1" in state
        assert "server_status=0" in state
        assert "launcher_log=" in state
        assert affinity_result.read_text().splitlines() == [
            f"--watch --raknet-cpu1 --steam-base {base} "
            f"--lock-file {base}/run/tombraider-direct-affinity.lock"
        ]

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        diagnostic_environment = {
            **environment,
            "TOMB_RAIDER_DIRECT_MODE": "tombraider-diagnostic",
            "TOMB_RAIDER_DIRECT_CHILD_PRELOAD": "lean",
        }
        diagnostic = subprocess.run(
            ["bash", str(SCRIPT)],
            env=diagnostic_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert diagnostic.returncode == 1, diagnostic.stderr
        diagnostic_state = (
            base / "run/tombraider-direct-dispatch.state"
        ).read_text()
        assert "mode=tombraider-diagnostic" in diagnostic_state
        assert "child_preload=lean" in diagnostic_state

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        executable(launcher, "#!/bin/bash\nexit 7\n")
        failed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert failed.returncode == 7, failed.stderr
        failed_state = (
            base / "run/tombraider-direct-dispatch.state"
        ).read_text()
        assert "status=complete" in failed_state
        assert "launcher_status=7" in failed_state
        assert "launcher_log=" in failed_state

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
