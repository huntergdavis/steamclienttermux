#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("start-no-mans-sky-direct.sh")
SUMMARIZER = Path(__file__).with_name("summarize-mangohud-csv.py")


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
        (base / "compat-bin").mkdir()
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
            "parser.add_argument('--wine-app')\n"
            "parser.add_argument('--mouse-warp-override')\n"
            "parser.parse_args()\n"
            "pathlib.Path(os.environ['FIXTURE_PREPARE_LOG']).write_text("
            "' '.join(sys.argv[1:]) + '\\n')\n",
        )
        executable(
            base / "compat-bin/prepare-no-mans-sky-proton.py",
            "#!/usr/bin/env python3\n"
            "import argparse\n"
            "parser=argparse.ArgumentParser(); parser.add_argument('action'); parser.add_argument('--base')\n"
            "args=parser.parse_args(); assert args.action == 'check'\n",
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
            "assert os.environ['STEAM_ARM64_DIRECT_FEX_PROFILE'] == os.environ['FIXTURE_FEX_PROFILE']\n"
            "hud=os.environ['STEAM_ARM64_DIRECT_NMS_MANGOHUD']\n"
            "config=os.environ['STEAM_ARM64_DIRECT_NMS_MANGOHUD_CONFIG']\n"
            "assert os.environ['STEAM_ARM64_DIRECT_NMS_XINPUT'] == '1'\n"
            "assert hud in ('0', '1')\n"
            "if hud == '0': assert config == ''\n"
            "else:\n"
            " text=pathlib.Path(config).read_text()\n"
            " assert 'autostart_log=1\\n' in text\n"
            " assert f'output_folder={pathlib.Path(config).parent}\\n' in text\n"
            " csv=pathlib.Path(config).parent/'fixture.csv'\n"
            " csv.write_text('v1\\nFRAME METRICS\\nfps,frametime,elapsed\\n'"
            "+'30,33.333,0\\n31,32.258,1000000000\\n')\n"
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
            "NO_MANS_SKY_SUMMARIZER": str(SUMMARIZER),
            "NO_MANS_SKY_SUMMARY_START_SECONDS": "0",
            "FIXTURE_PREPARE_LOG": str(prepare_log),
            "FIXTURE_LAUNCHER_LOG": str(launcher_log),
            "FIXTURE_SOCKET": str(
                base / "run/native-runtime-dispatch/dispatch.sock"
            ),
            "FIXTURE_FEX_PROFILE": "safe",
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
            "--window-background 0 0 0 --wine-app NMS.exe "
            "--mouse-warp-override disable"
        )
        assert "launcher=0 server=0" in result.stdout
        fixture_socket = base / "run/native-runtime-dispatch/dispatch.sock"
        assert not fixture_socket.exists()

        proton_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "NO_MANS_SKY_FEX_PROFILE": "proton",
                "FIXTURE_FEX_PROFILE": "proton",
            },
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert proton_result.returncode == 0, proton_result.stderr
        assert not fixture_socket.exists()

        stability_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "NO_MANS_SKY_FEX_PROFILE": "stability",
                "FIXTURE_FEX_PROFILE": "stability",
            },
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert stability_result.returncode == 0, stability_result.stderr
        assert not fixture_socket.exists()

        strict_locks_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "NO_MANS_SKY_FEX_PROFILE": "strict-locks",
                "FIXTURE_FEX_PROFILE": "strict-locks",
            },
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert strict_locks_result.returncode == 0, strict_locks_result.stderr
        assert not fixture_socket.exists()

        smc_full_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "NO_MANS_SKY_FEX_PROFILE": "smc-full",
                "FIXTURE_FEX_PROFILE": "smc-full",
            },
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert smc_full_result.returncode == 0, smc_full_result.stderr
        assert not fixture_socket.exists()

        invalid_profile = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "NO_MANS_SKY_FEX_PROFILE": "turbo"},
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert invalid_profile.returncode != 0
        assert (
            "must be proton, stability, strict-locks, smc-full, safe, or fast"
            in invalid_profile.stderr
        )
        assert not fixture_socket.exists()

        fps_result = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "NO_MANS_SKY_MANGOHUD": "1"},
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert fps_result.returncode == 0, fps_result.stderr
        assert "No Man's Sky FPS log directory:" in fps_result.stdout
        fps_directories = list((base / "logs").glob("no-mans-sky-fps-*/MangoHud.conf"))
        assert len(fps_directories) == 1
        assert fps_directories[0].stat().st_mode & 0o077 == 0
        summary = fps_directories[0].with_name("summary.json")
        assert summary.is_file() and not summary.is_symlink()
        assert '"mean": 30.5' in summary.read_text(encoding="utf-8")
        assert "No Man's Sky FPS summary:" in fps_result.stdout
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
