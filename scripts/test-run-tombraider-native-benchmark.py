#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "scripts" / "run-tombraider-native-benchmark.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("run_tombraider_benchmark", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_tool()
    assert module.parse_benchmark_result(
        b"MinFPS: 15.8\r\nMaxFPS: 29.8\r\nAverage FPS: 23.2\r\n"
    ) == {"minimum_fps": 15.8, "maximum_fps": 29.8, "average_fps": 23.2}
    quality = module.parse_benchmark_quality_settings(
        b"Quality settings:\r\n\r\n"
        b"Fullscreen = 1\r\nExclusiveFullscreen = 1\r\nVSyncMode = 0\r\n"
        b"FullscreenWidth = 1280\r\nFullscreenHeight = 720\r\n"
        b"FullscreenRefreshRate = 60\r\nEnableMotionBlur = 0\r\n"
        b"TextureQuality = 1\r\n"
    )
    module.validate_benchmark_quality_settings(
        quality, module.GAME_PROFILES["720p-high"]
    )
    assert module.parse_benchmark_result(
        "Minimum FPS = 19.0\nMaximum FPS = 36.0\nAvgFPS = 25.7\n".encode("utf-16")
    ) == {"minimum_fps": 19.0, "maximum_fps": 36.0, "average_fps": 25.7}
    try:
        module.parse_benchmark_result(b"MinFPS: 1\nMaxFPS: 2\n")
    except RuntimeError as error:
        assert "average_fps" in str(error)
    else:
        raise AssertionError("incomplete benchmark result was accepted")
    patched_sha = "4" * 64
    assert module.parse_topology_fix_status(
        f"Tomb Raider CPU topology fix: enabled; SHA-256 {patched_sha}\n"
    ) == patched_sha
    for invalid_topology_status in (
        f"Tomb Raider CPU topology fix: disabled; SHA-256 {'f' * 64}\n",
        "Tomb Raider CPU topology fix: enabled\n",
        f"noise\nTomb Raider CPU topology fix: enabled; SHA-256 {patched_sha}\n",
    ):
        try:
            module.parse_topology_fix_status(invalid_topology_status)
        except RuntimeError as error:
            assert "not enabled" in str(error)
        else:
            raise AssertionError("invalid topology-fix status was accepted")
    assert module.parse_cef_hold_log(
        "Steam CEF experimental hold: active; 20,21,30\n"
        "Steam CEF experimental hold: game exited\n"
        "Steam CEF experimental hold: resumed 20,21,30\n"
    ) == [20, 21, 30]
    for invalid_cef_log in (
        "Steam CEF experimental hold: active; 20,21\n",
        "Steam CEF experimental hold: active; 20,21\n"
        "Steam CEF experimental hold: game exited\n"
        "Steam CEF experimental hold: resumed 20\n",
        "Steam CEF experimental hold: active; 21,20\n"
        "Steam CEF experimental hold: game exited\n"
        "Steam CEF experimental hold: resumed 21,20\n",
        "Steam CEF experimental hold: active; 20,21\n"
        "Steam CEF experimental hold: game exited\n"
        "Steam CEF experimental hold: resumed 20,21\n"
        "hold-tombraider-steam-cef: unexpected error\n",
    ):
        try:
            module.parse_cef_hold_log(invalid_cef_log)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid Steam CEF hold log was accepted")
    assert module.parse_x11_isolation_log(
        "Termux X11 experimental isolation: active; pid=10; cpus=0,1; tids=10,11\n"
        "Termux X11 experimental isolation: game exited\n"
        "Termux X11 experimental isolation: restored; tids=10,11,12\n"
    ) == {
        "pid": 10,
        "cpus": [0, 1],
        "active_tids": [10, 11],
        "restored_tids": [10, 11, 12],
    }
    for invalid_x11_log in (
        "Termux X11 experimental isolation: active; pid=10; cpus=0,1; tids=10,11\n",
        "Termux X11 experimental isolation: active; pid=10; cpus=1,0; tids=10,11\n"
        "Termux X11 experimental isolation: game exited\n"
        "Termux X11 experimental isolation: restored; tids=10,11\n",
        "Termux X11 experimental isolation: active; pid=10; cpus=0; tids=11,10\n"
        "Termux X11 experimental isolation: game exited\n"
        "Termux X11 experimental isolation: restored; tids=10,11\n",
        "Termux X11 experimental isolation: active; pid=10; cpus=0; tids=10,11\n"
        "Termux X11 experimental isolation: game exited\n"
        "Termux X11 experimental isolation: restored; tids=10\n",
        "Termux X11 experimental isolation: active; pid=10; cpus=0; tids=10,11\n"
        "Termux X11 experimental isolation: game exited\n"
        "Termux X11 experimental isolation: restored; tids=10,11\n"
        "unexpected noise\n",
    ):
        try:
            module.parse_x11_isolation_log(invalid_x11_log)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid Termux X11 isolation log was accepted")
    assert module.parse_steam_service_isolation_log(
        "Steam service CPU isolation: active; steam_pid=10; tid=20; "
        "cpus=0; original_cpus=0-3\n"
        "Steam service CPU isolation: game exited\n"
        "Steam service CPU isolation: restored; steam_pid=10; tid=20; cpus=0-3\n"
    ) == {
        "steam_pid": 10,
        "tid": 20,
        "isolated_cpus": "0",
        "original_cpus": "0-3",
        "restored_cpus": "0-3",
    }
    for invalid_service_log in (
        "Steam service CPU isolation: active; steam_pid=10; tid=20; "
        "cpus=0; original_cpus=0-3\n",
        "Steam service CPU isolation: active; steam_pid=10; tid=20; "
        "cpus=0; original_cpus=0-3\n"
        "Steam service CPU isolation: game exited\n"
        "Steam service CPU isolation: restored; steam_pid=10; tid=21; cpus=0-3\n",
        "Steam service CPU isolation: active; steam_pid=10; tid=20; "
        "cpus=0; original_cpus=0-3\n"
        "Steam service CPU isolation: game exited\n"
        "Steam service CPU isolation: restored; steam_pid=10; tid=20; cpus=0-2\n",
    ):
        try:
            module.parse_steam_service_isolation_log(invalid_service_log)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid Steam service isolation log was accepted")
    assert module.parse_recorded_passes("2,4,6") == (2, 4, 6)
    for invalid_passes in ("", "0", "2,2", "4,2", "one,2"):
        try:
            module.parse_recorded_passes(invalid_passes)
        except module.argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError("invalid recorded pass list was accepted")
    assert module.parse_cpu_set("0,1") == (0, 1)
    for invalid_cpus in ("", "-1", "8", "1,0", "0,0", "zero"):
        try:
            module.parse_cpu_set(invalid_cpus)
        except module.argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError("invalid benchmark X11 CPU set was accepted")

    xrandr = (
        "Screen 0: minimum 320 x 200, current 2800 x 1752, maximum 8192 x 8192\n"
        "   2800x1752     119.92*  60.00\n"
    )
    assert module.parse_xrandr_geometry(xrandr) == "2800x1752"
    assert module.parse_xrandr_refresh(xrandr) == [119.92]
    checker = Path("/base/compat-bin/configure-tombraider-performance.py")
    assert module.python_tool_command(checker, "--check") == [
        Path(module.sys.executable),
        checker,
        "--check",
    ]
    normal = module.build_parser().parse_args(["--game-profile", "720p-normal"])
    assert normal.game_profile == "720p-normal"
    assert module.GAME_PROFILES[normal.game_profile] == {
        "resolution": "1280x720",
        "graphics": "Normal",
        "registry_profile": "720p-normal",
        "benchmark_preset": "registry",
    }
    normal_1080p = module.build_parser().parse_args(
        ["--game-profile", "1080p-normal"]
    )
    assert normal_1080p.game_profile == "1080p-normal"
    assert module.GAME_PROFILES[normal_1080p.game_profile] == {
        "resolution": "1920x1080",
        "graphics": "Normal",
        "registry_profile": "1080p-normal",
        "benchmark_preset": "registry",
    }
    high = module.build_parser().parse_args(["--game-profile", "720p-high"])
    assert module.GAME_PROFILES[high.game_profile] == {
        "resolution": "1280x720",
        "graphics": "High",
        "registry_profile": "720p-normal",
        "benchmark_preset": "720p-high",
        "quality_level": 2,
    }
    high_1080p = module.build_parser().parse_args(
        ["--game-profile", "1080p-high"]
    )
    assert module.GAME_PROFILES[high_1080p.game_profile] == {
        "resolution": "1920x1080",
        "graphics": "High",
        "registry_profile": "1080p-normal",
        "benchmark_preset": "1080p-high",
        "quality_level": 2,
    }
    assert module.GAME_PROFILES["720p-ultra"]["quality_level"] == 3
    assert module.GAME_PROFILES["1080p-ultra"]["graphics"] == "Ultra"
    ultra_no_tessellation = module.GAME_PROFILES[
        "720p-ultra-no-tessellation"
    ]
    assert ultra_no_tessellation["benchmark_overrides"] == {
        "EnableTessellation": 0
    }
    assert module.quality_benchmark_ini(ultra_no_tessellation).endswith(
        "EnableMotionBlur = 0\nEnableTessellation = 0\n"
    )
    custom_quality = {**quality, "EnableTessellation": 0}
    module.validate_benchmark_quality_settings(
        custom_quality, ultra_no_tessellation
    )
    try:
        module.validate_benchmark_quality_settings(
            {**custom_quality, "EnableTessellation": 1},
            ultra_no_tessellation,
        )
    except RuntimeError as error:
        assert "EnableTessellation" in str(error)
    else:
        raise AssertionError("enabled tessellation passed the custom profile")
    tuned_ultra = module.GAME_PROFILES[
        "720p-ultra-no-tessellation-ssao1"
    ]
    assert tuned_ultra["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
    }
    assert module.quality_benchmark_ini(tuned_ultra).endswith(
        "EnableTessellation = 0\nSSAOMode = 1\n"
    )
    module.validate_benchmark_quality_settings(
        {**custom_quality, "SSAOMode": 1}, tuned_ultra
    )
    dof_tuned_ultra = module.GAME_PROFILES[
        "720p-ultra-no-tessellation-ssao1-dof1"
    ]
    assert dof_tuned_ultra["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
        "DOFQuality": 1,
    }
    assert module.quality_benchmark_ini(dof_tuned_ultra).endswith(
        "EnableTessellation = 0\nSSAOMode = 1\nDOFQuality = 1\n"
    )
    dof_tuned_quality = {
        **custom_quality,
        "SSAOMode": 1,
        "DOFQuality": 1,
    }
    module.validate_benchmark_quality_settings(
        dof_tuned_quality, dof_tuned_ultra
    )
    try:
        module.validate_benchmark_quality_settings(
            {**dof_tuned_quality, "DOFQuality": 2}, dof_tuned_ultra
        )
    except RuntimeError as error:
        assert "DOFQuality" in str(error)
    else:
        raise AssertionError("modified DOF quality passed the custom profile")
    lod_tuned_ultra = module.GAME_PROFILES[
        "720p-ultra-no-tessellation-ssao1-dof1-lod3"
    ]
    assert lod_tuned_ultra["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
        "DOFQuality": 1,
        "LODScale": 3,
    }
    assert module.quality_benchmark_ini(lod_tuned_ultra).endswith(
        "EnableTessellation = 0\nSSAOMode = 1\nDOFQuality = 1\nLODScale = 3\n"
    )
    lod_tuned_quality = {**dof_tuned_quality, "LODScale": 3}
    module.validate_benchmark_quality_settings(
        lod_tuned_quality, lod_tuned_ultra
    )
    try:
        module.validate_benchmark_quality_settings(
            {**lod_tuned_quality, "LODScale": 4}, lod_tuned_ultra
        )
    except RuntimeError as error:
        assert "LODScale" in str(error)
    else:
        raise AssertionError("modified LOD scale passed the custom profile")
    lod_tuned_1080p = module.GAME_PROFILES[
        "1080p-ultra-no-tessellation-ssao1-dof1-lod3"
    ]
    assert lod_tuned_1080p["registry_profile"] == "1080p-normal"
    assert lod_tuned_1080p["benchmark_preset"] == (
        "1080p-ultra-no-tessellation-ssao1-dof1-lod3"
    )
    assert lod_tuned_1080p["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
        "DOFQuality": 1,
        "LODScale": 3,
    }
    module.validate_benchmark_quality_settings(
        {**lod_tuned_quality, "FullscreenWidth": 1920, "FullscreenHeight": 1080},
        lod_tuned_1080p,
    )
    assert module.quality_benchmark_ini(lod_tuned_1080p) == (
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
    shadow_tuned_1080p = module.GAME_PROFILES[
        "1080p-ultra-no-tessellation-ssao1-dof1-shadow1"
    ]
    assert shadow_tuned_1080p["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
        "DOFQuality": 1,
        "ShadowResolution": 1,
    }
    assert module.quality_benchmark_ini(shadow_tuned_1080p).endswith(
        "DOFQuality = 1\nShadowResolution = 1\n"
    )
    module.validate_benchmark_quality_settings(
        {
            **dof_tuned_quality,
            "FullscreenWidth": 1920,
            "FullscreenHeight": 1080,
            "ShadowResolution": 1,
        },
        shadow_tuned_1080p,
    )
    shadow0_tuned_1080p = module.GAME_PROFILES[
        "1080p-ultra-no-tessellation-ssao1-dof1-shadow0"
    ]
    assert shadow0_tuned_1080p["benchmark_overrides"] == {
        "EnableTessellation": 0,
        "SSAOMode": 1,
        "DOFQuality": 1,
        "ShadowResolution": 0,
    }
    assert module.quality_benchmark_ini(shadow0_tuned_1080p).endswith(
        "DOFQuality = 1\nShadowResolution = 0\n"
    )
    module.validate_benchmark_quality_settings(
        {
            **dof_tuned_quality,
            "FullscreenWidth": 1920,
            "FullscreenHeight": 1080,
            "ShadowResolution": 0,
        },
        shadow0_tuned_1080p,
    )
    assert module.GAME_PROFILES["720p-ultimate"]["quality_level"] == 4
    assert module.GAME_PROFILES["1080p-ultimate"]["graphics"] == "Ultimate"
    assert module.quality_benchmark_ini(
        module.GAME_PROFILES["1080p-ultimate"]
    ).startswith("QualityLevel = 4\n")
    assert "TOMB_RAIDER_PROFILE_CHECKER" in TOOL.read_text(encoding="utf-8")
    fixed = module.build_parser().parse_args(
        ["--profile", "proton", "--start-temperature-ceiling-c", "40"]
    )
    assert fixed.profile == "proton"
    assert fixed.start_temperature_ceiling_c == 40.0
    direct = module.build_parser().parse_args(["--backend", "direct"])
    assert direct.backend == "direct"
    assert direct.launcher is None
    assert direct.raknet_nice is None
    assert direct.raknet_exclusive_recorded_passes == ()
    assert direct.startup_topology == "available"
    assert not direct.hold_steam_cef
    assert direct.steam_cef_hold_recorded_passes == ()
    assert not direct.isolate_x11
    assert direct.x11_isolation_recorded_passes == ()
    assert direct.x11_isolation_cpus == (0,)
    assert not direct.isolate_steam_service
    assert direct.steam_service_isolation_recorded_passes == ()
    direct_cef_hold = module.build_parser().parse_args(
        ["--backend", "direct", "--hold-steam-cef"]
    )
    assert direct_cef_hold.hold_steam_cef
    direct_cef_pairs = module.build_parser().parse_args(
        ["--backend", "direct", "--steam-cef-hold-recorded-passes", "2,4,6"]
    )
    assert direct_cef_pairs.steam_cef_hold_recorded_passes == (2, 4, 6)
    direct_x11_pairs = module.build_parser().parse_args(
        [
            "--backend",
            "direct",
            "--x11-isolation-recorded-passes",
            "2,4,6",
            "--x11-isolation-cpus",
            "0,1",
        ]
    )
    assert direct_x11_pairs.x11_isolation_recorded_passes == (2, 4, 6)
    assert direct_x11_pairs.x11_isolation_cpus == (0, 1)
    direct_priority = module.build_parser().parse_args(
        ["--backend", "direct", "--raknet-nice", "19"]
    )
    assert direct_priority.raknet_nice == 19
    direct_raknet_exclusive = module.build_parser().parse_args(
        ["--backend", "direct", "--raknet-exclusive-recorded-passes", "2,4,6"]
    )
    assert direct_raknet_exclusive.raknet_exclusive_recorded_passes == (2, 4, 6)
    direct_service_pairs = module.build_parser().parse_args(
        [
            "--backend",
            "direct",
            "--steam-service-isolation-recorded-passes",
            "2,4,6",
        ]
    )
    assert direct_service_pairs.steam_service_isolation_recorded_passes == (2, 4, 6)
    direct_full = module.build_parser().parse_args(
        ["--backend", "direct", "--startup-topology", "full"]
    )
    assert direct_full.startup_topology == "full"
    assert module.affinity_log_is_ready(
        "Tomb Raider PID 1: observing inherited startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1, CPUs 1-7\n",
        "direct",
    )
    assert module.affinity_log_is_ready(
        "Tomb Raider PID 1: holding startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1, CPUs 1-7\n",
        "direct",
    )
    assert not module.affinity_log_is_ready(
        "Tomb Raider performance state: ready; PID 1\n", "direct"
    )
    assert not module.affinity_log_is_ready(
        "Tomb Raider PID 1: observing inherited startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1, CPUs 1-7\n",
        "direct",
        "2-7",
    )
    assert not module.affinity_log_is_ready(
        "Tomb Raider PID 1: observing inherited startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1, CPUs 2-7\n",
        "direct",
        "1-7",
    )
    assert module.affinity_log_is_ready(
        "Tomb Raider PID 1: observing inherited startup topology on CPUs 1-7\n"
        "Tomb Raider PID 1: startup topology ready; logical=7, cores=7, "
        "physical=7; affinity guard attached\n"
        "Tomb Raider performance state: ready; PID 1, CPUs 2-7, RakNet CPU 1\n",
        "direct",
        "2-7",
    )
    assert module.affinity_log_is_ready(
        "Tomb Raider performance state: ready; PID 1\n", "proot"
    )

    condition_runs = [
        {
            "kind": "recorded",
            "x11_isolation": False,
            "metrics": {
                "minimum_fps": 10.0,
                "maximum_fps": 30.0,
                "average_fps": 20.0,
            },
        },
        {
            "kind": "recorded",
            "x11_isolation": True,
            "metrics": {
                "minimum_fps": 12.0,
                "maximum_fps": 32.0,
                "average_fps": 22.0,
            },
        },
    ]
    assert module.aggregate_x11_isolation_conditions(condition_runs) == {
        "control": {
            "minimum_fps": {"mean": 10.0, "median": 10.0, "values": [10.0]},
            "maximum_fps": {"mean": 30.0, "median": 30.0, "values": [30.0]},
            "average_fps": {"mean": 20.0, "median": 20.0, "values": [20.0]},
        },
        "x11_isolation": {
            "minimum_fps": {"mean": 12.0, "median": 12.0, "values": [12.0]},
            "maximum_fps": {"mean": 32.0, "median": 32.0, "values": [32.0]},
            "average_fps": {"mean": 22.0, "median": 22.0, "values": [22.0]},
        },
    }
    raknet_runs = [
        {**condition_runs[0], "raknet_exclusive": False},
        {**condition_runs[1], "raknet_exclusive": True},
    ]
    assert module.aggregate_raknet_exclusive_conditions(raknet_runs) == {
        "control": {
            "minimum_fps": {"mean": 10.0, "median": 10.0, "values": [10.0]},
            "maximum_fps": {"mean": 30.0, "median": 30.0, "values": [30.0]},
            "average_fps": {"mean": 20.0, "median": 20.0, "values": [20.0]},
        },
        "raknet_exclusive": {
            "minimum_fps": {"mean": 12.0, "median": 12.0, "values": [12.0]},
            "maximum_fps": {"mean": 32.0, "median": 32.0, "values": [32.0]},
            "average_fps": {"mean": 22.0, "median": 22.0, "values": [22.0]},
        },
    }
    service_runs = [
        {**condition_runs[0], "steam_service_isolation": False},
        {**condition_runs[1], "steam_service_isolation": True},
    ]
    assert module.aggregate_steam_service_isolation_conditions(service_runs) == {
        "control": {
            "minimum_fps": {"mean": 10.0, "median": 10.0, "values": [10.0]},
            "maximum_fps": {"mean": 30.0, "median": 30.0, "values": [30.0]},
            "average_fps": {"mean": 20.0, "median": 20.0, "values": [20.0]},
        },
        "steam_service_isolation": {
            "minimum_fps": {"mean": 12.0, "median": 12.0, "values": [12.0]},
            "maximum_fps": {"mean": 32.0, "median": 32.0, "values": [32.0]},
            "average_fps": {"mean": 22.0, "median": 22.0, "values": [22.0]},
        },
    }

    def snapshot(cpu_policy, gpu_policy, gpu_level, temperature):
        return {
            "cpu": [
                {
                    "cpu": 7,
                    "policy_max_khz": cpu_policy,
                    "hardware_max_khz": 2_995_200,
                }
            ],
            "gpu": {
                "policy_max_hz": gpu_policy,
                "hardware_max_hz": 818_000_000,
                "thermal_pwrlevel": gpu_level,
            },
            "thermal": [
                {"zone": "cpu-1-7", "millidegrees_c": temperature}
            ],
        }

    hot = snapshot(1_843_200, 492_000_000, 6, 73_900)
    ready = snapshot(2_995_200, 818_000_000, 0, 51_000)
    issues = module.benchmark_readiness_issues(hot, 52_300)
    assert any("CPU policy is throttled" in issue for issue in issues)
    assert any("GPU policy is throttled" in issue for issue in issues)
    assert any("maximum temperature" in issue for issue in issues)
    assert module.benchmark_readiness_issues(ready, 52_300) == []
    samples = iter((hot, ready, ready))
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    settled, elapsed = module.wait_for_benchmark_ready(
        lambda: next(samples),
        52_300,
        60,
        10,
        2,
        monotonic=lambda: clock[0],
        sleeper=sleep,
    )
    assert settled is ready
    assert elapsed == 20.0

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        cgroup = root / "cgroup"
        cgroup.write_text("3:cpuset:/top-app\n2:cpu:/top-app\n")
        module.require_top_app(cgroup)
        cgroup.write_text("3:cpuset:/moderate\n2:cpu:/background\n")
        try:
            module.require_top_app(cgroup)
        except RuntimeError as error:
            assert "not in Android top-app" in str(error)
        else:
            raise AssertionError("background benchmark runner was accepted")

        proc = root / "proc"
        (proc / "10").mkdir(parents=True)
        (proc / "11").mkdir()
        executable = Path("/base/client/steamrtarm64/steam")
        (proc / "10/cmdline").write_bytes(
            b"/glibc/ld-linux-aarch64.so.1\0--argv0\0"
            + str(executable).encode()
            + b"\0"
            + str(executable).encode()
            + b"\0"
        )
        (proc / "11/cmdline").write_bytes(
            b"/base/client/steamrtarm64/steamwebhelper\0"
        )
        assert module.find_exact_processes(proc, executable) == [10]

        results = root / "results"
        results.mkdir()
        old = results / "benchmarkresults-old.txt"
        old.write_text("old")
        before = module.file_state(results.glob(module.RESULT_GLOB))
        new = results / "benchmarkresults-new.txt"
        new.write_text("new")
        # Removable-storage metadata for an existing name can change between
        # scans. Only a previously absent timestamped result is a new pass.
        old.write_text("old rewritten")
        assert module.new_regular_files(results, module.RESULT_GLOB, before) == [new]

        launch_output = root / "launch.log"
        holder_output = root / "holder.log"
        elapsed, held_pids, launch_return_code = module.run_logged_with_cef_holder(
            [sys.executable, "-c", "print('game completed')"],
            os.environ,
            launch_output,
            [
                sys.executable,
                "-c",
                "print('Steam CEF experimental hold: active; 20,21'); "
                "print('Steam CEF experimental hold: game exited'); "
                "print('Steam CEF experimental hold: resumed 20,21')",
            ],
            holder_output,
        )
        assert elapsed >= 0
        assert held_pids == [20, 21]
        assert launch_return_code == 0
        assert launch_output.read_text() == "game completed\n"

        nonzero_output = root / "nonzero-launch.log"
        elapsed, launch_return_code = module.run_logged_outcome(
            [sys.executable, "-c", "raise SystemExit(1)"],
            os.environ,
            nonzero_output,
        )
        assert elapsed >= 0
        assert launch_return_code == 1

        service_output = root / "accepted-steam-service-isolator.log"
        elapsed, service_evidence, launch_return_code = (
            module.run_logged_with_steam_service_isolator(
                [sys.executable, "-c", "raise SystemExit(1)"],
                os.environ,
                root / "accepted-steam-service-nonzero-launch.log",
                [
                    sys.executable,
                    "-c",
                    "print('Steam service CPU isolation: active; steam_pid=10; "
                    "tid=20; cpus=0; original_cpus=0-3'); "
                    "print('Steam service CPU isolation: game exited'); "
                    "print('Steam service CPU isolation: restored; steam_pid=10; "
                    "tid=20; cpus=0-3')",
                ],
                service_output,
                allow_launch_failure=True,
            )
        )
        assert elapsed >= 0
        assert service_evidence == {
            "steam_pid": 10,
            "tid": 20,
            "isolated_cpus": "0",
            "original_cpus": "0-3",
            "restored_cpus": "0-3",
        }
        assert launch_return_code == 1

        accepted_output = root / "accepted-holder.log"
        elapsed, held_pids, launch_return_code = module.run_logged_with_cef_holder(
            [sys.executable, "-c", "raise SystemExit(1)"],
            os.environ,
            root / "accepted-nonzero-launch.log",
            [
                sys.executable,
                "-c",
                "print('Steam CEF experimental hold: active; 20,21'); "
                "print('Steam CEF experimental hold: game exited'); "
                "print('Steam CEF experimental hold: resumed 20,21')",
            ],
            accepted_output,
            allow_launch_failure=True,
        )
        assert elapsed >= 0
        assert held_pids == [20, 21]
        assert launch_return_code == 1

        isolated_output = root / "accepted-isolator.log"
        elapsed, isolation_evidence, launch_return_code = (
            module.run_logged_with_x11_isolator(
                [sys.executable, "-c", "raise SystemExit(1)"],
                os.environ,
                root / "accepted-isolator-nonzero-launch.log",
                [
                    sys.executable,
                    "-c",
                    "print('Termux X11 experimental isolation: active; "
                    "pid=10; cpus=0,1; tids=10,11'); "
                    "print('Termux X11 experimental isolation: game exited'); "
                    "print('Termux X11 experimental isolation: restored; "
                    "tids=10,11')",
                ],
                isolated_output,
                allow_launch_failure=True,
            )
        )
        assert elapsed >= 0
        assert isolation_evidence == {
            "pid": 10,
            "cpus": [0, 1],
            "active_tids": [10, 11],
            "restored_tids": [10, 11],
        }
        assert launch_return_code == 1

        direct_base = root / "direct-base"
        direct_logs = direct_base / "logs"
        direct_logs.mkdir(parents=True)
        server_log = direct_logs / "tombraider-direct-tombraider-benchmark-lean-20260818T010203Z.log"
        launcher_log = direct_logs / "tombraider-direct-launcher-tombraider-benchmark-lean-20260818T010203Z.log"
        server_log.write_text(
            "READY=/protected/dispatch.sock\n"
            + module.PULSE_MAINLOOP_ABORT
            + "\nDISPATCH_STATUS=1 TRACER_PID=0\n"
        )
        launcher_log.write_text("launcher completed\n")
        direct_launch = root / "direct-launch.log"
        direct_launch.write_text(
            "Tomb Raider direct dispatch completed: mode=tombraider-benchmark "
            "child_preload=lean launcher=0 server=1 "
            f"server_log={server_log} launcher_log={launcher_log}\n"
        )
        evidence = module.validate_post_result_pulse_abort(
            direct_launch, 1, direct_base, proc
        )
        assert evidence["reason"] == "post-result-pulseaudio-mainloop-abort"
        assert evidence["return_code"] == 1
        assert evidence["server_log"] == str(server_log)
        assert len(evidence["server_log_sha256"]) == 64

        server_log.write_text("DISPATCH_STATUS=1 TRACER_PID=0\n")
        try:
            module.validate_post_result_pulse_abort(direct_launch, 1, direct_base, proc)
        except RuntimeError as error:
            assert "lacks the exact PulseAudio" in str(error)
        else:
            raise AssertionError("missing PulseAudio assertion was accepted")
        server_log.write_text(
            module.PULSE_MAINLOOP_ABORT + "\nDISPATCH_STATUS=1 TRACER_PID=0\n"
        )
        (proc / "12").mkdir()
        (proc / "12/cmdline").write_bytes(b"Z:\\\\games\\\\TombRaider.exe\0")
        try:
            module.validate_post_result_pulse_abort(direct_launch, 1, direct_base, proc)
        except RuntimeError as error:
            assert "left Tomb Raider active" in str(error)
        else:
            raise AssertionError("live Tomb Raider process was accepted")
        (proc / "12/cmdline").unlink()
        (proc / "12").rmdir()
        try:
            module.validate_post_result_pulse_abort(direct_launch, 2, direct_base, proc)
        except RuntimeError as error:
            assert "status 1" in str(error)
        else:
            raise AssertionError("unexpected direct return code was accepted")

        rejected_output = root / "rejected-holder.log"
        try:
            module.run_logged_with_cef_holder(
                [sys.executable, "-c", "pass"],
                os.environ,
                root / "rejected-launch.log",
                [sys.executable, "-c", "raise SystemExit(2)"],
                rejected_output,
            )
        except RuntimeError as error:
            assert "holder exited 2" in str(error)
        else:
            raise AssertionError("nonzero Steam CEF holder was accepted")

    runs = [
        {
            "kind": "warmup",
            "metrics": {"minimum_fps": 1.0, "maximum_fps": 2.0, "average_fps": 1.5},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 10.0, "maximum_fps": 30.0, "average_fps": 20.0},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 12.0, "maximum_fps": 32.0, "average_fps": 22.0},
        },
        {
            "kind": "recorded",
            "metrics": {"minimum_fps": 14.0, "maximum_fps": 34.0, "average_fps": 24.0},
        },
    ]
    aggregate = module.aggregate_results(runs)
    assert aggregate["average_fps"] == {
        "mean": 22.0,
        "median": 22.0,
        "values": [20.0, 22.0, 24.0],
    }
    paired_runs = [
        {**run, "steam_cef_hold": index % 2 == 1}
        for index, run in enumerate(runs[1:] + runs[1:])
    ]
    paired = module.aggregate_cef_hold_conditions(paired_runs)
    assert paired["control"]["average_fps"]["values"] == [20.0, 24.0, 22.0]
    assert paired["steam_cef_hold"]["average_fps"]["values"] == [22.0, 20.0, 24.0]
    series = {"status": "initializing", "runs": []}
    active_pass = {
        "kind": "recorded",
        "number": 2,
        "label": "recorded-2",
        "game_cpus": "1-7",
    }
    module.set_series_phase(series, "cooldown", active_pass)
    assert series["phase"] == "cooldown"
    assert series["phase_updated_at"].endswith("+00:00")
    assert series["active_pass"] == {
        **active_pass,
        "phase": "cooldown",
        "updated_at": series["phase_updated_at"],
    }
    module.set_series_phase(series, "launching_or_running", series["active_pass"])
    assert series["active_pass"]["phase"] == "launching_or_running"
    try:
        module.set_series_phase(series, "guessed_boundary", active_pass)
    except ValueError as error:
        assert "unknown benchmark series phase" in str(error)
    else:
        raise AssertionError("unknown benchmark phase was accepted")
    failed = {**series, "status": "running"}
    module.mark_series_failed(failed, RuntimeError("controlled failure"))
    assert failed["status"] == "failed"
    assert failed["phase"] == "failed"
    assert failed["active_pass"]["kind"] == "recorded"
    assert failed["active_pass"]["number"] == 2
    assert failed["active_pass"]["phase"] == "failed"
    assert failed["failure"] == {
        "type": "RuntimeError",
        "message": "controlled failure",
    }
    assert failed["finished_at"].endswith("+00:00")
    print("native Tomb Raider benchmark runner tests: PASS")


if __name__ == "__main__":
    main()
