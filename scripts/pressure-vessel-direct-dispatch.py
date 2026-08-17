#!/usr/bin/env python3
"""Move a Pressure Vessel payload out of PRoot without logging its environment."""

from __future__ import annotations

import argparse
import array
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import struct
import sys
from typing import NoReturn


SCHEMA_VERSION = 1
KIND = "steamclienttermux-pressure-vessel-direct"
MAX_FRAME = 16 * 1024 * 1024
MAX_FDS = 64
MAX_ARGS_DATA = 16 * 1024 * 1024
ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FD_SOURCE_OPTIONS = {
    "--bind-data",
    "--bind-fd",
    "--file",
    "--ro-bind-data",
    "--ro-bind-fd",
    "--seccomp",
    "--sync-fd",
    "--info-fd",
    "--json-status-fd",
    "--userns",
}
BIND_OPTIONS = {
    "--bind",
    "--bind-try",
    "--dev-bind",
    "--dev-bind-try",
    "--ro-bind",
    "--ro-bind-try",
}


class DispatchError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise DispatchError(message)


def private_directory(path: Path, description: str, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"{description} is not a real directory: {path}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        fail(f"{description} is not privately owned: {path}")
    return path


def validated_base(value: str) -> Path:
    if not value.startswith("/"):
        fail("Steam base must be absolute")
    base = Path(value)
    metadata = base.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or base.is_symlink():
        fail(f"Steam base is not a real directory: {base}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        fail(f"Steam base is not privately owned: {base}")
    return base


def dispatch_socket(base: Path) -> Path:
    run = private_directory(base / "run", "Steam run directory", create=True)
    directory = private_directory(
        run / "native-runtime-dispatch", "Runtime dispatch directory", create=True
    )
    return directory / "dispatch.sock"


def locate_args_fd(arguments: list[str]) -> tuple[int, int, int]:
    for index, argument in enumerate(arguments):
        if argument == "--args":
            if index + 1 >= len(arguments):
                fail("--args is missing its fd")
            value = arguments[index + 1]
            payload_start = index + 2
            break
        if argument.startswith("--args="):
            value = argument[7:]
            payload_start = index + 1
            break
    else:
        fail("Pressure Vessel invocation has no --args fd")
    if not value.isdecimal():
        fail("invalid --args fd")
    return int(value), index, payload_start


def read_nul_arguments(descriptor: int) -> list[str]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_ARGS_DATA:
        fail("unexpected --args fd type or size")
    data = os.pread(descriptor, metadata.st_size, 0)
    if len(data) != metadata.st_size or not data.endswith(b"\0"):
        fail("malformed --args data")
    return [os.fsdecode(value) for value in data[:-1].split(b"\0")]


def parse_nonnegative_fd(value: str, description: str) -> int:
    if not value.isdecimal():
        fail(f"invalid fd for {description}")
    descriptor = int(value)
    if descriptor < 0:
        fail(f"invalid fd for {description}")
    return descriptor


def referenced_fd_numbers(bwrap_arguments: list[str], payload: list[str]) -> list[int]:
    descriptors: set[int] = set()
    for index, argument in enumerate(bwrap_arguments[:-1]):
        if argument in FD_SOURCE_OPTIONS:
            descriptors.add(
                parse_nonnegative_fd(bwrap_arguments[index + 1], argument)
            )
    for index, argument in enumerate(payload):
        if argument == "--fd":
            if index + 1 >= len(payload):
                fail("pv-adverb --fd is missing its value")
            descriptors.add(parse_nonnegative_fd(payload[index + 1], "--fd"))
        elif argument.startswith("--fd="):
            descriptors.add(parse_nonnegative_fd(argument[5:], "--fd"))
        elif argument.startswith("--assign-fd="):
            assignment = argument[12:]
            destination, separator, source = assignment.partition("=")
            if not separator:
                fail("invalid pv-adverb --assign-fd")
            parse_nonnegative_fd(destination, "--assign-fd destination")
            descriptors.add(parse_nonnegative_fd(source, "--assign-fd source"))
    ordered = sorted(descriptors)
    if len(ordered) > MAX_FDS:
        fail("Pressure Vessel request references too many fds")
    for descriptor in ordered:
        os.fstat(descriptor)
    return ordered


def encode_frame(payload: dict[str, object]) -> bytes:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if not data or len(data) > MAX_FRAME:
        fail("dispatch frame has an invalid size")
    return data


def send_request(
    connection: socket.socket, payload: dict[str, object], descriptors: list[int]
) -> None:
    data = encode_frame(payload)
    ancillary = []
    if descriptors:
        packed = array.array("i", descriptors)
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, packed)]
    header = struct.pack("!I", len(data))
    sent = connection.sendmsg([header], ancillary)
    if sent <= 0:
        fail("unable to send dispatch header")
    if sent < len(header):
        connection.sendall(header[sent:])
    connection.sendall(data)


def receive_request(connection: socket.socket) -> tuple[dict[str, object], list[int]]:
    header, ancillary, flags, _ = connection.recvmsg(
        4, socket.CMSG_SPACE(MAX_FDS * array.array("i").itemsize)
    )
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        fail("truncated dispatch request")
    while len(header) < 4:
        chunk = connection.recv(4 - len(header))
        if not chunk:
            fail("incomplete dispatch header")
        header += chunk
    length = struct.unpack("!I", header)[0]
    if not 0 < length <= MAX_FRAME:
        fail("dispatch frame has an invalid size")
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            fail("incomplete dispatch frame")
        chunks.extend(chunk)
    descriptors: list[int] = []
    for level, kind, value in ancillary:
        if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
            continue
        received = array.array("i")
        usable = len(value) - (len(value) % received.itemsize)
        received.frombytes(value[:usable])
        descriptors.extend(received.tolist())
    if len(descriptors) > MAX_FDS:
        fail("dispatch request supplied too many fds")
    try:
        payload = json.loads(chunks.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"invalid dispatch JSON: {error}")
    if not isinstance(payload, dict):
        fail("dispatch payload is not an object")
    return payload, descriptors


def send_response(connection: socket.socket, status: int, tracer_pid: int = -1) -> None:
    data = encode_frame({"status": status, "tracer_pid": tracer_pid})
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive_response(connection: socket.socket) -> tuple[int, int]:
    header = connection.recv(4, socket.MSG_WAITALL)
    if len(header) != 4:
        fail("incomplete dispatch response")
    length = struct.unpack("!I", header)[0]
    if not 0 < length <= 4096:
        fail("invalid dispatch response size")
    data = connection.recv(length, socket.MSG_WAITALL)
    if len(data) != length:
        fail("incomplete dispatch response")
    response = json.loads(data.decode("utf-8"))
    status = response.get("status")
    tracer_pid = response.get("tracer_pid", -1)
    if not isinstance(status, int) or not 0 <= status <= 255:
        fail("invalid dispatch response status")
    if not isinstance(tracer_pid, int):
        fail("invalid dispatch tracer pid")
    return status, tracer_pid


def path_has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def plan_mappings(arguments: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    binds: dict[str, str] = {}
    symlinks: dict[str, str] = {}
    for index, argument in enumerate(arguments):
        if argument in BIND_OPTIONS and index + 2 < len(arguments):
            source, destination = arguments[index + 1 : index + 3]
            if source.startswith("/") and destination.startswith("/"):
                binds[destination.rstrip("/") or "/"] = source.rstrip("/") or "/"
        elif argument == "--symlink" and index + 2 < len(arguments):
            target, destination = arguments[index + 1 : index + 3]
            if destination.startswith("/"):
                symlinks[destination.rstrip("/") or "/"] = target
    return binds, symlinks


def translated_path(path: str, binds: dict[str, str], symlinks: dict[str, str]) -> str:
    if not path.startswith("/"):
        fail(f"container path is not absolute: {path}")
    current = str(PurePosixPath(path))
    for _ in range(32):
        candidates = [prefix for prefix in symlinks if path_has_prefix(current, prefix)]
        if candidates:
            prefix = max(candidates, key=len)
            suffix = current[len(prefix) :]
            target = symlinks[prefix]
            if target.startswith("/"):
                current = str(PurePosixPath(target + suffix))
            else:
                current = str(
                    PurePosixPath(prefix).parent
                    / target.lstrip("/")
                    / suffix.lstrip("/")
                )
            continue
        candidates = [prefix for prefix in binds if path_has_prefix(current, prefix)]
        if candidates:
            prefix = max(candidates, key=len)
            suffix = current[len(prefix) :]
            return str(PurePosixPath(binds[prefix] + suffix))
        return current
    fail(f"container path mapping loops: {path}")


def validate_request(payload: dict[str, object], descriptors: list[int]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != KIND:
        fail("unsupported dispatch request")
    for name in ("bwrap_args", "payload_argv", "environment"):
        value = payload.get(name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            fail(f"dispatch {name} is invalid")
    numbers = payload.get("fd_numbers")
    if not isinstance(numbers, list) or not all(isinstance(item, int) for item in numbers):
        fail("dispatch fd_numbers is invalid")
    if len(numbers) != len(descriptors) or len(set(numbers)) != len(numbers):
        fail("dispatch fd metadata does not match received fds")


def tracer_pid(process: int) -> int:
    try:
        lines = Path(f"/proc/{process}/status").read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return -1
    for line in lines:
        if line.startswith("TracerPid:"):
            value = line.split(":", 1)[1].strip()
            return int(value) if value.isdecimal() else -1
    return -1


def selected_runtime(base: Path) -> tuple[Path, Path, str]:
    runtime_root = (base / "runtime/SteamLinuxRuntime_4-arm64-direct/current").resolve(
        strict=True
    )
    glibc_root = (Path.home() / ".local/share/tgcompat/glibc/current").resolve(
        strict=True
    )
    loader = glibc_root / "lib/ld-linux-aarch64.so.1"
    if not loader.is_file() or not os.access(loader, os.X_OK):
        fail(f"patched glibc loader is unavailable: {loader}")
    libraries = ":".join(
        str(path)
        for path in (
            glibc_root / "lib",
            runtime_root / "usr/lib/aarch64-linux-gnu",
            runtime_root / "usr/lib",
        )
    )
    return runtime_root, loader, libraries


def remap_descriptors(received: list[int], targets: list[int]) -> None:
    if len(received) != len(targets):
        fail("received descriptor count changed before execution")
    minimum = max([64, *received, *targets]) + 1
    temporary: list[tuple[int, int]] = []
    try:
        for source, target in zip(received, targets):
            duplicate = fcntl.fcntl(source, fcntl.F_DUPFD_CLOEXEC, minimum)
            temporary.append((duplicate, target))
            minimum = duplicate + 1
        for source in received:
            os.close(source)
        for duplicate, target in temporary:
            os.dup2(duplicate, target, inheritable=True)
    finally:
        for duplicate, _ in temporary:
            try:
                os.close(duplicate)
            except OSError:
                pass


def run_loader_child(
    loader: Path,
    arguments: list[str],
    environment: dict[str, str],
    descriptors: list[int],
    target_numbers: list[int],
    trace_path: Path | None = None,
) -> tuple[int, int]:
    executable = loader
    execution_arguments = arguments
    execution_environment = environment
    if trace_path is not None:
        prefix = os.environ.get("PREFIX", "")
        strace = Path(prefix) / "bin/strace"
        metadata = strace.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or strace.is_symlink()
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o022
            or not os.access(strace, os.X_OK)
        ):
            fail(f"Termux strace is unavailable or unsafe: {strace}")
        execution_environment = environment.copy()
        forwarded: list[str] = []
        for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "GLIBC_LD_LIBRARY_PATH"):
            value = execution_environment.pop(name, None)
            if value is not None:
                forwarded.extend(["-E", f"{name}={value}"])
        executable = strace
        execution_arguments = [
            str(strace),
            "-f",
            "-qq",
            "-s",
            "256",
            "-o",
            str(trace_path),
            "-e",
            "trace=%file,%process,%memory",
            *forwarded,
            *arguments,
        ]
    ready_read, ready_write = os.pipe()
    process = os.fork()
    if process == 0:
        try:
            os.close(ready_write)
            if os.read(ready_read, 1) != b"x":
                os._exit(125)
            os.close(ready_read)
            remap_descriptors(descriptors, target_numbers)
            os.execve(executable, execution_arguments, execution_environment)
        except BaseException:
            os._exit(125)
    os.close(ready_read)
    observed_tracer = tracer_pid(process)
    os.write(ready_write, b"x")
    os.close(ready_write)
    _, wait_status = os.waitpid(process, 0)
    if observed_tracer != 0:
        return 125, observed_tracer
    if os.WIFEXITED(wait_status):
        return os.WEXITSTATUS(wait_status), observed_tracer
    if os.WIFSIGNALED(wait_status):
        return 128 + os.WTERMSIG(wait_status), observed_tracer
    return 125, observed_tracer


def runtime_true_from_plan(base: Path, payload: dict[str, object]) -> tuple[Path, Path, str]:
    bwrap_arguments = payload["bwrap_args"]
    payload_arguments = payload["payload_argv"]
    assert isinstance(bwrap_arguments, list)
    assert isinstance(payload_arguments, list)
    if "--" not in payload_arguments:
        fail("pv-adverb payload has no command boundary")
    boundary = payload_arguments.index("--")
    command = payload_arguments[boundary + 1 :]
    if command != ["/bin/true"]:
        fail("direct dispatcher smoke accepts only /bin/true")
    binds, symlinks = plan_mappings(bwrap_arguments)
    program = Path(translated_path(command[0], binds, symlinks)).resolve(strict=True)
    runtime_root, loader, libraries = selected_runtime(base)
    expected = (runtime_root / "usr/bin/true").resolve(strict=True)
    if program != expected or not program.is_file() or not os.access(program, os.X_OK):
        fail(f"translated smoke payload is not Runtime true: {program}")
    return program, loader, libraries


def clean_loader_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "GLIBC_LD_LIBRARY_PATH"):
        environment.pop(name, None)
    return environment


def request_environment(payload: dict[str, object]) -> dict[str, str]:
    entries = payload["environment"]
    assert isinstance(entries, list)
    environment: dict[str, str] = {}
    for entry in entries:
        name, separator, value = entry.partition("=")
        if not separator or not ENVIRONMENT_NAME.fullmatch(name):
            fail("dispatch environment contains an invalid assignment")
        environment[name] = value
    for name in (
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "GLIBC_LD_LIBRARY_PATH",
        "TGCOMPAT_LD_SO",
        "TGCOMPAT_LIBRARY_PATH",
        "TGCOMPAT_EXEC_LD_PRELOAD",
        "TGCOMPAT_PROC_SELF_EXE",
    ):
        environment.pop(name, None)
    return environment


def validated_tombraider_command(
    base: Path, payload_arguments: list[str]
) -> tuple[Path, Path]:
    if "--" not in payload_arguments:
        fail("Tomb Raider payload has no command boundary")
    boundary = payload_arguments.index("--")
    command = payload_arguments[boundary + 1 :]
    proton = (
        base
        / "client/steamapps/common/Proton 11.0 (ARM64)/proton"
    )
    game = (
        base
        / "removable-library/steamapps/common/Tomb Raider/TombRaider.exe"
    )
    expected = [str(proton), "waitforexitandrun", str(game), "-nolauncher"]
    if command != expected:
        fail("direct Proton smoke received an unexpected game command")
    return proton, game


def proton_smoke_command(
    base: Path, runtime_root: Path, proton: Path, command_mode: str
) -> list[str]:
    runtime_python = runtime_root / "usr/bin/python3"
    if not runtime_python.is_file() or not os.access(runtime_python, os.X_OK):
        fail(f"Runtime Python is unavailable: {runtime_python}")
    if not proton.is_file() or not os.access(proton, os.X_OK):
        fail(f"validated Proton entry point is unavailable: {proton}")
    if command_mode == "proton-entry":
        return [str(runtime_python), str(proton), "steamclienttermux-probe"]
    if command_mode in ("proton-cmd", "proton-arm64-cmd"):
        architecture = (
            "x86_64-windows"
            if command_mode == "proton-cmd"
            else "aarch64-windows"
        )
        command = (
            base
            / "client/steamapps/common/Proton 11.0 (ARM64)"
            / f"files/lib/wine/{architecture}/cmd.exe"
        )
        if not command.is_file() or command.is_symlink():
            fail(f"validated Proton command is unavailable: {command}")
        return [
            str(runtime_python),
            str(proton),
            "waitforexitandrun",
            str(command),
            "/d",
            "/c",
            "exit",
            "/b",
            "0",
        ]
    fail(f"unsupported Proton smoke mode: {command_mode}")


def proton_smoke_environment(command_mode: str) -> dict[str, str]:
    if command_mode == "proton-entry":
        return {}
    if command_mode in ("proton-cmd", "proton-arm64-cmd"):
        return {
            "WINEDEBUG": "+timestamp,+pid,+tid,+process,+module,+loaddll,+seh"
        }
    fail(f"unsupported Proton smoke mode: {command_mode}")


def run_final_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    program, loader, libraries = runtime_true_from_plan(base, payload)
    arguments = [
        str(loader),
        "--inhibit-cache",
        "--library-path",
        libraries,
        str(program),
    ]
    return run_loader_child(
        loader,
        arguments,
        clean_loader_environment(),
        descriptors,
        payload["fd_numbers"],
    )


def pv_smoke_invocation(
    base: Path, payload: dict[str, object], command_mode: str = "runtime-true"
) -> tuple[Path, list[str], dict[str, str]]:
    runtime_root, loader, runtime_libraries = selected_runtime(base)
    bwrap_arguments = payload["bwrap_args"]
    payload_arguments = payload["payload_argv"]
    assert isinstance(bwrap_arguments, list)
    assert isinstance(payload_arguments, list)
    if "--" not in payload_arguments:
        fail("pv-adverb payload has no command boundary")
    binds, symlinks = plan_mappings(bwrap_arguments)
    boundary = payload_arguments.index("--")
    pv_path = Path(translated_path(payload_arguments[0], binds, symlinks))
    expected_pv = (
        base
        / "client/steamapps/common/SteamLinuxRuntime_4-arm64/pressure-vessel"
        / "libexec/steam-runtime-tools-0/pv-adverb"
    )
    if not pv_path.is_file() or not os.access(pv_path, os.X_OK):
        fail(f"translated pv-adverb is unavailable: {pv_path}")
    if not expected_pv.exists() or not os.path.samefile(pv_path, expected_pv):
        fail(f"translated pv-adverb is unexpected: {pv_path}")
    pv_library = (
        expected_pv.parent.parent.parent
        / "lib/aarch64-linux-gnu/steam-runtime-tools-0"
    )
    glibc_library, separator, remaining_libraries = runtime_libraries.partition(":")
    if not separator:
        fail("Runtime library path is incomplete")
    libraries = f"{glibc_library}:{pv_library}:{remaining_libraries}"
    rewritten = [str(pv_path)]
    index = 1
    removed_flags = {"--generate-locales"}
    removed_pairs = {
        "--regenerate-ld.so-cache",
        "--add-ld.so-path",
        "--set-ld-library-path",
        "--overrides-path",
    }
    while index < boundary:
        argument = payload_arguments[index]
        if argument in removed_flags:
            index += 1
            continue
        if argument in removed_pairs:
            if index + 1 >= boundary:
                fail(f"pv-adverb option is missing its value: {argument}")
            index += 2
            continue
        if argument.startswith("--prefix="):
            rewritten.append(f"--prefix={expected_pv.parent.parent.parent}")
        else:
            rewritten.append(argument)
        index += 1
    if command_mode == "runtime-true":
        program, _, _ = runtime_true_from_plan(base, payload)
        command = [str(program)]
        preserve_assignments = True
    elif command_mode in ("proton-entry", "proton-cmd", "proton-arm64-cmd"):
        proton, _ = validated_tombraider_command(base, payload_arguments)
        command = proton_smoke_command(base, runtime_root, proton, command_mode)
        preserve_assignments = False
    else:
        fail(f"unsupported pv-adverb command mode: {command_mode}")
    if not preserve_assignments:
        rewritten = [
            argument
            for argument in rewritten
            if not argument.startswith("--assign-fd=")
        ]
    rewritten.extend(["--set-ld-library-path", libraries, "--", *command])
    compat_repo = Path.home() / "workspace/termux-glibc-compat"
    preloads = [
        base / "compat-bin/steam-arm64-native-tmp.so",
        compat_repo / "build/libtgcompat-android-root.so",
        compat_repo / "build/libtgcompat-exec.so",
    ]
    if any(not path.is_file() for path in preloads):
        fail("pv-adverb compatibility preload is unavailable")
    preload = ":".join(str(path) for path in preloads)
    environment = request_environment(payload)
    if command_mode in ("proton-entry", "proton-cmd", "proton-arm64-cmd"):
        environment.update(proton_smoke_environment(command_mode))
    prefix = os.environ.get("PREFIX", "")
    if not prefix.startswith("/"):
        fail("Termux PREFIX is unavailable to the direct dispatcher")
    environment.update(
        {
            "LD_PRELOAD": preload,
            "TGCOMPAT_ANDROID_ROOT_O_PATH": "1",
            "TGCOMPAT_PROC_SELF_EXE": str(pv_path),
            "TGCOMPAT_LD_SO": str(loader),
            "TGCOMPAT_LIBRARY_PATH": libraries,
            "TGCOMPAT_EXEC_LD_PRELOAD": preload,
            "TGCOMPAT_EXEC_SHELL": str(runtime_root / "usr/bin/sh"),
            "STEAM_ARM64_TMP_ROOT": prefix + "/tmp",
            "STEAM_ARM64_SHM_ROOT": str(base / "run/native-steam/shm"),
            "STEAM_ARM64_LINUX_ROOT": str(
                Path(prefix) / "var/lib/proot-distro/containers/debian/rootfs"
            ),
            "PATH": ":".join(
                (
                    str(base / "compat-bin"),
                    str(runtime_root / "usr/bin"),
                    str(runtime_root / "usr/sbin"),
                    prefix + "/bin",
                )
            ),
            "VK_DRIVER_FILES": str(base / "mesa-kgsl/icd.d/freedreno-private.json"),
            "VK_ICD_FILENAMES": str(base / "mesa-kgsl/icd.d/freedreno-private.json"),
        }
    )
    loader_arguments = [
        str(loader),
        "--inhibit-cache",
        "--library-path",
        libraries,
        "--argv0",
        str(pv_path),
        *rewritten,
    ]
    return loader, loader_arguments, environment


def run_pv_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(base, payload)
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_proton_entry_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-entry"
    )
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_proton_cmd_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-cmd"
    )
    return run_loader_child(
        loader, arguments, environment, descriptors, payload["fd_numbers"]
    )


def run_proton_arm64_cmd_smoke(
    base: Path,
    payload: dict[str, object],
    descriptors: list[int],
) -> tuple[int, int]:
    loader, arguments, environment = pv_smoke_invocation(
        base, payload, "proton-arm64-cmd"
    )
    logs = private_directory(base / "logs", "Steam log directory")
    trace_path = logs / f"proton-arm64-wine-{os.getpid()}.strace"
    print(f"STRACE_LOG={trace_path}", flush=True)
    return run_loader_child(
        loader,
        arguments,
        environment,
        descriptors,
        payload["fd_numbers"],
        trace_path,
    )


def verify_peer(connection: socket.socket) -> None:
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    _, uid, _ = struct.unpack("3i", credentials)
    if uid != os.geteuid():
        fail("dispatch peer uid does not match")


def serve(base: Path, mode: str) -> int:
    path = dispatch_socket(base)
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
            fail(f"refusing unsafe existing dispatch socket: {path}")
        path.unlink()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen(1)
        print(f"READY={path}", flush=True)
        connection, _ = listener.accept()
        with connection:
            verify_peer(connection)
            payload, descriptors = receive_request(connection)
            try:
                validate_request(payload, descriptors)
                print(f"REQUEST_RECEIVED=1 FD_COUNT={len(descriptors)}", flush=True)
                if mode == "final-smoke":
                    status, observed_tracer = run_final_smoke(
                        base, payload, descriptors
                    )
                elif mode == "pv-smoke":
                    status, observed_tracer = run_pv_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-entry-smoke":
                    status, observed_tracer = run_proton_entry_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-cmd-smoke":
                    status, observed_tracer = run_proton_cmd_smoke(
                        base, payload, descriptors
                    )
                elif mode == "proton-arm64-cmd-smoke":
                    status, observed_tracer = run_proton_arm64_cmd_smoke(
                        base, payload, descriptors
                    )
                else:
                    fail(f"unsupported server mode: {mode}")
                print(
                    f"DISPATCH_STATUS={status} TRACER_PID={observed_tracer}",
                    flush=True,
                )
                send_response(connection, status, observed_tracer)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
    finally:
        listener.close()
        if path.exists() and not path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.geteuid():
                path.unlink()
    return 0


def delegate_probe(arguments: list[str], base: Path) -> NoReturn:
    selected = os.environ.get("STEAM_ARM64_DIRECT_REAL_BWRAP", "")
    expected = (
        base
        / "runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec"
        / "steam-runtime-tools-0/srt-bwrap"
    )
    if selected != str(expected):
        fail("direct probe delegate is not the expected srt-bwrap")
    metadata = expected.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or expected.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not os.access(expected, os.X_OK)
    ):
        fail(f"direct probe delegate is not protected: {expected}")
    os.execv(expected, [str(expected), *arguments])
    fail("cannot execute direct probe delegate")


def client(arguments: list[str], base: Path) -> int:
    if not any(argument == "--args" or argument.startswith("--args=") for argument in arguments):
        delegate_probe(arguments, base)
    args_fd, _, payload_start = locate_args_fd(arguments)
    bwrap_arguments = read_nul_arguments(args_fd)
    payload_arguments = arguments[payload_start:]
    descriptors = referenced_fd_numbers(bwrap_arguments, payload_arguments)
    request = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "cwd": os.getcwd(),
        "bwrap_args": bwrap_arguments,
        "payload_argv": payload_arguments,
        "environment": [f"{name}={value}" for name, value in os.environ.items()],
        "fd_numbers": descriptors,
    }
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    with connection:
        connection.connect(str(dispatch_socket(base)))
        send_request(connection, request, descriptors)
        status, observed_tracer = receive_response(connection)
    if status == 0:
        print(f"direct Runtime smoke: PASS tracer_pid={observed_tracer}")
    return status


def main() -> int:
    try:
        arguments = sys.argv[1:]
        base_value = os.environ.get("STEAM_ARM64_BASE", str(Path.home() / "steam-arm64"))
        if arguments and arguments[0] == "serve":
            parser = argparse.ArgumentParser()
            parser.add_argument("serve", nargs="?")
            parser.add_argument("--base", default=base_value)
            parser.add_argument(
                "--mode",
                choices=(
                    "final-smoke",
                    "pv-smoke",
                    "proton-entry-smoke",
                    "proton-cmd-smoke",
                    "proton-arm64-cmd-smoke",
                ),
                default="final-smoke",
            )
            options = parser.parse_args(arguments)
            return serve(validated_base(options.base), options.mode)
        if arguments and arguments[0] == "client":
            arguments = arguments[1:]
        return client(arguments, validated_base(base_value))
    except (DispatchError, OSError, ValueError) as error:
        print(f"pressure-vessel-direct-dispatch: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
