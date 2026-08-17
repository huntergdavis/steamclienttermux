#!/usr/bin/env python3

import importlib.util
import inspect
import json
import os
from pathlib import Path
import socket
import tempfile


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
        wine_debug = "+timestamp,+pid,+tid,+process,+module,+loaddll,+seh"
        assert MODULE.proton_smoke_environment("proton-cmd", True) == {
            "WINEDEBUG": wine_debug
        }
        assert MODULE.proton_smoke_environment("proton-arm64-cmd", True) == {
            "WINEDEBUG": wine_debug
        }
    assert MODULE.request_environment(
        {
            "environment": [
                "STEAM_COMPAT_APP_ID=203160",
                "LD_PRELOAD=unsafe",
                "TGCOMPAT_USERFAULTFD_ENOSYS=unsafe",
            ]
        }
    ) == {"STEAM_COMPAT_APP_ID": "203160"}
    invocation_source = inspect.getsource(MODULE.pv_smoke_invocation)
    assert "libtgcompat-robust.so" in invocation_source
    assert '"TGCOMPAT_USERFAULTFD_ENOSYS": "1"' in invocation_source
    assert 'command_mode == "tombraider"' in invocation_source
    game_source = inspect.getsource(MODULE.run_tombraider)
    assert '"tombraider"' in game_source
    diagnostic_source = inspect.getsource(MODULE.run_tombraider_diagnostic)
    assert "tombraider-direct-process-" in diagnostic_source
    assert "trace_path" in diagnostic_source
    assert "False" in diagnostic_source
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
