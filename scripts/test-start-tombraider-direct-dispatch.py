#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import time


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
        server_environment = root / "dispatcher-environment"
        executable(
            dispatcher,
            "#!/usr/bin/env python3\n"
            "import argparse, os, pathlib, socket, time\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('serve')\n"
            "parser.add_argument('--base')\n"
            "parser.add_argument('--mode')\n"
            "args = parser.parse_args()\n"
            "names=('BVB_COMMAND_STREAM','STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM','TOMB_RAIDER_BVB_COMMAND_STREAM','BVB_MAPPED_MEMORY','STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY','TOMB_RAIDER_BVB_MAPPED_MEMORY','BVB_DESCRIPTOR_JOURNAL','STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL','TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL','BVB_FIRST_REJECTION_DIAGNOSTIC','STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC','TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC')\n"
            "pathlib.Path(os.environ['FIXTURE_SERVER_ENVIRONMENT']).write_text('\\n'.join(name+'='+os.environ.get(name,'<absent>') for name in names))\n"
            "path = pathlib.Path(args.base) / 'run/native-runtime-dispatch/dispatch.sock'\n"
            "with socket.socket(socket.AF_UNIX) as listener:\n"
            "    listener.bind(str(path))\n"
            "    listener.listen(1)\n"
            "    connection, _ = listener.accept()\n"
            "    connection.close()\n"
            "    if os.environ.get('FIXTURE_SERVER_HOLD') == '1':\n"
            "        time.sleep(1)\n",
        )
        result_file = root / "launcher-environment"
        launcher_control_environment = root / "launcher-control-environment"
        prepare_result = root / "prepare-result"
        affinity_result = root / "affinity-result"
        topology_result = root / "topology-result"
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
            "for name in BVB_COMMAND_STREAM STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM TOMB_RAIDER_BVB_COMMAND_STREAM BVB_MAPPED_MEMORY STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY TOMB_RAIDER_BVB_MAPPED_MEMORY BVB_DESCRIPTOR_JOURNAL STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL BVB_FIRST_REJECTION_DIAGNOSTIC STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC; do printf '%s=%s\\n' \"$name\" \"${!name-<absent>}\"; done >\"$FIXTURE_LAUNCHER_CONTROL_ENVIRONMENT\"\n"
            "python3 - <<'PY'\n"
            "import os, socket\n"
            "with socket.socket(socket.AF_UNIX) as connection:\n"
            "    connection.connect(os.environ['FIXTURE_SOCKET'])\n"
            "PY\n"
            "sleep 0.2\n"
            "exit 1\n",
        )
        failing_launcher_body = launcher.read_text(encoding="utf-8")
        affinity = root / "affinity"
        executable(
            affinity,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os, sys, time\n"
            "Path(os.environ['FIXTURE_AFFINITY_RESULT']).write_text(' '.join(sys.argv[1:]) + '\\n')\n"
            "time.sleep(30)\n",
        )
        topology_checker = root / "topology-checker"
        executable(
            topology_checker,
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os, sys\n"
            "Path(os.environ['FIXTURE_TOPOLOGY_RESULT']).write_text(' '.join(sys.argv[1:]) + '\\n')\n"
            "print('Tomb Raider CPU topology fix: enabled; SHA-256 ' + '4' * 64)\n",
        )
        environment = {
            **os.environ,
            "STEAM_ARM64_BASE": str(base),
            "TOMB_RAIDER_DIRECT_DISPATCHER": str(dispatcher),
            "TOMB_RAIDER_DIRECT_PYTHON": str(Path(os.sys.executable).resolve()),
            "TOMB_RAIDER_DIRECT_LAUNCHER": str(launcher),
            "TOMB_RAIDER_DIRECT_PREPARE": str(prepare),
            "TOMB_RAIDER_DIRECT_AFFINITY": str(affinity),
            "TOMB_RAIDER_DIRECT_TOPOLOGY_CHECKER": str(topology_checker),
            "FIXTURE_RESULT": str(result_file),
            "FIXTURE_SERVER_ENVIRONMENT": str(server_environment),
            "FIXTURE_LAUNCHER_CONTROL_ENVIRONMENT": str(
                launcher_control_environment
            ),
            "FIXTURE_AFFINITY_RESULT": str(affinity_result),
            "FIXTURE_PREPARE_RESULT": str(prepare_result),
            "FIXTURE_TOPOLOGY_RESULT": str(topology_result),
            "FIXTURE_SOCKET": str(
                base / "run/native-runtime-dispatch/dispatch.sock"
            ),
            "STEAM_ARM64_BVB_VULKAN": "1",
            "TOMB_RAIDER_BVB_COMMAND_STREAM": "shared",
            "TOMB_RAIDER_BVB_MAPPED_MEMORY": "direct",
            "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL": "shared",
            "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC": "1",
            "BVB_COMMAND_STREAM": "smuggled",
            "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "smuggled",
            "BVB_MAPPED_MEMORY": "smuggled",
            "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "smuggled",
            "BVB_DESCRIPTOR_JOURNAL": "smuggled",
            "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL": "smuggled",
            "BVB_FIRST_REJECTION_DIAGNOSTIC": "smuggled",
            "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC": "smuggled",
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
        assert topology_result.read_text().splitlines() == ["--check"]
        assert result_file.read_text().splitlines() == [
            "1",
            "--appid 203160 -- -nolauncher",
        ]
        assert server_environment.read_text().splitlines() == [
            "BVB_COMMAND_STREAM=<absent>",
            "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM=shared",
            "TOMB_RAIDER_BVB_COMMAND_STREAM=<absent>",
            "BVB_MAPPED_MEMORY=<absent>",
            "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY=direct",
            "TOMB_RAIDER_BVB_MAPPED_MEMORY=<absent>",
            "BVB_DESCRIPTOR_JOURNAL=<absent>",
            "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL=shared",
            "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL=<absent>",
            "BVB_FIRST_REJECTION_DIAGNOSTIC=<absent>",
            "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC=1",
            "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC=<absent>",
        ]
        assert launcher_control_environment.read_text().splitlines() == [
            "BVB_COMMAND_STREAM=<absent>",
            "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM=<absent>",
            "TOMB_RAIDER_BVB_COMMAND_STREAM=<absent>",
            "BVB_MAPPED_MEMORY=<absent>",
            "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY=<absent>",
            "TOMB_RAIDER_BVB_MAPPED_MEMORY=<absent>",
            "BVB_DESCRIPTOR_JOURNAL=<absent>",
            "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL=<absent>",
            "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL=<absent>",
            "BVB_FIRST_REJECTION_DIAGNOSTIC=<absent>",
            "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC=<absent>",
            "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC=<absent>",
        ]
        state = (base / "run/tombraider-direct-dispatch.state").read_text()
        assert "mode=tombraider" in state
        assert "child_preload=full" in state
        assert "game_cpus=1-7" in state
        assert "status=complete" in state
        assert "launcher_status=1" in state
        assert "server_status=0" in state
        assert "launcher_log=" in state
        assert affinity_result.read_text().splitlines() == [
            f"--watch --raknet-cpu1 --steam-base {base} --game-cpus 1-7 "
            "--wait-for-cpu-log "
            "--poll-seconds 0.25 "
            f"--lock-file {base}/runtime/tomb-raider-affinity.lock"
        ]

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        gate_directory = base / "run/bvb"
        gate_directory.mkdir(mode=0o700)
        start_gate = (
            gate_directory / "tombraider-start-20260821T010203Z-42.gate"
        )
        waiting = Path(f"{start_gate}.waiting")
        executable(
            launcher,
            failing_launcher_body.replace("exit 1", "exit 0"),
        )
        delayed_marker = subprocess.Popen(
            [
                os.sys.executable,
                "-c",
                "import os, pathlib, time; "
                "time.sleep(0.5); "
                "os.umask(0o077); "
                "pathlib.Path(os.environ['FIXTURE_WAITING']).write_text('')",
            ],
            env={**os.environ, "FIXTURE_WAITING": str(waiting)},
        )
        started = time.monotonic()
        gated = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "STEAM_ARM64_DIRECT_START_GATE": str(start_gate),
                "FIXTURE_SERVER_HOLD": "1",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        delayed_marker.wait(timeout=2)
        assert gated.returncode == 0, gated.stderr
        assert time.monotonic() - started >= 0.45
        launcher_ready = Path(f"{start_gate}.launcher-ready")
        assert launcher_ready.is_file() and not launcher_ready.is_symlink()
        assert launcher_ready.stat().st_mode & 0o077 == 0
        waiting.unlink()
        launcher_ready.unlink()
        executable(launcher, failing_launcher_body)

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        benchmark_environment = {
            **environment,
            "TOMB_RAIDER_DIRECT_MODE": "tombraider-benchmark",
            "TOMB_RAIDER_DIRECT_CHILD_PRELOAD": "lean",
        }
        benchmark = subprocess.run(
            ["bash", str(SCRIPT)],
            env=benchmark_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert benchmark.returncode == 1, benchmark.stderr
        assert result_file.read_text().splitlines() == [
            "1",
            "--appid 203160 -- -nolauncher -benchmark",
        ]
        benchmark_state = (
            base / "run/tombraider-direct-dispatch.state"
        ).read_text()
        assert "mode=tombraider-benchmark" in benchmark_state
        assert "child_preload=lean" in benchmark_state

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        high_environment = {
            **benchmark_environment,
            "TOMB_RAIDER_BENCHMARK_PRESET": "720p-high",
        }
        high = subprocess.run(
            ["bash", str(SCRIPT)],
            env=high_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert high.returncode == 1, high.stderr
        high_ini = base / "run/tombraider-benchmark-720p-high.ini"
        high_ini_windows = "Z:" + str(high_ini).replace("/", "\\")
        assert result_file.read_text().splitlines() == [
            "1",
            f"--appid 203160 -- -nolauncher -benchmarkini {high_ini_windows}",
        ]
        assert not high_ini.exists() and not high_ini.is_symlink()

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        no_tessellation_environment = {
            **benchmark_environment,
            "TOMB_RAIDER_BENCHMARK_PRESET": "720p-ultra-no-tessellation",
        }
        no_tessellation = subprocess.run(
            ["bash", str(SCRIPT)],
            env=no_tessellation_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert no_tessellation.returncode == 1, no_tessellation.stderr
        no_tessellation_ini = (
            base / "run/tombraider-benchmark-720p-ultra-no-tessellation.ini"
        )
        no_tessellation_ini_windows = "Z:" + str(no_tessellation_ini).replace(
            "/", "\\"
        )
        assert result_file.read_text().splitlines() == [
            "1",
            "--appid 203160 -- -nolauncher -benchmarkini "
            + no_tessellation_ini_windows,
        ]
        assert not no_tessellation_ini.exists()
        assert not no_tessellation_ini.is_symlink()

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        tuned_environment = {
            **benchmark_environment,
            "TOMB_RAIDER_BENCHMARK_PRESET": (
                "720p-ultra-no-tessellation-ssao1"
            ),
        }
        tuned = subprocess.run(
            ["bash", str(SCRIPT)],
            env=tuned_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert tuned.returncode == 1, tuned.stderr
        tuned_ini = (
            base
            / "run/tombraider-benchmark-720p-ultra-no-tessellation-ssao1.ini"
        )
        tuned_ini_windows = "Z:" + str(tuned_ini).replace("/", "\\")
        assert result_file.read_text().splitlines() == [
            "1",
            f"--appid 203160 -- -nolauncher -benchmarkini {tuned_ini_windows}",
        ]
        assert not tuned_ini.exists() and not tuned_ini.is_symlink()

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        priority_environment = {
            **benchmark_environment,
            "TOMB_RAIDER_RAKNET_NICE": "19",
        }
        priority = subprocess.run(
            ["bash", str(SCRIPT)],
            env=priority_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert priority.returncode == 1, priority.stderr
        assert affinity_result.read_text().splitlines() == [
            f"--watch --raknet-cpu1 --steam-base {base} --game-cpus 1-7 "
            "--raknet-nice 19 "
            "--wait-for-cpu-log --poll-seconds 0.25 "
            f"--lock-file {base}/runtime/tomb-raider-affinity.lock"
        ]

        invalid_priority = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "TOMB_RAIDER_RAKNET_NICE": "20"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_priority.returncode != 0
        assert "must be an integer from 0 through 19" in invalid_priority.stderr

        invalid_stream = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "TOMB_RAIDER_BVB_COMMAND_STREAM": "invalid"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_stream.returncode != 0
        assert "must be strict or shared" in invalid_stream.stderr

        invalid_mapped_memory = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "TOMB_RAIDER_BVB_MAPPED_MEMORY": "invalid"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_mapped_memory.returncode != 0
        assert "TOMB_RAIDER_BVB_MAPPED_MEMORY must be strict, shared, or direct" in (
            invalid_mapped_memory.stderr
        )

        invalid_first_rejection_diagnostic = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC": "invalid",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_first_rejection_diagnostic.returncode != 0
        assert "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC must be 0 or 1" in (
            invalid_first_rejection_diagnostic.stderr
        )

        invalid_descriptor_journal = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL": "invalid"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_descriptor_journal.returncode != 0
        assert "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL must be strict or shared" in (
            invalid_descriptor_journal.stderr
        )

        empty_first_rejection_diagnostic = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC": "",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert empty_first_rejection_diagnostic.returncode != 0
        assert "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC must be 0 or 1" in (
            empty_first_rejection_diagnostic.stderr
        )

        shared_without_bvb = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_COMMAND_STREAM": "shared",
                "STEAM_ARM64_BVB_VULKAN": "0",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert shared_without_bvb.returncode != 0
        assert "shared BVB command stream requires" in shared_without_bvb.stderr

        mapped_memory_without_bvb = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_COMMAND_STREAM": "strict",
                "TOMB_RAIDER_BVB_MAPPED_MEMORY": "direct",
                "STEAM_ARM64_BVB_VULKAN": "0",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert mapped_memory_without_bvb.returncode != 0
        assert "direct BVB mapped memory requires" in (
            mapped_memory_without_bvb.stderr
        )

        descriptor_journal_without_bvb = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_COMMAND_STREAM": "strict",
                "TOMB_RAIDER_BVB_MAPPED_MEMORY": "strict",
                "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL": "shared",
                "STEAM_ARM64_BVB_VULKAN": "0",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert descriptor_journal_without_bvb.returncode != 0
        assert "shared BVB descriptor journal requires" in (
            descriptor_journal_without_bvb.stderr
        )

        diagnostic_without_bvb = subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **environment,
                "TOMB_RAIDER_BVB_COMMAND_STREAM": "strict",
                "TOMB_RAIDER_BVB_MAPPED_MEMORY": "strict",
                "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL": "strict",
                "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC": "1",
                "STEAM_ARM64_BVB_VULKAN": "0",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert diagnostic_without_bvb.returncode != 0
        assert "BVB first-rejection diagnostic requires" in (
            diagnostic_without_bvb.stderr
        )

        (base / "run/native-runtime-dispatch/dispatch.sock").unlink()
        exclusive = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**benchmark_environment, "TOMB_RAIDER_GAME_CPUS": "2-7"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert exclusive.returncode == 1, exclusive.stderr
        assert affinity_result.read_text().splitlines() == [
            f"--watch --raknet-cpu1 --steam-base {base} --game-cpus 2-7 "
            "--wait-for-cpu-log --poll-seconds 0.25 "
            f"--lock-file {base}/runtime/tomb-raider-affinity.lock"
        ]
        assert "game_cpus=2-7" in (
            base / "run/tombraider-direct-dispatch.state"
        ).read_text()

        invalid_game_cpus = subprocess.run(
            ["bash", str(SCRIPT)],
            env={**environment, "TOMB_RAIDER_GAME_CPUS": "0-7"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert invalid_game_cpus.returncode != 0
        assert "must be 1-7 or 2-7" in invalid_game_cpus.stderr

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
        tmp_only_environment = {
            **environment,
            "TOMB_RAIDER_DIRECT_CHILD_PRELOAD": "lean-tmp-only",
        }
        tmp_only = subprocess.run(
            ["bash", str(SCRIPT)],
            env=tmp_only_environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert tmp_only.returncode == 1, tmp_only.stderr
        tmp_only_state = (
            base / "run/tombraider-direct-dispatch.state"
        ).read_text()
        assert "child_preload=lean-tmp-only" in tmp_only_state

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

        executable(
            topology_checker,
            "#!/usr/bin/env python3\n"
            "print('Tomb Raider CPU topology fix: disabled; SHA-256 ' + 'f' * 64)\n",
        )
        rejected_patch = subprocess.run(
            ["bash", str(SCRIPT)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected_patch.returncode == 1
        assert "CPU-topology fix is not enabled" in rejected_patch.stderr

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
