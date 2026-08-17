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
    assert MODULE.request_environment(
        {"environment": ["STEAM_COMPAT_APP_ID=203160", "LD_PRELOAD=unsafe"]}
    ) == {"STEAM_COMPAT_APP_ID": "203160"}

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
