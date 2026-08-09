#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def parse_args_fd(argv):
    for index, arg in enumerate(argv):
        if arg == "--args":
            return int(argv[index + 1])
        if arg.startswith("--args="):
            return int(arg.partition("=")[2])
    return None


def mock_bwrap():
    args_fd = parse_args_fd(sys.argv[1:])
    if args_fd is None:
        print("PASSTHROUGH")
        return 0

    data = os.pread(args_fd, os.fstat(args_fd).st_size, 0)
    args = [item.decode() for item in data.rstrip(b"\0").split(b"\0")]

    injected = None
    for index, arg in enumerate(args[:-2]):
        if arg == "--ro-bind-fd" and args[index + 2] == "/proc/net":
            injected = index

    if injected is None:
        print(json.dumps({"injected": False, "args": args}))
        return 0

    source_fd = int(args[injected + 1])
    source = Path(os.readlink(f"/proc/self/fd/{source_fd}"))
    print(
        json.dumps(
            {
                "injected": True,
                "source": str(source),
                "destination": args[injected + 2],
                "before_terminator":
                    "--" not in args or injected < args.index("--"),
                "entries": sorted(item.name for item in source.iterdir()),
                "route_data": (source / "route").read_text(),
                "ipv6_route_data": (source / "ipv6_route").read_text(),
            }
        )
    )
    return 0


def args_fd(args):
    data = b"\0".join(arg.encode() for arg in args) + b"\0"
    memfd_create = getattr(os, "memfd_create", None)
    if memfd_create is not None:
        args_file = os.fdopen(
            memfd_create("pressure-vessel-route-test"), "w+b"
        )
    else:
        args_file = tempfile.TemporaryFile(
            mode="w+b", prefix="pressure-vessel-route-test."
        )

    args_file.write(data)
    args_file.flush()
    args_file.seek(0)
    os.set_inheritable(args_file.fileno(), True)
    return args_file


def invoke(wrapper, proc_net, args, *, equals_form=False):
    args_file = args_fd(args)
    fd = args_file.fileno()
    env = os.environ.copy()
    env.update(
        {
            "STEAM_ARM64_BWRAP_TEST_MOCK": "1",
            "STEAM_ARM64_PROC_NET": str(proc_net),
            "STEAM_ARM64_REAL_BWRAP": str(Path(__file__).resolve()),
            "TMPDIR": str(proc_net.parent),
        }
    )
    wrapper_args = (
        [str(wrapper), f"--args={fd}", "payload"]
        if equals_form
        else [str(wrapper), "--args", str(fd), "payload"]
    )
    try:
        return subprocess.run(
            wrapper_args,
            env=env,
            pass_fds=(fd,),
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        args_file.close()


def run_tests():
    repo = Path(__file__).resolve().parent.parent
    source = repo / "diagnostics" / "pressure-vessel-route-bwrap.c"

    with tempfile.TemporaryDirectory(prefix="pressure-vessel-route-test.") as temp:
        tempdir = Path(temp)
        wrapper = tempdir / "steam-arm64-bwrap-route"
        proc_net = tempdir / "proc-net"
        proc_net.mkdir(mode=0o700)
        route = proc_net / "route"
        ipv6_route = proc_net / "ipv6_route"
        route_text = "Iface\tDestination\tGateway\n"
        route.write_text(route_text)
        route.chmod(0o600)
        ipv6_route.write_text("")
        ipv6_route.chmod(0o600)

        subprocess.run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(source),
                "-o",
                str(wrapper),
            ],
            check=True,
        )

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--dir", "/tmp", "--", "/bin/true"],
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload == {
            "injected": True,
            "source": str(proc_net),
            "destination": "/proc/net",
            "before_terminator": True,
            "entries": ["ipv6_route", "route"],
            "route_data": route_text,
            "ipv6_route_data": "",
        }

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            equals_form=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["injected"] is True
        assert payload["source"] == str(proc_net)
        assert payload["before_terminator"] is True

        memfd_create = getattr(os, "memfd_create", None)
        if memfd_create is not None:
            del os.memfd_create
        try:
            result = invoke(
                wrapper,
                proc_net,
                ["--proc", "/proc", "--", "/bin/true"],
            )
        finally:
            if memfd_create is not None:
                os.memfd_create = memfd_create
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["injected"] is True
        assert payload["source"] == str(proc_net)
        assert payload["before_terminator"] is True

        passthrough_env = os.environ.copy()
        passthrough_env.update(
            {
                "STEAM_ARM64_BWRAP_TEST_MOCK": "1",
                "STEAM_ARM64_PROC_NET": str(proc_net),
                "STEAM_ARM64_REAL_BWRAP": str(Path(__file__).resolve()),
            }
        )
        result = subprocess.run(
            [str(wrapper), "--version"],
            env=passthrough_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "PASSTHROUGH\n"

        result = invoke(wrapper, proc_net, ["--dir", "/tmp"])
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["injected"] is False

        route.chmod(0o622)
        result = invoke(wrapper, proc_net, ["--proc", "/proc"])
        assert result.returncode == 125
        assert "must not be group- or other-writable" in result.stderr

        route.chmod(0o600)
        unexpected = proc_net / "tcp"
        unexpected.write_text("not exposed\n")
        unexpected.chmod(0o600)
        result = invoke(wrapper, proc_net, ["--proc", "/proc"])
        assert result.returncode == 125
        assert "unexpected entry" in result.stderr

    print("pressure-vessel route bwrap wrapper tests: PASS")
    return 0


if __name__ == "__main__":
    if os.environ.get("STEAM_ARM64_BWRAP_TEST_MOCK") == "1":
        raise SystemExit(mock_bwrap())
    raise SystemExit(run_tests())
