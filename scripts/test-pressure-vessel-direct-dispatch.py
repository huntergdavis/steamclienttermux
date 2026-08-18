#!/usr/bin/env python3

import importlib.util
import inspect
import json
import os
from pathlib import Path
import socket
import tempfile
from unittest import mock


SCRIPT = Path(__file__).with_name("pressure-vessel-direct-dispatch.py")
PLAN = (
    Path(__file__).resolve().parents[1]
    / "docs/evidence/tombraider-pressure-vessel-plan-20260817.json"
)
SPEC = importlib.util.spec_from_file_location("pv_direct_dispatch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> None:
    mapping_plan = [
        "--ro-bind",
        "/runtime/usr",
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
    ]
    binds, symlinks = MODULE.plan_mappings(mapping_plan)
    assert MODULE.translated_path("/bin/true", binds, symlinks) == "/runtime/usr/bin/true"
    serve_source = inspect.getsource(MODULE.serve)
    assert "environment" not in serve_source
    assert "REQUEST_RECEIVED=1" in serve_source
    assert "DISPATCH_STATUS=" in serve_source
    arm64_source = inspect.getsource(MODULE.run_proton_arm64_cmd_smoke)
    assert "proton-arm64-wine-" in arm64_source
    assert "trace_path" in arm64_source
    assert 'diagnostics == "1"' in arm64_source
    loader_source = inspect.getsource(MODULE.run_loader_child)
    assert '"-k"' in loader_source
    assert '"trace=%process,%signal,%network"' in loader_source
    assert "os.chdir(working_directory)" in loader_source
    runtime_source = inspect.getsource(MODULE.selected_runtime)
    assert '"usr/lib/aarch64-linux-gnu/pulseaudio"' in runtime_source

    with tempfile.TemporaryDirectory(prefix="loader-child-cwd.") as directory:
        root = Path(directory)
        working_directory = root / "game"
        working_directory.mkdir()
        result = root / "cwd.txt"
        status, tracer = MODULE.run_loader_child(
            Path(os.sys.executable),
            [
                os.sys.executable,
                "-c",
                (
                    "import os, pathlib; "
                    f"pathlib.Path({str(result)!r}).write_text(os.getcwd())"
                ),
            ],
            os.environ.copy(),
            [],
            [],
            working_directory=working_directory,
        )
        assert status == 0
        assert tracer == 0
        assert result.read_text(encoding="utf-8") == str(working_directory)

    available_cpus = os.sched_getaffinity(0)
    selected_cpu = min(available_cpus)
    with tempfile.TemporaryDirectory(prefix="loader-child-affinity.") as directory:
        result = Path(directory) / "affinity.txt"
        status, tracer = MODULE.run_loader_child(
            Path(os.sys.executable),
            [
                os.sys.executable,
                "-c",
                (
                    "import os, pathlib; "
                    f"pathlib.Path({str(result)!r}).write_text("
                    "os.environ['PROTON_CPU_TOPOLOGY'] + ';' + "
                    "','.join(str(cpu) for cpu in sorted(os.sched_getaffinity(0))))"
                ),
            ],
            os.environ.copy(),
            [],
            [],
            cpu_affinity={selected_cpu},
            match_proton_cpu_topology=True,
            minimum_cpu_affinity_count=1,
        )
        assert status == 0
        assert tracer == 0
        assert result.read_text(encoding="utf-8") == (
            f"1:{selected_cpu};{selected_cpu}"
        )

    topology_environment = "STEAM_ARM64_DIRECT_STARTUP_TOPOLOGY"
    original_topology = os.environ.pop(topology_environment, None)
    try:
        assert not MODULE.require_full_startup_topology()
        os.environ[topology_environment] = "full"
        assert MODULE.require_full_startup_topology()
        os.environ[topology_environment] = "invalid"
        try:
            MODULE.require_full_startup_topology()
        except MODULE.DispatchError as error:
            assert "must be available or full" in str(error)
        else:
            raise AssertionError("invalid startup topology was accepted")
    finally:
        if original_topology is None:
            os.environ.pop(topology_environment, None)
        else:
            os.environ[topology_environment] = original_topology

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert plan["kind"] == "pressure-vessel-bwrap-plan"
    assert len(plan["bwrap_args"]) == 864
    assert len(plan["fd_sources"]) == 11
    assert plan["payload_argv"][16:] == [
        "/data/data/com.termux/files/home/steam-arm64/client/steamapps/common/Proton 11.0 (ARM64)/proton",
        "waitforexitandrun",
        "/data/data/com.termux/files/home/steam-arm64/removable-library/steamapps/common/Tomb Raider/TombRaider.exe",
        "-nolauncher",
    ]
    plan_binds, plan_symlinks = MODULE.plan_mappings(plan["bwrap_args"])
    assert MODULE.translated_path(
        plan["payload_argv"][0], plan_binds, plan_symlinks
    ) == (
        "/data/data/com.termux/files/home/steam-arm64/client/steamapps/common/"
        "SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/"
        "steam-runtime-tools-0/pv-adverb"
    )
    tablet_base = Path("/data/data/com.termux/files/home/steam-arm64")
    proton, game = MODULE.validated_tombraider_command(
        tablet_base, plan["payload_argv"]
    )
    assert proton == (
        tablet_base / "client/steamapps/common/Proton 11.0 (ARM64)/proton"
    )
    assert game == (
        tablet_base
        / "removable-library/steamapps/common/Tomb Raider/TombRaider.exe"
    )
    benchmark_payload = [*plan["payload_argv"], "-benchmark"]
    assert MODULE.validated_tombraider_command(
        tablet_base, benchmark_payload, benchmark=True
    ) == (proton, game)
    try:
        MODULE.validated_tombraider_command(
            tablet_base, benchmark_payload, benchmark=False
        )
    except MODULE.DispatchError:
        pass
    else:
        raise AssertionError("normal mode accepted benchmark arguments")
    with tempfile.TemporaryDirectory(prefix="proton-cmd-smoke.") as directory:
        fixture_base = Path(directory)
        fixture_runtime = fixture_base / "runtime"
        fixture_python = fixture_runtime / "usr/bin/python3"
        fixture_proton = (
            fixture_base
            / "client/steamapps/common/Proton 11.0 (ARM64)/proton"
        )
        fixture_command = (
            fixture_base
            / "client/steamapps/common/Proton 11.0 (ARM64)"
            / "files/lib/wine/x86_64-windows/cmd.exe"
        )
        for executable in (fixture_python, fixture_proton, fixture_command):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"fixture")
            executable.chmod(0o700)
        assert MODULE.proton_smoke_command(
            fixture_base, fixture_runtime, fixture_proton, "proton-cmd"
        ) == [
            str(fixture_python),
            str(fixture_proton),
            "waitforexitandrun",
            str(fixture_command),
            "/d",
            "/c",
            "exit",
            "/b",
            "0",
        ]
        fixture_arm64_command = (
            fixture_base
            / "client/steamapps/common/Proton 11.0 (ARM64)"
            / "files/lib/wine/aarch64-windows/cmd.exe"
        )
        fixture_arm64_command.parent.mkdir(parents=True, exist_ok=True)
        fixture_arm64_command.write_bytes(b"fixture")
        fixture_arm64_command.chmod(0o700)
        assert MODULE.proton_smoke_command(
            fixture_base, fixture_runtime, fixture_proton, "proton-arm64-cmd"
        )[3] == str(fixture_arm64_command)
        assert MODULE.proton_smoke_environment("proton-entry") == {}
        assert MODULE.proton_smoke_environment("proton-cmd") == {
            "WINEDEBUG": "-all"
        }
        assert MODULE.proton_smoke_environment("proton-arm64-cmd") == {
            "WINEDEBUG": "-all"
        }
        assert MODULE.proton_smoke_environment("tombraider") == {
            "WINEDEBUG": "-all"
        }
        assert MODULE.proton_smoke_environment("tombraider-benchmark") == {
            "WINEDEBUG": "-all"
        }
        audio_runtime = fixture_base / "audio-runtime"
        alsa_data = audio_runtime / "usr/share/alsa"
        pulse_config = alsa_data / "alsa.conf.d/50-pulseaudio.conf"
        plugin_directory = (
            audio_runtime / "usr/lib/aarch64-linux-gnu/alsa-lib"
        )
        pulse_config.parent.mkdir(parents=True)
        plugin_directory.mkdir(parents=True)
        (alsa_data / "alsa.conf").write_text("# base\n", encoding="utf-8")
        pulse_config.write_text("# pulse\n", encoding="utf-8")
        audio_environment = MODULE.direct_audio_environment(
            fixture_base, audio_runtime
        )
        direct_config = (
            fixture_base / "run/native-runtime-dispatch/alsa-direct.conf"
        )
        assert audio_environment == {
            "ALSA_CONFIG_PATH": str(direct_config),
            "ALSA_CONFIG_DIR": str(alsa_data),
            "ALSA_PLUGIN_DIR": str(plugin_directory),
        }
        assert MODULE.direct_game_environment(
            fixture_base, audio_runtime
        ) == {
            **audio_environment,
            "TZ": "UTC0",
        }
        stale_fex = {
            "FEX_MAXINST": "500",
            "FEX_TSOENABLED": "1",
            "FEX_HALFBARRIERTSOENABLED": "1",
            "STEAM_FEX_TSOENABLED": "1",
            "UNRELATED": "preserved",
        }
        MODULE.apply_direct_fex_profile(stale_fex, "fast")
        assert stale_fex["STEAM_ARM64_FEX_PROFILE"] == "fast"
        assert stale_fex["FEX_MAXINST"] == "5000"
        assert stale_fex["FEX_TSOENABLED"] == "0"
        assert stale_fex["FEX_HALFBARRIERTSOENABLED"] == "0"
        assert stale_fex["STEAM_FEX_TSOENABLED"] == "0"
        assert stale_fex["FEX_MULTIBLOCK"] == "1"
        assert stale_fex["UNRELATED"] == "preserved"
        MODULE.apply_direct_fex_profile(stale_fex, "proton")
        assert stale_fex == {
            "STEAM_ARM64_FEX_PROFILE": "proton",
            "UNRELATED": "preserved",
        }
        try:
            MODULE.apply_direct_fex_profile(stale_fex, "unsafe")
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("unsupported direct FEX profile was accepted")
        assert direct_config.stat().st_mode & 0o777 == 0o600
        assert direct_config.read_text(encoding="utf-8") == (
            f"<{alsa_data / 'alsa.conf'}>\n"
            f"<{pulse_config}>\n"
            "pcm.!default {\n"
            "    type pulse\n"
            "}\n"
            "ctl.!default {\n"
            "    type pulse\n"
            "}\n"
        )
        proc_net = fixture_base / "config/proc-net"
        proc_net.mkdir(parents=True, mode=0o700)
        (proc_net / "route").write_text("route\n", encoding="utf-8")
        (proc_net / "ipv6_route").write_text("", encoding="utf-8")
        (proc_net / "route").chmod(0o600)
        (proc_net / "ipv6_route").chmod(0o600)
        assert MODULE.validated_proc_net_shadow(fixture_base) == proc_net
        unexpected = proc_net / "tcp"
        unexpected.write_text("unsafe\n", encoding="utf-8")
        try:
            MODULE.validated_proc_net_shadow(fixture_base)
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("proc-net validator accepted an extra file")
        unexpected.unlink()
        route = proc_net / "route"
        route.unlink()
        route.symlink_to(proc_net / "ipv6_route")
        try:
            MODULE.validated_proc_net_shadow(fixture_base)
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("proc-net validator accepted a route symlink")
        route.unlink()
        route.write_text("route\n", encoding="utf-8")
        route.chmod(0o600)
        proc_stat = fixture_base / "config/proc-stat"
        proc_stat.write_text(
            "cpu  20 0 10 100 0 0 0 0 0 0\n"
            "cpu0 10 0 5 50 0 0 0 0 0 0\n"
            "cpu1 10 0 5 50 0 0 0 0 0 0\n"
            "intr 0\n",
            encoding="ascii",
        )
        proc_stat.chmod(0o600)
        assert MODULE.validated_proc_stat_shadow(fixture_base) == proc_stat
        proc_stat.write_text(
            "cpu 20 0 10 100\ncpu1 10 0 5 50\n", encoding="ascii"
        )
        try:
            MODULE.validated_proc_stat_shadow(fixture_base)
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("proc-stat validator accepted a missing cpu0 row")
        proc_stat.unlink()
        proc_stat.symlink_to(proc_net / "ipv6_route")
        try:
            MODULE.validated_proc_stat_shadow(fixture_base)
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("proc-stat validator accepted a symlink")
        proc_stat.unlink()
        proc_stat.write_text(
            "cpu 20 0 10 100\ncpu0 10 0 5 50\n", encoding="ascii"
        )
        proc_stat.chmod(0o600)
        wine_debug = (
            "+timestamp,+pid,+tid,+process,+module,+loaddll,+seh,"
            "+winsock,+wininet,+winhttp,+iphlpapi,+nsi,"
            "+secur32,+schannel"
        )
        assert MODULE.proton_smoke_environment("proton-cmd", True) == {
            "WINEDEBUG": wine_debug
        }
        assert MODULE.proton_smoke_environment("proton-arm64-cmd", True) == {
            "WINEDEBUG": wine_debug
        }
        assert MODULE.proton_smoke_environment("tombraider", True) == {
            "WINEDEBUG": wine_debug
        }
    assert MODULE.request_environment(
        {
            "environment": [
                "STEAM_COMPAT_APP_ID=203160",
                "LD_PRELOAD=unsafe",
                "TGCOMPAT_USERFAULTFD_ENOSYS=unsafe",
                "BVB_VULKAN_TRACE_FILE=unsafe",
                "STEAM_ARM64_VULKAN_TRACE_PRELOAD=unsafe",
                "STEAM_ARM64_VULKAN_TRACE_FILE=unsafe",
            ]
        }
    ) == {"STEAM_COMPAT_APP_ID": "203160"}
    with tempfile.TemporaryDirectory(prefix="vulkan-trace-validation.") as directory:
        home = Path(directory)
        base = home / "steam-arm64"
        logs = base / "logs"
        logs.mkdir(parents=True, mode=0o700)
        preload = (
            home
            / "bionic-vulkan-bridge/out/glibc/libbvb-vulkan-resolve-trace.so"
        )
        preload.parent.mkdir(parents=True)
        preload.write_bytes(b"tracer")
        preload.chmod(0o600)
        trace = logs / "tombraider-vulkan-resolve-20260818T120000Z-123.tsv"
        trace.write_text("", encoding="ascii")
        trace.chmod(0o600)
        trace_environment = {
            "HOME": str(home),
            "STEAM_ARM64_VULKAN_TRACE_PRELOAD": str(preload),
            "STEAM_ARM64_VULKAN_TRACE_FILE": str(trace),
        }
        with mock.patch.dict(os.environ, trace_environment, clear=False):
            assert MODULE.validated_vulkan_trace(base) == (preload, trace)
            os.environ["STEAM_ARM64_VULKAN_TRACE_PRELOAD"] = str(home / "other.so")
            try:
                MODULE.validated_vulkan_trace(base)
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("Vulkan trace validator accepted an arbitrary preload")
    invocation_source = inspect.getsource(MODULE.pv_smoke_invocation)
    assert "libtgcompat-robust.so" in invocation_source
    assert "libtgcompat-mprotect.so" in invocation_source
    assert '("lean", "lean-tmp-only", "lean-debug-wait")' in invocation_source
    assert '"lean-tmp-only"' in invocation_source
    assert '"lean-debug-wait"' in invocation_source
    assert "steam-arm64-debug-wait.so" in invocation_source
    assert "entry_preloads[2]" in invocation_source
    assert "TGCOMPAT_EXEC_LD_PRELOAD" in invocation_source
    assert "TGCOMPAT_EXEC_FINAL_PATH_PREFIX" in invocation_source
    assert "TGCOMPAT_EXEC_FINAL_LD_PRELOAD" in invocation_source
    assert "TGCOMPAT_EXEC_FINAL_PROC_SELF_EXE" in invocation_source
    assert "final_preloads.append(vulkan_trace[0])" in invocation_source
    assert 'environment["BVB_VULKAN_TRACE_FILE"]' in invocation_source
    assert "entry_preloads[4]" in invocation_source
    assert "entry_preloads[1]" in invocation_source
    assert 'child_preload_profile == "lean-tmp-only"' in invocation_source
    assert '"TGCOMPAT_USERFAULTFD_ENOSYS": "1"' in invocation_source
    assert '"TGCOMPAT_PROC_NET": str(proc_net_shadow)' in invocation_source
    assert '"TGCOMPAT_PROC_STAT": str(proc_stat_shadow)' in invocation_source
    assert '("tombraider", "tombraider-benchmark")' in invocation_source
    game_source = inspect.getsource(MODULE.run_tombraider)
    assert '"tombraider"' in game_source
    assert '"removable-library/steamapps/common/Tomb Raider"' in game_source
    assert "cpu_affinity=set(range(8))" in game_source
    assert "match_proton_cpu_topology=True" in game_source
    assert "minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0)" in game_source
    benchmark_source = inspect.getsource(MODULE.run_tombraider_benchmark)
    assert '"tombraider-benchmark"' in benchmark_source
    assert "cpu_affinity=set(range(8))" in benchmark_source
    assert "match_proton_cpu_topology=True" in benchmark_source
    assert "minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0)" in benchmark_source
    diagnostic_source = inspect.getsource(MODULE.run_tombraider_diagnostic)
    assert "tombraider-direct-process-" in diagnostic_source
    assert "trace_path" in diagnostic_source
    assert "False" in diagnostic_source
    assert '"tombraider", True' in diagnostic_source
    assert "cpu_affinity=set(range(8))" in diagnostic_source
    assert "match_proton_cpu_topology=True" in diagnostic_source
    assert "minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0)" in diagnostic_source
    with tempfile.TemporaryDirectory(prefix="removable-game.") as directory:
        game_fixture = Path(directory) / "TombRaider.exe"
        game_fixture.write_bytes(b"game")
        game_fixture.chmod(0o770)
        MODULE.validate_removable_windows_file(game_fixture, "fixture game")
        game_link = game_fixture.with_name("linked.exe")
        game_link.symlink_to(game_fixture)
        try:
            MODULE.validate_removable_windows_file(game_link, "fixture link")
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("removable executable validator accepted a symlink")
    with tempfile.TemporaryDirectory(prefix="runtime-python.") as directory:
        runtime_fixture = Path(directory)
        python_target = runtime_fixture / "usr/bin/python3.13"
        python_target.parent.mkdir(parents=True)
        python_target.write_bytes(b"python")
        python_target.chmod(0o700)
        python_link = python_target.with_name("python3")
        python_link.symlink_to(python_target.name)
        MODULE.validate_runtime_executable(
            python_link, runtime_fixture, "fixture Runtime Python"
        )
        outside = runtime_fixture.parent / f"{runtime_fixture.name}-outside"
        outside.write_bytes(b"outside")
        outside.chmod(0o700)
        escaping_link = python_target.with_name("python-outside")
        escaping_link.symlink_to(outside)
        try:
            MODULE.validate_runtime_executable(
                escaping_link, runtime_fixture, "escaping Runtime Python"
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("Runtime executable validator accepted an escape")
        outside.unlink()

    with (
        tempfile.TemporaryFile() as source8,
        tempfile.TemporaryFile() as source9,
        tempfile.TemporaryFile() as source10,
    ):
        fd8, fd9, fd10 = source8.fileno(), source9.fileno(), source10.fileno()
        bwrap = [*mapping_plan, "--ro-bind-data", str(fd8), "/etc/passwd"]
        payload = [
            "/pv-adverb",
            "--fd",
            str(fd9),
            f"--assign-fd=1={fd10}",
            "--",
            "/bin/true",
        ]
        assert MODULE.referenced_fd_numbers(bwrap, payload) == sorted([fd8, fd9, fd10])
        source8.write(b"fd-payload")
        source8.flush()
        source8.seek(0)
        left, right = socket.socketpair()
        with left, right:
            request = {
                "schema_version": MODULE.SCHEMA_VERSION,
                "kind": MODULE.KIND,
                "cwd": "/fixture",
                "bwrap_args": bwrap,
                "payload_argv": payload,
                "environment": ["FIXTURE=value"],
                "fd_numbers": [fd8],
            }
            MODULE.send_request(left, request, [fd8])
            received, descriptors = MODULE.receive_request(right)
            MODULE.validate_request(received, descriptors)
            assert os.pread(descriptors[0], 10, 0) == b"fd-payload"
            os.close(descriptors[0])
            MODULE.send_response(right, 0, 0)
            assert MODULE.receive_response(left) == (0, 0)

    print("Pressure Vessel direct dispatch tests: PASS")


if __name__ == "__main__":
    main()
