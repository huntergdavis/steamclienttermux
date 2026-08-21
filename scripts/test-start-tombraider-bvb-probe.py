#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import time


SCRIPT = Path(__file__).with_name("start-tombraider-bvb-probe.sh")
PACKAGE = "io.github.huntergdavis.bvb.visiblehost"


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
            "import os, signal, socket, struct, sys, time\n"
            "assert not any(name in os.environ for name in ('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','TOMB_RAIDER_BVB_MAPPED_MEMORY'))\n"
            "path=sys.argv[sys.argv.index('--socket')+1]\n"
            "frame_name=sys.argv[sys.argv.index('--activity-frame-socket')+1]\n"
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
            "    values=struct.unpack('<IHHIIIIQ32s', wire)\n"
            "    magic,version,event,sequence,width,height,pid,clock,received_token=values\n"
            "    status=0 if (magic,version,sequence,received_token)==(0x314c5642,1,expected_sequence,token) else -71\n"
            "    connection.sendall(struct.pack('<IHHIi',0x314c5642,1,0,sequence,status))\n"
            "    connection.close()\n"
            "    if status != 0: raise SystemExit(4)\n"
            "    print(f'bvb-bridge-service: activity_event={event} sequence={sequence} pid={pid} width={width} height={height}', flush=True)\n"
            "activity.close()\n"
            "connection,_=listener.accept()\n"
            "frame=socket.socket(socket.AF_UNIX)\n"
            "for attempt in range(100):\n"
            "    try: frame.connect('\\0'+frame_name); break\n"
            "    except OSError:\n"
            "        if attempt == 99: raise\n"
            "        time.sleep(0.01)\n"
            "frame.sendall(b'frame-setup'); frame.close()\n"
            "connection.close(); listener.close()\n"
            "if os.environ.get('FAKE_SERVICE_MODE') == 'die_after_handoff':\n"
            "    raise SystemExit(23)\n"
            "signal.pause()\n",
        )

        activity_calls = root / "activity-calls.txt"
        activity_launcher = root / "fake-am"
        executable(
            activity_launcher,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, socket, struct, sys\n"
            "assert not any(name in os.environ for name in ('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','TOMB_RAIDER_BVB_MAPPED_MEMORY'))\n"
            f"log=pathlib.Path({str(activity_calls)!r})\n"
            "args=sys.argv[1:]\n"
            "with log.open('a', encoding='utf-8') as output: output.write(' '.join(args)+'\\n')\n"
            f"if args == ['force-stop', '--user', '0', {PACKAGE!r}]: raise SystemExit(0)\n"
            "assert args[:2] == ['start', '-S']\n"
            "port=int(args[args.index('bvb_activity_port')+1])\n"
            "token=bytes.fromhex(args[args.index('bvb_activity_token')+1])\n"
            "events=[(1,0,0),(2,0,0),(3,0,0),(7,2800,1752),(11,2800,1752),(9,0,0)]\n"
            "for sequence,(event,width,height) in enumerate(events,1):\n"
            "    wire=struct.pack('<IHHIIIIQ32s',0x314c5642,1,event,sequence,width,height,12345,9876543210+sequence,token)\n"
            "    with socket.create_connection(('127.0.0.1',port),timeout=1) as connection:\n"
            "        connection.sendall(wire); ack=connection.recv(16)\n"
            "    assert struct.unpack('<IHHIi',ack)[4] == 0\n",
        )

        helper_apk = root / "visible-host.apk"
        helper_apk.write_bytes(b"test-visible-host-apk\n")
        helper_apk.chmod(0o600)
        package_manager = root / "fake-pm"
        executable(
            package_manager,
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "assert not any(name in os.environ for name in ('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','TOMB_RAIDER_BVB_MAPPED_MEMORY'))\n"
            f"package={PACKAGE!r}\n"
            "if sys.argv[1:] == ['list', 'packages', '--show-versioncode', package]:\n"
            "    print('package:io.github.huntergdavis.bvb.visiblehost.decoy versionCode:999')\n"
            "    print(f'package:{package} versionCode:{os.environ.get(\"FAKE_PM_VERSION\", \"40\")}')\n"
            "elif sys.argv[1:] == ['path', package]:\n"
            f"    print('package:{helper_apk}')\n"
            "else:\n"
            "    raise SystemExit(2)\n",
        )

        app_process = root / "fake-app-process"
        executable(
            app_process,
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, signal, socket, sys, time\n"
            "assert not any(name in os.environ for name in ('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','TOMB_RAIDER_BVB_MAPPED_MEMORY'))\n"
            "assert os.environ['CLASSPATH'].endswith('visible-host.apk')\n"
            "assert sys.argv[1:4] == ['-Xnoimage-dex2oat', '/', 'io.github.huntergdavis.bvb.visiblehost.FrameTransportClient']\n"
            "result=pathlib.Path(sys.argv[-2]); name=sys.argv[-1]\n"
            "mode=os.environ.get('FAKE_HELPER_MODE','pass')\n"
            "if mode in ('hang','delayed_fail'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "listener=socket.socket(socket.AF_UNIX)\n"
            "listener.bind('\\0'+name); listener.listen(1)\n"
            "connection,_=listener.accept(); assert connection.recv(64) == b'frame-setup'\n"
            "connection.close(); listener.close()\n"
            "valid={'result':'pass','setup_transport':'persistent_external_image_ring','image_count':3,'generation':7,'per_frame_java_calls':0,'per_frame_binder_calls':0}\n"
            "if mode == 'pass': result.write_text(json.dumps(valid)+'\\n')\n"
            "elif mode == 'fail':\n"
            "    result.write_text(json.dumps({'result':'fail','stage':'native_import'})+'\\n'); raise SystemExit(7)\n"
            "elif mode == 'nested':\n"
            "    valid.update({'result':'fail','nested':{'result':'pass'}}); result.write_text(json.dumps(valid)+'\\n')\n"
            "elif mode == 'multiple': result.write_text(json.dumps(valid)+'\\n'+json.dumps(valid)+'\\n')\n"
            "elif mode == 'delayed_fail': time.sleep(60)\n"
            "elif mode == 'hang': time.sleep(60)\n"
            "else: raise SystemExit(90)\n",
        )

        environment_capture = root / "environment.txt"
        launcher = root / "launcher"
        executable(
            launcher,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, signal, socket, sys, time\n"
            "mode=os.environ.get('FAKE_LAUNCHER_MODE','pass')\n"
            "if mode == 'early17': raise SystemExit(17)\n"
            "required=['STEAM_ARM64_BVB_VULKAN','BVB_BRIDGE_SOCKET','BVB_ICD_DIAGNOSTICS','TOMB_RAIDER_DIRECT_DIAGNOSTICS','TOMB_RAIDER_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_START_GATE']\n"
            "assert not any(name in os.environ for name in ('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY'))\n"
            "gate=pathlib.Path(os.environ['STEAM_ARM64_DIRECT_START_GATE'])\n"
            "waiting=pathlib.Path(str(gate)+'.waiting'); ready=pathlib.Path(str(gate)+'.launcher-ready')\n"
            "waiting.write_text('', encoding='ascii'); waiting.chmod(0o600)\n"
            "ready.write_text('', encoding='ascii'); ready.chmod(0o600)\n"
            "deadline=time.monotonic()+5\n"
            "while not gate.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
            "assert gate.is_file() and not gate.is_symlink()\n"
            "gate.unlink(); waiting.unlink()\n"
            f"pathlib.Path({str(environment_capture)!r}).write_text('\\n'.join([*(f'{{name}}={{os.environ[name]}}' for name in required),f\"BVB_ICD_PROBE_WSI={{os.environ.get('BVB_ICD_PROBE_WSI','')}}\",f\"BVB_COMMAND_STREAM={{os.environ.get('BVB_COMMAND_STREAM','')}}\",f\"STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM={{os.environ.get('STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','')}}\",f\"BVB_MAPPED_MEMORY={{os.environ.get('BVB_MAPPED_MEMORY','')}}\",f\"STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY={{os.environ.get('STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','')}}\"]))\n"
            "client=socket.socket(socket.AF_UNIX); client.connect(os.environ['BVB_BRIDGE_SOCKET']); client.close()\n"
            "if mode == 'post17': raise SystemExit(17)\n"
            "if mode == 'ignore_term': signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)\n"
            "if mode != 'pass': raise SystemExit(91)\n",
        )

        environment = os.environ.copy()
        environment.update(
            {
                "STEAM_ARM64_BASE": str(base),
                "TOMB_RAIDER_BVB_LAUNCHER": str(launcher),
                "BVB_ACTIVITY_LAUNCHER": str(activity_launcher),
                "BVB_PACKAGE_MANAGER": str(package_manager),
                "BVB_APP_PROCESS": str(app_process),
                "BVB_CHILD_STOP_TICKS": "4",
                "BVB_CHILD_KILL_TICKS": "4",
                "BVB_FRAME_FINISH_TICKS": "4",
                "BVB_COMMAND_STREAM": "smuggled",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "smuggled",
                "BVB_MAPPED_MEMORY": "smuggled",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "smuggled",
            }
        )

        def run_case(**overrides: str) -> tuple[subprocess.CompletedProcess[str], float]:
            case_environment = environment.copy()
            case_environment.update(overrides)
            before = time.monotonic()
            completed = subprocess.run(
                ["bash", str(SCRIPT)],
                env=case_environment,
                text=True,
                capture_output=True,
                check=False,
                timeout=8,
            )
            return completed, time.monotonic() - before

        def calls() -> list[str]:
            if not activity_calls.exists():
                return []
            return activity_calls.read_text(encoding="utf-8").splitlines()

        def assert_activity_balanced(expected: int) -> None:
            records = calls()
            starts = [record for record in records if record.startswith("start ")]
            stops = [record for record in records if record.startswith("force-stop ")]
            assert len(starts) == expected, records
            assert len(stops) == expected, records
            assert all(record == f"force-stop --user 0 {PACKAGE}" for record in stops)

        completed, _ = run_case()
        assert completed.returncode == 0, completed.stderr
        assert "frame setup-only handoff" in completed.stdout
        assert "E057_FRAME_PRESENTED" not in completed.stdout
        assert "standalone_E074=authoritative" in completed.stdout
        values = dict(
            line.split("=", 1)
            for line in environment_capture.read_text(encoding="utf-8").splitlines()
        )
        assert values["STEAM_ARM64_BVB_VULKAN"] == "1"
        assert values["BVB_ICD_DIAGNOSTICS"] == "1"
        assert values["TOMB_RAIDER_DIRECT_DIAGNOSTICS"] == "0"
        assert values["TOMB_RAIDER_BVB_COMMAND_STREAM"] == "strict"
        assert values["TOMB_RAIDER_BVB_MAPPED_MEMORY"] == "strict"
        assert values["BVB_COMMAND_STREAM"] == ""
        assert values["STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM"] == ""
        assert values["BVB_MAPPED_MEMORY"] == ""
        assert values["STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY"] == ""
        assert values["BVB_ICD_PROBE_WSI"] == ""
        assert values["BVB_BRIDGE_SOCKET"].startswith(str(base / "run/bvb/"))
        assert values["STEAM_ARM64_DIRECT_START_GATE"].startswith(
            str(base / "run/bvb/tombraider-start-")
        )
        assert not Path(values["BVB_BRIDGE_SOCKET"]).exists()
        assert not Path(values["STEAM_ARM64_DIRECT_START_GATE"]).exists()
        assert_activity_balanced(1)
        start_record = next(record for record in calls() if record.startswith("start "))
        assert "--es bvb_activity_token " in start_record
        assert "--ei bvb_retain_external_renderer 1" in start_record
        frame_results = list(logs.glob("tombraider-bvb-frame-*.json"))
        assert len(frame_results) == 1
        assert '"image_count": 3' in frame_results[0].read_text()

        expected_activity_count = 1
        for command_stream, mapped_memory in (
            ("shared", "strict"),
            ("strict", "shared"),
            ("shared", "shared"),
        ):
            selected, _ = run_case(
                TOMB_RAIDER_BVB_COMMAND_STREAM=command_stream,
                TOMB_RAIDER_BVB_MAPPED_MEMORY=mapped_memory,
            )
            assert selected.returncode == 0, selected.stderr
            selected_values = dict(
                line.split("=", 1)
                for line in environment_capture.read_text(encoding="utf-8").splitlines()
            )
            assert selected_values["TOMB_RAIDER_BVB_COMMAND_STREAM"] == command_stream
            assert selected_values["TOMB_RAIDER_BVB_MAPPED_MEMORY"] == mapped_memory
            assert selected_values["BVB_COMMAND_STREAM"] == ""
            assert selected_values["STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM"] == ""
            assert selected_values["BVB_MAPPED_MEMORY"] == ""
            assert selected_values["STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY"] == ""
            expected_activity_count += 1
            assert_activity_balanced(expected_activity_count)

        invalid_stream, _ = run_case(TOMB_RAIDER_BVB_COMMAND_STREAM="invalid")
        assert invalid_stream.returncode == 1
        assert "must be strict or shared" in invalid_stream.stderr
        assert_activity_balanced(4)

        invalid_mapped_memory, _ = run_case(
            TOMB_RAIDER_BVB_MAPPED_MEMORY="invalid"
        )
        assert invalid_mapped_memory.returncode == 1
        assert "TOMB_RAIDER_BVB_MAPPED_MEMORY must be strict or shared" in (
            invalid_mapped_memory.stderr
        )
        assert_activity_balanced(4)

        early, _ = run_case(FAKE_LAUNCHER_MODE="early17")
        assert early.returncode == 1
        assert "failed before Activity handoff: status=17" in early.stderr
        assert_activity_balanced(4)

        stale, _ = run_case(FAKE_PM_VERSION="39")
        assert stale.returncode == 1
        assert "visible host versionCode 40 or newer is required" in stale.stderr
        assert_activity_balanced(4)

        frame_failed, elapsed = run_case(
            FAKE_HELPER_MODE="fail", FAKE_LAUNCHER_MODE="ignore_term"
        )
        assert frame_failed.returncode == 1
        assert "Activity frame transport did not pass: status=7" in frame_failed.stderr
        assert elapsed < 4, elapsed
        assert "launcher pid" in frame_failed.stderr and "sending KILL" in frame_failed.stderr
        assert_activity_balanced(5)

        nested, _ = run_case(
            FAKE_HELPER_MODE="nested", FAKE_LAUNCHER_MODE="ignore_term"
        )
        assert nested.returncode == 1
        assert "Activity frame transport did not pass: status=0" in nested.stderr
        assert_activity_balanced(6)

        multiple, _ = run_case(
            FAKE_HELPER_MODE="multiple", FAKE_LAUNCHER_MODE="ignore_term"
        )
        assert multiple.returncode == 1
        assert "Activity frame transport did not pass: status=0" in multiple.stderr
        assert_activity_balanced(7)

        hung_helper, elapsed = run_case(FAKE_HELPER_MODE="hang")
        assert hung_helper.returncode == 1
        assert "Activity frame transport timed out" in hung_helper.stderr
        assert "frame-client pid" in hung_helper.stderr and "sending KILL" in hung_helper.stderr
        assert elapsed < 4, elapsed
        assert_activity_balanced(8)

        service_died, elapsed = run_case(
            FAKE_SERVICE_MODE="die_after_handoff",
            FAKE_HELPER_MODE="hang",
            FAKE_LAUNCHER_MODE="ignore_term",
        )
        assert service_died.returncode == 1
        assert "BVB service exited during the foreground probe: status=23" in service_died.stderr
        assert elapsed < 4, elapsed
        assert_activity_balanced(9)

        launcher_first, _ = run_case(
            FAKE_HELPER_MODE="delayed_fail", FAKE_LAUNCHER_MODE="post17"
        )
        assert launcher_first.returncode == 17, launcher_first.stderr
        assert "probe complete: status=17" in launcher_first.stdout
        assert "Activity frame transport did not pass" not in launcher_first.stderr
        assert_activity_balanced(10)


if __name__ == "__main__":
    main()
