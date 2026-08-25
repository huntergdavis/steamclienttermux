#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("start-no-mans-sky-direct.sh")


def executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "launcher=${NO_MANS_SKY_DIRECT_LAUNCHER:-$HOME/start-steam.sh}" in source
    assert "start-steam-native.sh" not in source

    with tempfile.TemporaryDirectory(prefix="no-mans-sky-direct.") as directory:
        root = Path(directory)
        base = root / "steam-arm64"
        (base / "run/native-runtime-dispatch").mkdir(parents=True)
        (base / "logs").mkdir()
        (base / "removable-library-compatdata/275850/pfx").mkdir(parents=True)
        prepare_log = root / "prepare.log"
        launcher_log = root / "launcher.log"
        prepare = root / "prepare"
        executable(
            prepare,
            "#!/usr/bin/env python3\n"
            "import argparse, os, pathlib, sys\n"
            "parser=argparse.ArgumentParser()\n"
            "parser.add_argument('action')\n"
            "parser.add_argument('--base')\n"
            "parser.add_argument('--wine-prefix')\n"
            "parser.add_argument('--window-background')\n"
            "parser.parse_args()\n"
            "pathlib.Path(os.environ['FIXTURE_PREPARE_LOG']).write_text("
            "' '.join(sys.argv[1:]) + '\\n')\n",
        )
        dispatcher = root / "dispatcher.py"
        executable(
            dispatcher,
            "#!/usr/bin/env python3\n"
            "import argparse, os, pathlib, socket\n"
            "parser=argparse.ArgumentParser()\n"
            "parser.add_argument('serve')\n"
            "parser.add_argument('--base')\n"
            "parser.add_argument('--mode')\n"
            "args=parser.parse_args()\n"
            "assert args.mode == 'no-mans-sky'\n"
            "assert os.environ['STEAM_ARM64_DIRECT_FEX_PROFILE'] == 'safe'\n"
            "path=pathlib.Path(args.base)/'run/native-runtime-dispatch/dispatch.sock'\n"
            "with socket.socket(socket.AF_UNIX) as listener:\n"
            " listener.bind(str(path)); os.chmod(path, 0o600); listener.listen(1)\n"
            " connection,_=listener.accept(); print('REQUEST_RECEIVED=1 FD_COUNT=0', flush=True); connection.close()\n",
        )
        launcher = root / "launcher"
        executable(
            launcher,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, socket, sys\n"
            "assert sys.argv[1:] == ['--appid', '275850']\n"
            "assert os.environ['STEAM_ARM64_BWRAP_DIRECT'] == '1'\n"
            "pathlib.Path(os.environ['FIXTURE_LAUNCHER_LOG']).write_text('PASS\\n')\n"
            "with socket.socket(socket.AF_UNIX) as connection:\n"
            " connection.connect(os.environ['FIXTURE_SOCKET'])\n",
        )
        environment = {
            **os.environ,
            "STEAM_ARM64_BASE": str(base),
            "NO_MANS_SKY_DIRECT_PYTHON": str(Path(sys.executable).resolve()),
            "NO_MANS_SKY_DIRECT_DISPATCHER": str(dispatcher),
            "NO_MANS_SKY_DIRECT_LAUNCHER": str(launcher),
            "NO_MANS_SKY_DIRECT_PREPARE": str(prepare),
            "FIXTURE_PREPARE_LOG": str(prepare_log),
            "FIXTURE_LAUNCHER_LOG": str(launcher_log),
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
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert launcher_log.read_text(encoding="utf-8") == "PASS\n"
        assert prepare_log.read_text(encoding="utf-8").strip() == (
            f"prepare --base {base} --wine-prefix "
            f"{base}/removable-library-compatdata/275850/pfx "
            "--window-background 0 0 0"
        )
        assert "launcher=0 server=0" in result.stdout
        fixture_socket = base / "run/native-runtime-dispatch/dispatch.sock"
        assert not fixture_socket.exists()

        timeout_dispatcher = root / "timeout-dispatcher.py"
        executable(
            timeout_dispatcher,
            "#!/usr/bin/env python3\n"
            "import argparse, os, pathlib, socket, time\n"
            "parser=argparse.ArgumentParser()\n"
            "parser.add_argument('serve'); parser.add_argument('--base'); parser.add_argument('--mode')\n"
            "args=parser.parse_args()\n"
            "path=pathlib.Path(args.base)/'run/native-runtime-dispatch/dispatch.sock'\n"
            "with socket.socket(socket.AF_UNIX) as listener:\n"
            " listener.bind(str(path)); os.chmod(path, 0o600); listener.listen(1); time.sleep(10)\n",
        )
        no_dispatch_launcher = root / "no-dispatch-launcher"
        executable(no_dispatch_launcher, "#!/usr/bin/env sh\nexit 0\n")
        timeout_environment = {
            **environment,
            "NO_MANS_SKY_DIRECT_DISPATCHER": str(timeout_dispatcher),
            "NO_MANS_SKY_DIRECT_LAUNCHER": str(no_dispatch_launcher),
            "NO_MANS_SKY_DIRECT_REQUEST_TIMEOUT": "1",
        }
        timeout_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=timeout_environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert timeout_result.returncode == 124, timeout_result.stderr
        assert "accepted AppID 275850 but did not dispatch" in timeout_result.stderr
        assert not (base / "run/native-runtime-dispatch/dispatch.sock").exists()

    print("No Man's Sky direct launcher tests: PASS")


if __name__ == "__main__":
    main()
