#!/usr/bin/env python3

import importlib.util
from itertools import product
import inspect
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import time
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

assert MODULE.NMS_PROTON_MARKER["patch_offset"] == 0x800E8


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
    assert "direct_diagnostics_enabled" in arm64_source
    tombraider_source = inspect.getsource(MODULE.run_tombraider)
    assert "direct_diagnostics_enabled" in tombraider_source
    loader_source = inspect.getsource(MODULE.run_loader_child)
    assert '"-k"' in loader_source
    assert '"trace=%process,%signal,%network"' in loader_source
    assert "os.chdir(working_directory)" in loader_source
    runtime_source = inspect.getsource(MODULE.selected_runtime)
    assert '"usr/lib/aarch64-linux-gnu/pulseaudio"' in runtime_source

    with tempfile.TemporaryDirectory(prefix="direct-start-gate.") as directory:
        base = Path(directory)
        gate_directory = base / "run/bvb"
        gate_directory.mkdir(parents=True, mode=0o700)
        gate = gate_directory / "tombraider-start-20260821T010203Z-42.gate"
        waiting = Path(f"{gate}.waiting")
        failures: list[BaseException] = []

        def wait_for_gate() -> None:
            try:
                MODULE.wait_for_direct_start_gate(base)
            except BaseException as error:  # test thread must report failures
                failures.append(error)

        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_DIRECT_START_GATE": str(gate),
                "STEAM_ARM64_DIRECT_START_GATE_TIMEOUT": "5",
            },
            clear=False,
        ):
            thread = threading.Thread(target=wait_for_gate)
            thread.start()
            deadline = time.monotonic() + 2.0
            while not waiting.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert waiting.is_file() and not waiting.is_symlink()
            descriptor = os.open(
                gate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.close(descriptor)
            thread.join(timeout=2.0)
            assert not thread.is_alive()
        assert failures == []
        assert not gate.exists()
        assert not waiting.exists()

    with tempfile.TemporaryDirectory(prefix="vulkan-icd-select.") as directory:
        base = Path(directory)
        turnip = base / "mesa-kgsl/icd.d/freedreno-private.json"
        bvb = base / "bvb/icd.d/bvb_icd.aarch64.json"
        turnip.parent.mkdir(parents=True)
        bvb.parent.mkdir(parents=True)
        turnip.write_text("{}\n", encoding="ascii")
        bvb.write_text("{}\n", encoding="ascii")
        turnip.chmod(0o600)
        bvb.chmod(0o600)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STEAM_ARM64_BVB_VULKAN", None)
            assert MODULE.validated_host_vulkan_icd(base) == turnip
        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_BVB_VULKAN": "1",
                "BVB_BRIDGE_SOCKET": "/private/bvb.sock",
                "BVB_ICD_DIAGNOSTICS": "1",
                "BVB_FRAME_PROFILE": "1",
                "BVB_ICD_PROBE_WSI": "1",
                "BVB_COMMAND_STREAM": "smuggled",
                "BVB_MAPPED_MEMORY": "smuggled",
                "BVB_DESCRIPTOR_JOURNAL": "smuggled",
                "BVB_FIRST_REJECTION_DIAGNOSTIC": "smuggled",
                "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC": "smuggled",
            },
            clear=False,
        ):
            assert MODULE.validated_host_vulkan_icd(base) == bvb
            os.environ.pop("STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM", None)
            os.environ.pop("STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY", None)
            os.environ.pop("STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL", None)
            os.environ.pop(
                "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC", None
            )
            default_environment = MODULE.bvb_vulkan_environment()
            assert "BVB_COMMAND_STREAM" not in default_environment
            assert "BVB_MAPPED_MEMORY" not in default_environment
            assert "BVB_DESCRIPTOR_JOURNAL" not in default_environment
            assert "BVB_FIRST_REJECTION_DIAGNOSTIC" not in default_environment
            for (
                command_stream,
                mapped_memory,
                descriptor_journal,
                first_rejection_diagnostic,
            ) in product(("strict", "shared"),
                         ("strict", "shared", "direct"),
                         ("strict", "shared"), ("0", "1")):
                        os.environ["STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM"] = (
                            command_stream
                        )
                        os.environ["STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY"] = (
                            mapped_memory
                        )
                        os.environ[
                            "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL"
                        ] = descriptor_journal
                        os.environ[
                            "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC"
                        ] = first_rejection_diagnostic
                        selected = MODULE.bvb_vulkan_environment()
                        assert selected == {
                            "BVB_BRIDGE_SOCKET": "/private/bvb.sock",
                            "BVB_ICD_DIAGNOSTICS": "1",
                            "BVB_ICD_PROBE_WSI": "1",
                            **(
                                {"BVB_COMMAND_STREAM": "shared"}
                                if command_stream == "shared"
                                else {}
                            ),
                            **(
                                {"BVB_MAPPED_MEMORY": mapped_memory}
                                if mapped_memory != "strict"
                                else {}
                            ),
                            **(
                                {"BVB_DESCRIPTOR_JOURNAL": "shared"}
                                if descriptor_journal == "shared"
                                else {}
                            ),
                            **(
                                {"BVB_FIRST_REJECTION_DIAGNOSTIC": "1"}
                                if first_rejection_diagnostic == "1"
                                else {}
                            ),
                            "BVB_FRAME_PROFILE": "1",
                            "VK_LOADER_DEBUG": "error,warn,driver",
                        }
            os.environ["BVB_ICD_DIAGNOSTICS"] = "0"
            os.environ["BVB_FRAME_PROFILE"] = "0"
            quiet_environment = MODULE.bvb_vulkan_environment()
            assert "BVB_ICD_DIAGNOSTICS" not in quiet_environment
            assert "BVB_FRAME_PROFILE" not in quiet_environment
            assert "VK_LOADER_DEBUG" not in quiet_environment
            os.environ["BVB_ICD_DIAGNOSTICS"] = "1"
            os.environ["STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM"] = "invalid"
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("invalid BVB command-stream selector was accepted")
            os.environ["STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM"] = "strict"
            os.environ["STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY"] = "invalid"
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("invalid BVB mapped-memory selector was accepted")
            os.environ["STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY"] = "strict"
            os.environ["STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL"] = "invalid"
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError(
                    "invalid BVB descriptor-journal selector was accepted"
                )
            os.environ["STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL"] = "strict"
            os.environ[
                "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC"
            ] = "invalid"
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError(
                    "invalid BVB first-rejection diagnostic selector was accepted"
                )
        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_BVB_VULKAN": "0",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "shared",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "strict",
            },
            clear=False,
        ):
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("shared command stream without BVB was accepted")
        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_BVB_VULKAN": "0",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "strict",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "direct",
                "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL": "strict",
            },
            clear=False,
        ):
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("direct mapped memory without BVB was accepted")
        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_BVB_VULKAN": "0",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "strict",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "strict",
                "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL": "shared",
            },
            clear=False,
        ):
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("shared descriptor journal without BVB was accepted")
        with mock.patch.dict(
            os.environ,
            {
                "STEAM_ARM64_BVB_VULKAN": "0",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM": "strict",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY": "strict",
                "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL": "strict",
                "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC": "1",
            },
            clear=False,
        ):
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError(
                    "first-rejection diagnostic without BVB was accepted"
                )
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_BVB_VULKAN": "invalid"}, clear=False
        ):
            try:
                MODULE.validated_host_vulkan_icd(base)
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("invalid BVB Vulkan selector was accepted")
        with mock.patch.dict(
            os.environ,
            {"STEAM_ARM64_BVB_VULKAN": "1", "BVB_BRIDGE_SOCKET": "relative"},
            clear=False,
        ):
            try:
                MODULE.bvb_vulkan_environment()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("relative BVB socket was accepted")

    with tempfile.TemporaryDirectory(prefix="nms-mangohud.") as directory:
        root = Path(directory)
        base = root / "steam-arm64"
        logs = base / "logs"
        output = logs / "no-mans-sky-fps-20260825T010203Z-42"
        logs.mkdir(parents=True, mode=0o700)
        logs.chmod(0o700)
        output.mkdir(mode=0o700)
        prefix = root / "usr"
        layer_directory = prefix / "glibc/share/vulkan/implicit_layer.d"
        layer_directory.mkdir(parents=True)
        library = prefix / "glibc/lib/mangohud/libMangoHud.so"
        library.parent.mkdir(parents=True)
        elf = bytearray(1024 * 1024)
        elf[:6] = b"\x7fELF\x02\x01"
        elf[18:20] = (183).to_bytes(2, "little")
        library.write_bytes(elf)
        library.chmod(0o700)
        manifest = layer_directory / "MangoHud.aarch64.json"
        manifest.write_text(
            json.dumps(
                {
                    "file_format_version": "1.0.0",
                    "layer": {
                        "name": "VK_LAYER_MANGOHUD_overlay_aarch64",
                        "type": "GLOBAL",
                        "library_path": str(library),
                        "enable_environment": {"MANGOHUD": "1"},
                    },
                }
            ),
            encoding="utf-8",
        )
        manifest.chmod(0o600)
        config = output / "MangoHud.conf"
        config.write_text(
            "\n".join(
                (
                    "legacy_layout=0",
                    "cpu_stats=0",
                    "gpu_stats=0",
                    "battery=0",
                    "device_battery=",
                    "throttling_status=0",
                    "fps",
                    "fps_only=1",
                    "frametime=0",
                    "position=top-left",
                    "fps_metrics=avg,0.01,0.001",
                    "autostart_log=1",
                    "log_duration=1800",
                    "log_interval=100",
                    f"output_folder={output}",
                    "benchmark_percentiles=97,AVG,1,0.1",
                    "log_versioning",
                    "",
                )
            ),
            encoding="utf-8",
        )
        config.chmod(0o600)
        selected = {
            "PREFIX": str(prefix),
            "STEAM_ARM64_DIRECT_NMS_MANGOHUD": "1",
            "STEAM_ARM64_DIRECT_NMS_MANGOHUD_CONFIG": str(config),
        }
        with mock.patch.dict(os.environ, selected, clear=False):
            assert MODULE.nms_mangohud_environment(base, "no-mans-sky") == {
                "MANGOHUD": "1",
                "MANGOHUD_CONFIGFILE": str(config),
                "VK_INSTANCE_LAYERS": "VK_LAYER_MANGOHUD_overlay_aarch64",
                "VK_LAYER_PATH": str(layer_directory),
            }
            try:
                MODULE.nms_mangohud_environment(base, "tombraider")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("NMS MangoHud was accepted for another game")
            config.write_text(config.read_text() + "unknown=true\n")
            try:
                MODULE.nms_mangohud_environment(base, "no-mans-sky")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("unexpected MangoHud options were accepted")

    with tempfile.TemporaryDirectory(prefix="nms-xinput.") as directory:
        base = Path(directory) / "steam-arm64"
        library = (
            base
            / "removable-library/steamapps/common/No Man's Sky/Binaries"
            / "xinput9_1_0.dll"
        )
        library.parent.mkdir(parents=True)
        library.write_bytes(b"x" * 16896)
        # Android removable storage presents fixed group-write mode bits.
        library.chmod(0o770)
        expected_hash = (
            "11e928f5e337680efa6baa6e2a839795a79bd752387b1e0956ea805f1a25fa43"
        )
        with (
            mock.patch.dict(
                os.environ, {"STEAM_ARM64_DIRECT_NMS_XINPUT": "1"}, clear=False
            ),
            mock.patch.object(MODULE, "sha256_file", return_value=expected_hash),
        ):
            assert MODULE.nms_xinput_environment(base, "no-mans-sky") == {
                "STEAMCLIENTTERMUX_NMS_XINPUT": "1",
                "WINEDLLOVERRIDES": "xinput9_1_0=n,b",
            }
            try:
                MODULE.nms_xinput_environment(base, "tombraider")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("NMS XInput was accepted for another game")
            library.write_bytes(b"short")
            try:
                MODULE.nms_xinput_environment(base, "no-mans-sky")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("wrong-size NMS XInput bridge was accepted")
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_NMS_XINPUT": "0"}, clear=False
        ):
            assert MODULE.nms_xinput_environment(base, "no-mans-sky") == {}

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
    with tempfile.TemporaryDirectory(prefix="nms-contained-proton.") as directory:
        nms_base = Path(directory)
        nms_tool = (
            nms_base
            / "client/compatibilitytools.d"
            / MODULE.NMS_PROTON_TOOL_DIRECTORY
        )
        nms_tool.mkdir(parents=True, mode=0o700)
        nms_tool.chmod(0o700)
        nms_proton = nms_tool / "proton"
        nms_proton.write_text("#!/bin/sh\nexit 0\n")
        nms_proton.chmod(0o700)
        nms_marker = nms_tool / ".steamclienttermux-nms-proton.json"
        nms_marker.write_text(json.dumps(MODULE.NMS_PROTON_MARKER))
        nms_marker.chmod(0o600)
        nms_dll = nms_tool / "files/lib/wine/aarch64-windows/lsteamclient.dll"
        nms_dll.parent.mkdir(parents=True)
        nms_dll.write_bytes(b"reviewed fixture")
        nms_dll.chmod(0o600)
        nms_loaders = {
            nms_tool / relative: expected_digest
            for relative, expected_digest in (
                MODULE.NMS_PROTON_LOADER_CHAIN_SHA256.items()
            )
        }
        for nms_loader in nms_loaders:
            nms_loader.parent.mkdir(parents=True, exist_ok=True)
            nms_loader.write_bytes(b"reviewed loader fixture")
            nms_loader.chmod(0o700)
        nms_loader_root = nms_tool / "files/lib/wine/aarch64-unix/ntdll.so"
        nms_game = (
            nms_base
            / "removable-library/steamapps/common/No Man's Sky/Binaries/NMS.exe"
        )
        nms_payload = [
            *plan["payload_argv"][:16],
            str(nms_proton),
            "waitforexitandrun",
            str(nms_game),
        ]
        original_sha256_file = MODULE.sha256_file
        MODULE.sha256_file = lambda path: (
            MODULE.NMS_PROTON_DLL_SHA256
            if path == nms_dll
            else nms_loaders[path]
            if path in nms_loaders
            else original_sha256_file(path)
        )
        try:
            assert MODULE.validated_no_mans_sky_command(
                nms_base, nms_payload
            ) == (nms_proton, nms_game)
            try:
                MODULE.validated_no_mans_sky_command(
                    nms_base, [*nms_payload, "--unexpected"]
                )
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError(
                    "No Man's Sky validator accepted extra arguments"
                )
            nms_loader_root.unlink()
            nms_loader_root.symlink_to(nms_dll)
            try:
                MODULE.validated_no_mans_sky_command(
                    nms_base, nms_payload
                )
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError(
                    "No Man's Sky validator accepted a symlinked loader root"
                )
        finally:
            MODULE.sha256_file = original_sha256_file
    benchmark_payload = [*plan["payload_argv"], "-benchmark"]
    assert MODULE.validated_tombraider_command(
        tablet_base, benchmark_payload, benchmark=True
    ) == (proton, game)
    with tempfile.TemporaryDirectory(prefix="tombraider-high-ini.") as directory:
        high_base = Path(directory)
        (high_base / "run").mkdir()
        high_ini = high_base / "run/tombraider-benchmark-720p-high.ini"
        high_ini.write_text(
            "QualityLevel = 2\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1280\n"
            "FullscreenHeight = 720\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
        )
        high_ini.chmod(0o600)
        high_proton = (
            high_base
            / "client/steamapps/common/Proton 11.0 (ARM64)/proton"
        )
        high_game = (
            high_base
            / "removable-library/steamapps/common/Tomb Raider/TombRaider.exe"
        )
        high_windows_ini = "Z:" + str(high_ini).replace("/", "\\")
        high_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            high_windows_ini,
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            high_payload,
            benchmark=True,
            benchmark_preset="720p-high",
        ) == (high_proton, high_game)
        high_ini.write_text(high_ini.read_text().replace("QualityLevel = 2", "QualityLevel = 4"))
        try:
            MODULE.validated_tombraider_command(
                high_base,
                high_payload,
                benchmark=True,
                benchmark_preset="720p-high",
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified High benchmark INI was accepted")

        no_tessellation_ini = (
            high_base
            / "run/tombraider-benchmark-720p-ultra-no-tessellation.ini"
        )
        no_tessellation_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1280\n"
            "FullscreenHeight = 720\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
        )
        no_tessellation_ini.chmod(0o600)
        no_tessellation_windows_ini = "Z:" + str(no_tessellation_ini).replace(
            "/", "\\"
        )
        no_tessellation_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            no_tessellation_windows_ini,
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            no_tessellation_payload,
            benchmark=True,
            benchmark_preset="720p-ultra-no-tessellation",
        ) == (high_proton, high_game)
        no_tessellation_ini.write_text(
            no_tessellation_ini.read_text().replace(
                "EnableTessellation = 0", "EnableTessellation = 1"
            )
        )
        try:
            MODULE.validated_tombraider_command(
                high_base,
                no_tessellation_payload,
                benchmark=True,
                benchmark_preset="720p-ultra-no-tessellation",
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified tessellation override was accepted")

        tuned_ini = (
            high_base
            / "run/tombraider-benchmark-720p-ultra-no-tessellation-ssao1.ini"
        )
        tuned_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1280\n"
            "FullscreenHeight = 720\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
            "SSAOMode = 1\n"
        )
        tuned_ini.chmod(0o600)
        tuned_windows_ini = "Z:" + str(tuned_ini).replace("/", "\\")
        tuned_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            tuned_windows_ini,
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            tuned_payload,
            benchmark=True,
            benchmark_preset="720p-ultra-no-tessellation-ssao1",
        ) == (high_proton, high_game)
        tuned_ini.write_text(tuned_ini.read_text().replace("SSAOMode = 1", "SSAOMode = 2"))
        try:
            MODULE.validated_tombraider_command(
                high_base,
                tuned_payload,
                benchmark=True,
                benchmark_preset="720p-ultra-no-tessellation-ssao1",
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified SSAO override was accepted")

        dof_tuned_ini = (
            high_base
            / "run/tombraider-benchmark-720p-ultra-no-tessellation-ssao1-dof1.ini"
        )
        dof_tuned_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1280\n"
            "FullscreenHeight = 720\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
            "SSAOMode = 1\n"
            "DOFQuality = 1\n"
        )
        dof_tuned_ini.chmod(0o600)
        dof_tuned_windows_ini = "Z:" + str(dof_tuned_ini).replace("/", "\\")
        dof_tuned_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            dof_tuned_windows_ini,
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            dof_tuned_payload,
            benchmark=True,
            benchmark_preset="720p-ultra-no-tessellation-ssao1-dof1",
        ) == (high_proton, high_game)
        dof_tuned_ini.write_text(
            dof_tuned_ini.read_text().replace("DOFQuality = 1", "DOFQuality = 2")
        )
        try:
            MODULE.validated_tombraider_command(
                high_base,
                dof_tuned_payload,
                benchmark=True,
                benchmark_preset="720p-ultra-no-tessellation-ssao1-dof1",
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified DOF override was accepted")

        lod_tuned_ini = (
            high_base
            / "run/tombraider-benchmark-720p-ultra-no-tessellation-ssao1-dof1-lod3.ini"
        )
        lod_tuned_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1280\n"
            "FullscreenHeight = 720\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
            "SSAOMode = 1\n"
            "DOFQuality = 1\n"
            "LODScale = 3\n"
        )
        lod_tuned_ini.chmod(0o600)
        lod_tuned_windows_ini = "Z:" + str(lod_tuned_ini).replace("/", "\\")
        lod_tuned_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            lod_tuned_windows_ini,
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            lod_tuned_payload,
            benchmark=True,
            benchmark_preset="720p-ultra-no-tessellation-ssao1-dof1-lod3",
        ) == (high_proton, high_game)
        lod_tuned_ini.write_text(
            lod_tuned_ini.read_text().replace("LODScale = 3", "LODScale = 4")
        )
        try:
            MODULE.validated_tombraider_command(
                high_base,
                lod_tuned_payload,
                benchmark=True,
                benchmark_preset="720p-ultra-no-tessellation-ssao1-dof1-lod3",
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified LOD override was accepted")

        registry_lod_ini = (
            high_base
            / "run/tombraider-benchmark-1080p-ultra-no-tessellation-ssao1-dof1-lod3.ini"
        )
        registry_lod_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1920\n"
            "FullscreenHeight = 1080\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
            "SSAOMode = 1\n"
            "DOFQuality = 1\n"
            "LODScale = 3\n"
        )
        registry_lod_ini.chmod(0o600)
        registry_lod_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            "Z:" + str(registry_lod_ini).replace("/", "\\"),
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            registry_lod_payload,
            benchmark=True,
            benchmark_preset="1080p-ultra-no-tessellation-ssao1-dof1-lod3",
        ) == (high_proton, high_game)
        registry_lod_ini.write_text(
            registry_lod_ini.read_text().replace("LODScale = 3", "LODScale = 4")
        )
        try:
            MODULE.validated_tombraider_command(
                high_base,
                registry_lod_payload,
                benchmark=True,
                benchmark_preset=(
                    "1080p-ultra-no-tessellation-ssao1-dof1-lod3"
                ),
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified 1080p LOD override was accepted")

        shadow_ini = (
            high_base
            / "run/tombraider-benchmark-1080p-ultra-no-tessellation-ssao1-dof1-shadow1.ini"
        )
        shadow_ini.write_text(
            "QualityLevel = 3\n"
            "Fullscreen = 1\n"
            "ExclusiveFullscreen = 1\n"
            "VSyncMode = 0\n"
            "FullscreenWidth = 1920\n"
            "FullscreenHeight = 1080\n"
            "FullscreenRefreshRate = 60\n"
            "EnableMotionBlur = 0\n"
            "EnableTessellation = 0\n"
            "SSAOMode = 1\n"
            "DOFQuality = 1\n"
            "ShadowResolution = 1\n"
        )
        shadow_ini.chmod(0o600)
        shadow_payload = [
            "--",
            str(high_proton),
            "waitforexitandrun",
            str(high_game),
            "-nolauncher",
            "-benchmarkini",
            "Z:" + str(shadow_ini).replace("/", "\\"),
        ]
        assert MODULE.validated_tombraider_command(
            high_base,
            shadow_payload,
            benchmark=True,
            benchmark_preset=(
                "1080p-ultra-no-tessellation-ssao1-dof1-shadow1"
            ),
        ) == (high_proton, high_game)
        shadow_ini.write_text(
            shadow_ini.read_text().replace(
                "ShadowResolution = 1", "ShadowResolution = 2"
            )
        )
        try:
            MODULE.validated_tombraider_command(
                high_base,
                shadow_payload,
                benchmark=True,
                benchmark_preset=(
                    "1080p-ultra-no-tessellation-ssao1-dof1-shadow1"
                ),
            )
        except MODULE.DispatchError:
            pass
        else:
            raise AssertionError("modified shadow override was accepted")
    try:
        MODULE.validated_tombraider_command(
            tablet_base, benchmark_payload, benchmark=False
        )
    except MODULE.DispatchError:
        pass
    else:
        raise AssertionError("normal mode accepted benchmark arguments")
    with tempfile.TemporaryDirectory(prefix="proton-cmd-smoke.") as directory:
        fixture_base = Path(directory) / "steam-arm64"
        fixture_home = fixture_base / "native-home"
        fixture_home.mkdir(parents=True, mode=0o700)
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
        assert MODULE.proton_smoke_environment("fex-offline-compile") == {
            "WINEDEBUG": "-all"
        }
        assert MODULE.proton_smoke_environment(
            "fex-offline-compile", diagnostics=True
        )["WINEDEBUG"].endswith("+schannel")
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
        native_sdk = fixture_base / "client/linuxarm64"
        native_sdk.mkdir(parents=True)
        (native_sdk / "steamclient.so").write_bytes(b"fixture")
        (native_sdk / "steamclient.so").chmod(0o600)
        (fixture_home / ".steam").mkdir(mode=0o700)
        (fixture_home / ".steam/sdkarm64").symlink_to(native_sdk)
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
            "HOME": str(fixture_home),
            "TZ": "UTC0",
        }
        diagnostic_game_environment = MODULE.direct_game_environment(
            fixture_base, audio_runtime, True
        )
        dxvk_log_path = Path(diagnostic_game_environment["DXVK_LOG_PATH"])
        assert diagnostic_game_environment == {
            **audio_environment,
            "HOME": str(fixture_home),
            "TZ": "UTC0",
            "DXVK_LOG_LEVEL": "info",
            "DXVK_LOG_PATH": str(dxvk_log_path),
        }
        assert dxvk_log_path.parent == fixture_base / "logs"
        assert dxvk_log_path.name.startswith("dxvk-direct-")
        assert dxvk_log_path.is_dir() and not dxvk_log_path.is_symlink()
        assert stat.S_IMODE(dxvk_log_path.stat().st_mode) == 0o700
        assert dxvk_log_path.stat().st_uid == os.geteuid()
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
            "+timestamp,+pid,+tid,+process,+module,+loaddll,+seh,+vulkan,"
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
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_DIAGNOSTICS": "1"}, clear=False
        ):
            assert MODULE.direct_diagnostics_enabled()
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_DIAGNOSTICS": "0"}, clear=False
        ):
            assert not MODULE.direct_diagnostics_enabled()
        with mock.patch.dict(
            os.environ, {"STEAM_ARM64_DIRECT_DIAGNOSTICS": "invalid"}, clear=False
        ):
            try:
                MODULE.direct_diagnostics_enabled()
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("invalid direct diagnostics flag was accepted")
    assert MODULE.request_environment(
        {
            "environment": [
                "STEAM_COMPAT_APP_ID=203160",
                "LD_PRELOAD=unsafe",
                "TGCOMPAT_USERFAULTFD_ENOSYS=unsafe",
                "BVB_VULKAN_TRACE_FILE=unsafe",
                "STEAM_ARM64_VULKAN_TRACE_PRELOAD=unsafe",
                "STEAM_ARM64_VULKAN_TRACE_FILE=unsafe",
                "BVB_COMMAND_STREAM=shared",
                "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM=shared",
                "TOMB_RAIDER_BVB_COMMAND_STREAM=shared",
                "BVB_MAPPED_MEMORY=shared",
                "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY=shared",
                "TOMB_RAIDER_BVB_MAPPED_MEMORY=shared",
                "BVB_DESCRIPTOR_JOURNAL=shared",
                "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL=shared",
                "TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL=shared",
                "BVB_FIRST_REJECTION_DIAGNOSTIC=1",
                "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC=1",
                "TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC=1",
                "BVB_ICD_DIAGNOSTICS=1",
                "TOMB_RAIDER_BVB_ICD_DIAGNOSTICS=1",
                "VK_LOADER_DEBUG=all",
                "MANGOHUD=1",
                "MANGOHUD_CONFIGFILE=/unsafe",
                "DISABLE_MANGOHUD=0",
                "VK_INSTANCE_LAYERS=unsafe",
                "VK_LAYER_PATH=/unsafe",
                "STEAM_ARM64_DIRECT_NMS_MANGOHUD=1",
                "STEAM_ARM64_DIRECT_NMS_MANGOHUD_CONFIG=/unsafe",
                "STEAM_ARM64_DIRECT_NMS_XINPUT=1",
                "STEAMCLIENTTERMUX_NMS_XINPUT=1",
                "BVB_FRAME_PROFILE=1",
                "TOMB_RAIDER_BVB_FRAME_PROFILE=1",
                "SDL_JOYSTICK_HIDAPI=0",
                "STEAM_ARM64_HIDAPI=disabled",
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
    assert "environment.update(bvb_vulkan_environment())" in invocation_source
    assert "environment.update(nms_mangohud_environment(base, command_mode))" in invocation_source
    assert "environment.update(nms_xinput_environment(base, command_mode))" in invocation_source
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
    assert "direct_game_environment(base, runtime_root, diagnostics)" in invocation_source
    game_source = inspect.getsource(MODULE.run_tombraider)
    assert '"tombraider"' in game_source
    assert '"removable-library/steamapps/common/Tomb Raider"' in game_source
    assert "cpu_affinity=set(range(8))" in game_source
    assert "match_proton_cpu_topology=True" in game_source
    assert "minimum_cpu_affinity_count=(6 if require_full_startup_topology() else 0)" in game_source
    nms_source = inspect.getsource(MODULE.run_no_mans_sky)
    assert '"no-mans-sky"' in nms_source
    assert '"removable-library/steamapps/common/No Man\'s Sky/Binaries"' in nms_source
    assert "cpu_affinity=set(range(8))" in nms_source
    assert "match_proton_cpu_topology=True" in nms_source
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
