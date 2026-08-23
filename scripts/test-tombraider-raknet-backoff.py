#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "scripts/pressure-vessel-direct-dispatch.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
LEAN_WRAPPER = ROOT / "scripts/start-tombraider-direct-lean.sh"
DIRECT_BENCHMARK_WRAPPER = ROOT / "scripts/start-tombraider-direct-benchmark.sh"
GAME_WRAPPER = ROOT / "scripts/start-tombraider-direct-raknet-backoff.sh"
BENCHMARK_WRAPPER = (
    ROOT / "scripts/start-tombraider-direct-raknet-backoff-benchmark.sh"
)
THERMAL_WRAPPER = (
    ROOT / "scripts/test-tomb-raider-direct-raknet-backoff-40c-ceiling.sh"
)
SPEC = importlib.util.spec_from_file_location("pv_direct_dispatch", DISPATCHER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="raknet-backoff.") as directory:
        root = Path(directory)
        base = root / "base"
        shim = base / "compat-bin/libtgcompat-raknet-recv.so"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(
            b"ELF-fixture\0Raknet-RecvFrom\0"
            b"TGCOMPAT_RAKNET_RECV_SLEEP_US\0sched_yield\0"
        )
        shim.chmod(0o700)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US", None)
            assert MODULE.validated_raknet_recv_backoff(base, "tombraider") is None
            os.environ["STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US"] = "1000"
            selected = MODULE.validated_raknet_recv_backoff(
                base, "tombraider-benchmark"
            )
            assert selected == (
                shim,
                {"TGCOMPAT_RAKNET_RECV_SLEEP_US": "1000"},
            )
            try:
                MODULE.validated_raknet_recv_backoff(base, "runtime-true")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("non-game RakNet backoff was accepted")
            os.environ["STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US"] = "1"
            try:
                MODULE.validated_raknet_recv_backoff(base, "tombraider")
            except MODULE.DispatchError:
                pass
            else:
                raise AssertionError("unvalidated RakNet sleep interval was accepted")

        sanitized = MODULE.request_environment(
            {
                "environment": [
                    "TGCOMPAT_RAKNET_RECV_SLEEP_US=smuggled",
                    "STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US=smuggled",
                    "TOMB_RAIDER_RAKNET_RECV_SLEEP_US=smuggled",
                    "PRESERVED=value",
                ]
            }
        )
        assert sanitized == {"PRESERVED": "value"}

        capture = root / "capture"
        fake_launcher = root / "launcher"
        executable(
            fake_launcher,
            "#!/bin/bash\n"
            "printf '%s\\n' \"${STEAM_ARM64_BVB_VULKAN-}\" "
            "\"${TOMB_RAIDER_RAKNET_RECV_SLEEP_US-}\" \"$*\" >\"$CAPTURE\"\n",
        )
        for wrapper in (LEAN_WRAPPER, DIRECT_BENCHMARK_WRAPPER):
            wrapper_env = {
                **os.environ,
                "TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER": str(fake_launcher),
                "CAPTURE": str(capture),
            }
            wrapper_env.pop("TOMB_RAIDER_RAKNET_RECV_SLEEP_US", None)
            promoted = subprocess.run(
                ["bash", str(wrapper), "default"],
                env=wrapper_env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert promoted.returncode == 0, promoted.stderr
            assert capture.read_text(encoding="utf-8").splitlines() == [
                "",
                "1000",
                "default",
            ]
            wrapper_env["TOMB_RAIDER_RAKNET_RECV_SLEEP_US"] = "0"
            control = subprocess.run(
                ["bash", str(wrapper), "control"],
                env=wrapper_env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert control.returncode == 0, control.stderr
            assert capture.read_text(encoding="utf-8").splitlines() == [
                "",
                "0",
                "control",
            ]
        for wrapper in (GAME_WRAPPER, BENCHMARK_WRAPPER):
            result = subprocess.run(
                ["bash", str(wrapper), "fixture"],
                env={
                    **os.environ,
                    "TOMB_RAIDER_DIRECT_LAUNCHER_WRAPPER": str(fake_launcher),
                    "CAPTURE": str(capture),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
            assert capture.read_text(encoding="utf-8").splitlines() == [
                "0",
                "1000",
                "fixture",
            ]

        fake_runner = root / "runner"
        executable(
            fake_runner,
            "#!/bin/bash\nprintf '%s\\n' \"$@\" >\"$CAPTURE\"\n",
        )
        thermal = subprocess.run(
            ["bash", str(THERMAL_WRAPPER), "--runs", "1"],
            env={
                **os.environ,
                "TOMB_RAIDER_BENCHMARK_COMMAND": str(fake_runner),
                "TOMB_RAIDER_RAKNET_BACKOFF_BENCHMARK_LAUNCHER": str(
                    fake_launcher
                ),
                "CAPTURE": str(capture),
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert thermal.returncode == 0, thermal.stderr
        assert capture.read_text(encoding="utf-8").splitlines() == [
            "--backend",
            "direct",
            "--profile",
            "safe",
            "--startup-topology",
            "full",
            "--launcher",
            str(fake_launcher),
            "--start-temperature-ceiling-c",
            "40",
            "--runs",
            "1",
        ]

    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    assert "STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US" in launcher_source
    assert launcher_source.count("-u TGCOMPAT_RAKNET_RECV_SLEEP_US") >= 2
    assert "raknet_recv_sleep_us=%s" in launcher_source
    for promoted_wrapper in (LEAN_WRAPPER, DIRECT_BENCHMARK_WRAPPER):
        promoted_source = promoted_wrapper.read_text(encoding="utf-8")
        assert (
            "TOMB_RAIDER_RAKNET_RECV_SLEEP_US=${TOMB_RAIDER_RAKNET_RECV_SLEEP_US-1000}"
            in promoted_source
        )
    dispatcher_source = DISPATCHER.read_text(encoding="utf-8")
    assert "final_preloads.append(raknet_recv_backoff[0])" in dispatcher_source
    assert 'environment.update(raknet_recv_backoff[1])' in dispatcher_source
    print("Tomb Raider RakNet receive backoff tests: PASS")


if __name__ == "__main__":
    main()
