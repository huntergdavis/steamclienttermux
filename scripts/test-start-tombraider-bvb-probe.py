#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("start-tombraider-bvb-probe.sh")


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tombraider-bvb-probe.") as root_text:
        root = Path(root_text)
        base = root / "steam-arm64"
        logs = base / "logs"
        logs.mkdir(parents=True)
        manifest = base / "bvb/icd.d/bvb_icd.aarch64.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="ascii")
        manifest.chmod(0o600)
        service = base / "bvb/bin/bvb-bridge-service"
        executable(
            service,
            "#!/usr/bin/env python3\n"
            "import socket, sys\n"
            "path=sys.argv[sys.argv.index('--socket')+1]\n"
            "listener=socket.socket(socket.AF_UNIX)\n"
            "listener.bind(path); listener.listen(1)\n"
            "connection,_=listener.accept()\n"
            "connection.close(); listener.close()\n",
        )
        result = root / "environment.txt"
        launcher = root / "launcher"
        executable(
            launcher,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, socket\n"
            "required=['STEAM_ARM64_BVB_VULKAN','BVB_BRIDGE_SOCKET',"
            "'BVB_ICD_DIAGNOSTICS','BVB_ICD_PROBE_WSI']\n"
            f"pathlib.Path({str(result)!r}).write_text('\\n'.join("
            "f'{name}={os.environ[name]}' for name in required))\n"
            "client=socket.socket(socket.AF_UNIX)\n"
            "client.connect(os.environ['BVB_BRIDGE_SOCKET'])\n"
            "client.close()\n",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "STEAM_ARM64_BASE": str(base),
                "TOMB_RAIDER_BVB_LAUNCHER": str(launcher),
            }
        )
        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        values = dict(
            line.split("=", 1)
            for line in result.read_text(encoding="utf-8").splitlines()
        )
        assert values["STEAM_ARM64_BVB_VULKAN"] == "1"
        assert values["BVB_ICD_DIAGNOSTICS"] == "1"
        assert values["BVB_ICD_PROBE_WSI"] == "1"
        assert values["BVB_BRIDGE_SOCKET"].startswith(str(base / "run/bvb/"))
        assert not Path(values["BVB_BRIDGE_SOCKET"]).exists()


if __name__ == "__main__":
    main()
