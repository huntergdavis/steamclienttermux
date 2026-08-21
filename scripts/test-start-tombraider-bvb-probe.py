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
        driver = base / "bvb/driver/libvulkan_freedreno.so"
        driver.parent.mkdir(parents=True)
        driver.write_bytes(b"private-turnip-test-fixture\n")
        driver.chmod(0o600)
        service = base / "bvb/bin/bvb-bridge-service"
        executable(
            service,
            "#!/usr/bin/env python3\n"
            "import socket, struct, sys\n"
            "path=sys.argv[sys.argv.index('--socket')+1]\n"
            f"assert sys.argv[sys.argv.index('--loader')+1] == {str(driver)!r}\n"
            "token=bytes.fromhex(sys.argv[sys.argv.index('--activity-token')+1])\n"
            "listener=socket.socket(socket.AF_UNIX)\n"
            "listener.bind(path); listener.listen(1)\n"
            "activity=socket.socket(socket.AF_INET)\n"
            "activity.bind(('127.0.0.1', 0)); activity.listen(1)\n"
            "port=activity.getsockname()[1]\n"
            "print(f'bvb-bridge-service: ready socket={path} loader=fake activity_port={port}', flush=True)\n"
            "for expected_sequence in range(1, 7):\n"
            "    connection,_=activity.accept()\n"
            "    wire=b''\n"
            "    while len(wire) < 64:\n"
            "        wire += connection.recv(64-len(wire))\n"
            "    magic,version,event,sequence,width,height,pid,clock,received_token=struct.unpack('<IHHIIIIQ32s', wire)\n"
            "    status=0 if (magic,version,sequence,received_token)==(0x314c5642,1,expected_sequence,token) else -71\n"
            "    connection.sendall(struct.pack('<IHHIi',0x314c5642,1,0,sequence,status))\n"
            "    connection.close()\n"
            "    if status != 0: raise SystemExit(4)\n"
            "    print(f'bvb-bridge-service: activity_event={event} sequence={sequence} pid={pid} width={width} height={height}', flush=True)\n"
            "activity.close()\n"
            "connection,_=listener.accept()\n"
            "connection.close(); listener.close()\n",
        )
        activity_calls = root / "activity-calls.txt"
        activity_launcher = root / "fake-am"
        executable(
            activity_launcher,
            "#!/usr/bin/env python3\n"
            "import pathlib, socket, struct, sys\n"
            f"log=pathlib.Path({str(activity_calls)!r})\n"
            "with log.open('a', encoding='utf-8') as output: output.write(' '.join(sys.argv[1:])+'\\n')\n"
            "assert sys.argv[1:3] == ['start', '-S']\n"
            "port=int(sys.argv[sys.argv.index('bvb_activity_port')+1])\n"
            "token=bytes.fromhex(sys.argv[sys.argv.index('bvb_activity_token')+1])\n"
            "events=[(1,0,0),(2,0,0),(3,0,0),(7,2800,1752),(11,2800,1752),(9,0,0)]\n"
            "for sequence,(event,width,height) in enumerate(events,1):\n"
            "    wire=struct.pack('<IHHIIIIQ32s',0x314c5642,1,event,sequence,width,height,12345,9876543210+sequence,token)\n"
            "    with socket.create_connection(('127.0.0.1',port),timeout=1) as connection:\n"
            "        connection.sendall(wire); ack=connection.recv(16)\n"
            "    assert struct.unpack('<IHHIi',ack)[4] == 0\n",
        )
        result = root / "environment.txt"
        launcher = root / "launcher"
        executable(
            launcher,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, socket, time\n"
            "required=['STEAM_ARM64_BVB_VULKAN','BVB_BRIDGE_SOCKET',"
            "'BVB_ICD_DIAGNOSTICS','TOMB_RAIDER_DIRECT_DIAGNOSTICS',"
            "'STEAM_ARM64_DIRECT_START_GATE']\n"
            "gate=pathlib.Path(os.environ['STEAM_ARM64_DIRECT_START_GATE'])\n"
            "waiting=pathlib.Path(str(gate)+'.waiting')\n"
            "ready=pathlib.Path(str(gate)+'.launcher-ready')\n"
            "waiting.write_text('', encoding='ascii'); waiting.chmod(0o600)\n"
            "ready.write_text('', encoding='ascii'); ready.chmod(0o600)\n"
            "deadline=time.monotonic()+5\n"
            "while not gate.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
            "assert gate.is_file() and not gate.is_symlink()\n"
            "gate.unlink(); waiting.unlink()\n"
            f"pathlib.Path({str(result)!r}).write_text('\\n'.join("
            "[*(f'{name}={os.environ[name]}' for name in required),"
            "f\"BVB_ICD_PROBE_WSI={os.environ.get('BVB_ICD_PROBE_WSI','')}\"]))\n"
            "client=socket.socket(socket.AF_UNIX)\n"
            "client.connect(os.environ['BVB_BRIDGE_SOCKET'])\n"
            "client.close()\n",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "STEAM_ARM64_BASE": str(base),
                "TOMB_RAIDER_BVB_LAUNCHER": str(launcher),
                "BVB_ACTIVITY_LAUNCHER": str(activity_launcher),
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
        assert values["TOMB_RAIDER_DIRECT_DIAGNOSTICS"] == "1"
        assert values["BVB_ICD_PROBE_WSI"] == ""
        assert values["BVB_BRIDGE_SOCKET"].startswith(str(base / "run/bvb/"))
        assert values["STEAM_ARM64_DIRECT_START_GATE"].startswith(
            str(base / "run/bvb/tombraider-start-")
        )
        assert not Path(values["BVB_BRIDGE_SOCKET"]).exists()
        assert not Path(values["STEAM_ARM64_DIRECT_START_GATE"]).exists()
        assert not Path(
            values["STEAM_ARM64_DIRECT_START_GATE"] + ".waiting"
        ).exists()
        assert not Path(
            values["STEAM_ARM64_DIRECT_START_GATE"] + ".launcher-ready"
        ).exists()
        calls = activity_calls.read_text(encoding="utf-8").splitlines()
        assert len(calls) == 1
        assert calls[0].startswith(
            "start -S -W -n io.github.huntergdavis.bvb.visiblehost/"
            ".VisibleHostActivity --ei bvb_activity_port "
        )
        assert "--es bvb_activity_token " in calls[0]

        executable(launcher, "#!/bin/sh\nexit 17\n")
        failed = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
        assert failed.returncode == 1
        assert "Steam foreground launch failed before Activity handoff: status=17" in (
            failed.stderr
        )
        assert len(activity_calls.read_text(encoding="utf-8").splitlines()) == 1


if __name__ == "__main__":
    main()
