#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


GTAIV_FILES = {
    "GTAIV.exe": 17425752,
    "MTLX.dll": 593240,
    "PlayGTAIV.exe": 264176,
    "binkw32.dll": 176640,
    "commandline.txt": 24,
    "gtaEncoder.exe": 47960,
    "installscript.vdf": 566,
    "metadata.dat": 472036,
    "steam_api.dll": 261072,
    "title.rgl": 1104,
}
GTAIV_DIRECTORIES = (
    "Manuals",
    "Redistributables",
    "TBoGT",
    "TLAD",
    "common",
    "movies",
    "pc",
)


def parse_args_fd(argv):
    for index, arg in enumerate(argv):
        if arg == "--args":
            return int(argv[index + 1])
        if arg.startswith("--args="):
            return int(arg.partition("=")[2])
    return None


def payload_argv(argv):
    for index, arg in enumerate(argv):
        if arg == "--args":
            return argv[index + 2:]
        if arg.startswith("--args="):
            return argv[index + 1:]
    return []


def mock_bwrap():
    args_fd = parse_args_fd(sys.argv[1:])
    if args_fd is None:
        print("PASSTHROUGH")
        return 0

    data = os.pread(args_fd, os.fstat(args_fd).st_size, 0)
    args = [item.decode() for item in data.rstrip(b"\0").split(b"\0")]

    injected = None
    gtaiv_injected = None
    vk_icd_bind_injected = None
    vk_driver_files_injected = None
    vk_icd_filenames_injected = None
    gtaiv_directory_injections = []
    directory_targets = []
    directory_injections = []
    install_bind = None
    for index, arg in enumerate(args[:-2]):
        if arg == "--ro-bind-fd":
            if args[index + 2] == "/proc/net":
                injected = index
            elif args[index + 2] in (
                "/overrides/share/vulkan/icd.d/freedreno-private.json",
                "/overrides/share/vulkan/icd.d/bvb_icd.aarch64.json",
            ):
                vk_icd_bind_injected = index
            elif args[index + 2].endswith("/Grand Theft Auto IV/GTAIV"):
                gtaiv_injected = index
            elif "/Grand Theft Auto IV/GTAIV/" in args[index + 2]:
                gtaiv_directory_injections.append(index)
        elif arg == "--setenv" and args[index + 1] == "VK_DRIVER_FILES":
            vk_driver_files_injected = index
        elif arg == "--setenv" and args[index + 1] == "VK_ICD_FILENAMES":
            vk_icd_filenames_injected = index
        elif arg == "--dir":
            directory_targets.append(args[index + 1])
            directory_injections.append(index)
        elif arg in ("--bind", "--ro-bind") and os.environ.get(
            "STEAM_COMPAT_INSTALL_PATH"
        ) == args[index + 2]:
            install_bind = index

    if injected is None:
        print(
            json.dumps(
                {
                    "injected": False,
                    "args": args,
                    "steam_game_id": os.environ.get("SteamGameId"),
                    "payload_argv": payload_argv(sys.argv[1:]),
                }
            )
        )
        return 0

    source_fd = int(args[injected + 1])
    source = Path(os.readlink(f"/proc/self/fd/{source_fd}"))
    gtaiv_source = None
    gtaiv_directory_sources = []
    if gtaiv_injected is not None:
        gtaiv_source_fd = int(args[gtaiv_injected + 1])
        gtaiv_source = Path(
            os.readlink(f"/proc/self/fd/{gtaiv_source_fd}")
        )
        for index in gtaiv_directory_injections:
            source_fd = int(args[index + 1])
            gtaiv_directory_sources.append(
                os.readlink(f"/proc/self/fd/{source_fd}")
            )
    payload = {
                "injected": True,
                "source": str(source),
                "destination": args[injected + 2],
                "before_terminator":
                    "--" not in args or injected < args.index("--"),
                "entries": sorted(item.name for item in source.iterdir()),
                "route_data": (source / "route").read_text(),
                "ipv6_route_data": (source / "ipv6_route").read_text(),
                "steam_game_id": os.environ.get("SteamGameId"),
                "payload_argv": payload_argv(sys.argv[1:]),
                "gtaiv_injected": gtaiv_injected is not None,
                "gtaiv_source": (
                    str(gtaiv_source) if gtaiv_source is not None else None
                ),
                "gtaiv_destination": (
                    args[gtaiv_injected + 2]
                    if gtaiv_injected is not None
                    else None
                ),
                "gtaiv_before_terminator": (
                    "--" not in args or gtaiv_injected < args.index("--")
                    if gtaiv_injected is not None
                    else None
                ),
                "gtaiv_at_end": (
                    gtaiv_injected == len(args) - 3
                    if gtaiv_injected is not None
                    else None
                ),
                "gtaiv_entries": (
                    sorted(item.name for item in gtaiv_source.iterdir())
                    if gtaiv_source is not None
                    else None
                ),
                "gtaiv_directory_sources": gtaiv_directory_sources,
                "gtaiv_directory_targets": [
                    args[index + 2]
                    for index in gtaiv_directory_injections
                ],
                "gtaiv_directory_after_view": (
                    all(index > gtaiv_injected
                        for index in gtaiv_directory_injections)
                    if gtaiv_injected is not None
                    else None
                ),
                "directory_targets": directory_targets,
                "directory_injections": directory_injections,
                "install_bind": install_bind,
            }
    if vk_driver_files_injected is not None:
        vk_icd_source_fd = int(args[vk_icd_bind_injected + 1])
        payload.update(
            {
                "vk_icd_source": os.readlink(
                    f"/proc/self/fd/{vk_icd_source_fd}"
                ),
                "vk_icd_target": args[vk_icd_bind_injected + 2],
                "vk_icd_bind_before_terminator": (
                    "--" not in args
                    or vk_icd_bind_injected < args.index("--")
                ),
                "vk_icd_bind_at_end": (
                    vk_icd_bind_injected == len(args) - 9
                ),
                "vk_driver_files": args[vk_driver_files_injected + 2],
                "vk_driver_files_before_terminator": (
                    "--" not in args
                    or vk_driver_files_injected < args.index("--")
                ),
                "vk_driver_files_at_end": (
                    vk_driver_files_injected == len(args) - 6
                ),
                "vk_icd_filenames": args[vk_icd_filenames_injected + 2],
                "vk_icd_filenames_before_terminator": (
                    "--" not in args
                    or vk_icd_filenames_injected < args.index("--")
                ),
                "vk_icd_filenames_at_end": (
                    vk_icd_filenames_injected == len(args) - 3
                ),
                "host_vk_driver_files_env": os.environ.get(
                    "STEAM_ARM64_HOST_VK_DRIVER_FILES"
                ),
            }
        )
    print(json.dumps(payload))
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


def invoke(
    wrapper,
    proc_net,
    args,
    *,
    equals_form=False,
    env_overrides=None,
    wrapper_payload=None,
):
    args_file = args_fd(args)
    fd = args_file.fileno()
    env = os.environ.copy()
    for key in (
        "STEAM_COMPAT_APP_ID",
        "STEAM_COMPAT_INSTALL_PATH",
        "SteamAppId",
        "SteamGameId",
    ):
        env.pop(key, None)
    env.update(
        {
            "STEAM_ARM64_BWRAP_TEST_MOCK": "1",
            "STEAM_ARM64_PROC_NET": str(proc_net),
            "STEAM_ARM64_REAL_BWRAP": str(Path(__file__).resolve()),
            "TMPDIR": str(proc_net.parent),
        }
    )
    if env_overrides is not None:
        env.update(env_overrides)
    if wrapper_payload is None:
        wrapper_payload = ["payload"]
    wrapper_args = (
        [str(wrapper), f"--args={fd}", *wrapper_payload]
        if equals_form
        else [str(wrapper), "--args", str(fd), *wrapper_payload]
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
        proc_net = tempdir / "config" / "proc-net"
        proc_net.parent.mkdir()
        proc_net.mkdir(mode=0o700)
        route = proc_net / "route"
        ipv6_route = proc_net / "ipv6_route"
        route_text = "Iface\tDestination\tGateway\n"
        route.write_text(route_text)
        route.chmod(0o600)
        ipv6_route.write_text("")
        ipv6_route.chmod(0o600)
        private_icd = (
            tempdir / "mesa-kgsl" / "icd.d" / "freedreno-private.json"
        )
        private_icd.parent.mkdir(parents=True)
        private_icd.write_text("{}\n")
        private_icd.chmod(0o600)
        bvb_icd = tempdir / "bvb" / "icd.d" / "bvb_icd.aarch64.json"
        bvb_icd.parent.mkdir(parents=True)
        bvb_icd.write_text("{}\n")
        bvb_icd.chmod(0o600)

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
            "steam_game_id": None,
            "payload_argv": ["payload"],
            "gtaiv_injected": False,
            "gtaiv_source": None,
            "gtaiv_destination": None,
            "gtaiv_before_terminator": None,
            "gtaiv_at_end": None,
            "gtaiv_entries": None,
            "gtaiv_directory_sources": [],
            "gtaiv_directory_targets": [],
            "gtaiv_directory_after_view": None,
            "directory_targets": ["/tmp"],
            "directory_injections": [5],
            "install_bind": None,
        }

        install_path = (
            tempdir
            / "removable-library"
            / "steamapps"
            / "common"
            / "No Man's Sky"
        )
        install_path.mkdir(parents=True)
        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind",
                str(install_path.parent.parent),
                str(install_path.parent.parent),
                "--bind",
                str(install_path),
                str(install_path),
                "--proc",
                "/proc",
                "--",
                "/bin/true",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "275850",
                "STEAM_COMPAT_INSTALL_PATH": str(install_path),
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        expected_chain = []
        for parent in reversed(install_path.parents):
            if parent != Path("/"):
                expected_chain.append(str(parent))
        expected_chain.append(str(install_path))
        assert payload["directory_targets"][: len(expected_chain)] == expected_chain
        assert payload["install_bind"] is not None
        assert max(payload["directory_injections"][: len(expected_chain)]) < (
            payload["install_bind"]
        )

        result = invoke(
            wrapper,
            proc_net,
            [
                "--proc",
                "/proc",
                "--bind",
                str(install_path),
                str(install_path),
                "--",
                "/bin/true",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "275850",
                "STEAM_COMPAT_INSTALL_PATH": str(install_path),
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["directory_targets"][: len(expected_chain)] == expected_chain
        assert max(payload["directory_injections"][: len(expected_chain)]) < (
            payload["install_bind"]
        )

        outside = tempdir / "outside" / "Game"
        outside.mkdir(parents=True)
        result = invoke(
            wrapper,
            proc_net,
            ["--ro-bind", "/runtime-root", "/", "--proc", "/proc"],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "275850",
                "STEAM_COMPAT_INSTALL_PATH": str(outside),
            },
        )
        assert result.returncode == 125
        assert "outside a supported Steam library" in result.stderr

        result = invoke(
            wrapper,
            proc_net,
            [
                "--proc",
                "/proc",
                "--setenv",
                "VK_DRIVER_FILES",
                "/overrides/share/vulkan/icd.d/freedreno-private.json",
                "--",
                "/bin/true",
            ],
            env_overrides={
                "STEAM_ARM64_HOST_VK_DRIVER_FILES": str(private_icd)
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        icd_target = "/overrides/share/vulkan/icd.d/freedreno-private.json"
        assert payload["vk_icd_source"] == str(private_icd)
        assert payload["vk_icd_target"] == icd_target
        assert payload["vk_icd_bind_before_terminator"] is True
        assert payload["vk_icd_bind_at_end"] is False
        assert payload["vk_driver_files"] == icd_target
        assert payload["vk_icd_filenames"] == icd_target
        assert payload["vk_driver_files_before_terminator"] is True
        assert payload["vk_icd_filenames_before_terminator"] is True
        assert payload["vk_driver_files_at_end"] is False
        assert payload["vk_icd_filenames_at_end"] is False
        assert payload["host_vk_driver_files_env"] is None

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={
                "STEAM_ARM64_HOST_VK_DRIVER_FILES": str(bvb_icd)
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        bvb_target = "/overrides/share/vulkan/icd.d/bvb_icd.aarch64.json"
        assert payload["vk_icd_source"] == str(bvb_icd)
        assert payload["vk_icd_target"] == bvb_target
        assert payload["vk_driver_files"] == bvb_target
        assert payload["vk_icd_filenames"] == bvb_target

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--ro-bind", "/", "/"],
            env_overrides={
                "STEAM_ARM64_HOST_VK_DRIVER_FILES": str(private_icd)
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["vk_icd_source"] == str(private_icd)
        assert payload["vk_icd_target"] == icd_target
        assert payload["vk_icd_bind_at_end"] is True
        assert payload["vk_driver_files"] == icd_target
        assert payload["vk_icd_filenames"] == icd_target
        assert payload["vk_driver_files_at_end"] is True
        assert payload["vk_icd_filenames_at_end"] is True

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={
                "STEAM_ARM64_HOST_VK_DRIVER_FILES": str(tempdir / "wrong.json")
            },
        )
        assert result.returncode == 125
        assert "unexpected native Vulkan ICD path" in result.stderr

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={"STEAM_COMPAT_APP_ID": "12210"},
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["steam_game_id"] == "12210"

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={"SteamAppId": "732430"},
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["steam_game_id"] == "732430"

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "SteamGameId": "1493710",
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["steam_game_id"] == "1493710"

        result = invoke(
            wrapper,
            proc_net,
            ["--proc", "/proc", "--", "/bin/true"],
            env_overrides={"STEAM_COMPAT_APP_ID": "not-an-app-id"},
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["steam_game_id"] is None

        install_path = (
            tempdir / "removable-library" / "steamapps" / "common"
            / "Grand Theft Auto IV"
        )
        original_gtaiv = install_path / "GTAIV"
        original_gtaiv.mkdir(parents=True)
        gtaiv_view = tempdir / "gtaiv-exec-view-12210"
        gtaiv_view.mkdir(mode=0o700)
        for name, size in GTAIV_FILES.items():
            path = gtaiv_view / name
            with path.open("wb") as output:
                output.truncate(size)
            path.chmod(0o600)
        for name in GTAIV_DIRECTORIES:
            (gtaiv_view / name).mkdir(mode=0o700)
            original = original_gtaiv / name
            original.mkdir(mode=0o700)
            (original / "payload-marker").write_text(name)

        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind", str(install_path), str(install_path),
                "--proc", "/proc", "--", "/bin/true",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "STEAM_COMPAT_INSTALL_PATH": install_path,
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["gtaiv_injected"] is True
        assert payload["gtaiv_source"] == str(gtaiv_view)
        assert payload["gtaiv_destination"] == f"{install_path}/GTAIV"
        assert payload["gtaiv_before_terminator"] is True
        assert payload["gtaiv_entries"] == sorted(
            [*GTAIV_FILES, *GTAIV_DIRECTORIES]
        )
        assert payload["gtaiv_directory_sources"] == [
            str(original_gtaiv / name) for name in GTAIV_DIRECTORIES
        ]
        assert payload["gtaiv_directory_targets"] == [
            f"{install_path}/GTAIV/{name}" for name in GTAIV_DIRECTORIES
        ]
        assert payload["gtaiv_directory_after_view"] is True

        play_path = f"{install_path}/GTAIV/PlayGTAIV.exe"
        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind", str(install_path), str(install_path),
                "--proc", "/proc",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "STEAM_COMPAT_INSTALL_PATH": install_path,
            },
            wrapper_payload=[
                "/opt/proton/proton",
                "waitforexitandrun",
                play_path,
            ],
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["payload_argv"] == [
            "/opt/proton/proton",
            "waitforexitandrun",
            "cmd.exe",
            "/d",
            "/c",
            r"C:\gtaiv-service-first.cmd",
        ]

        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind", str(install_path), str(install_path),
                "--proc", "/proc",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "STEAM_COMPAT_INSTALL_PATH": install_path,
            },
            wrapper_payload=[
                "/opt/proton/proton",
                "runinprefix",
                play_path,
            ],
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["payload_argv"][-3:] == [
            "/opt/proton/proton",
            "runinprefix",
            play_path,
        ]

        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind", str(install_path), str(install_path),
                "--proc", "/proc",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "STEAM_COMPAT_INSTALL_PATH": install_path,
            },
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["gtaiv_injected"] is True
        assert payload["gtaiv_before_terminator"] is True
        assert payload["gtaiv_at_end"] is False
        assert payload["gtaiv_directory_targets"][-1] == (
            f"{install_path}/GTAIV/{GTAIV_DIRECTORIES[-1]}"
        )

        gtaiv_view.chmod(0o770)
        result = invoke(
            wrapper,
            proc_net,
            [
                "--bind", str(install_path), str(install_path),
                "--proc", "/proc", "--", "/bin/true",
            ],
            env_overrides={
                "STEAM_COMPAT_APP_ID": "12210",
                "STEAM_COMPAT_INSTALL_PATH": install_path,
            },
        )
        assert result.returncode == 125
        assert "must be a private directory" in result.stderr
        gtaiv_view.chmod(0o700)

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
