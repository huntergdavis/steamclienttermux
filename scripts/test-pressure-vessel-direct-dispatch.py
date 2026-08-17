#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import socket
import tempfile


SCRIPT = Path(__file__).with_name("pressure-vessel-direct-dispatch.py")
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
