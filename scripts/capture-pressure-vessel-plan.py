#!/usr/bin/env python3
"""Capture Pressure Vessel's bwrap plan without executing its payload."""

import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


MAX_ARGS_DATA = 16 * 1024 * 1024
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
FD_SOURCE_OPTIONS = {
    "--bind-data",
    "--bind-fd",
    "--file",
    "--ro-bind-data",
    "--ro-bind-fd",
    "--seccomp",
}


def fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def owned_directory(path: Path, description: str, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"{description} is not a real directory: {path}")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
        fail(f"{description} is not privately owned: {path}")
    return path


def output_path() -> Path:
    base_value = os.environ.get("STEAM_ARM64_BASE", "")
    output_value = os.environ.get("STEAM_ARM64_BWRAP_CAPTURE_PLAN", "")
    if not base_value.startswith("/") or not output_value.startswith("/"):
        fail("STEAM_ARM64_BASE and capture output must be absolute")
    base = owned_directory(Path(base_value), "Steam base")
    logs = owned_directory(base / "logs", "Steam log directory")
    directory = owned_directory(logs / "runtime-plans", "runtime plan directory", create=True)
    output = Path(output_value)
    if output.parent != directory or not SAFE_NAME.fullmatch(output.name):
        fail("capture output must be a safe JSON name in the runtime plan directory")
    if output.exists() or output.is_symlink():
        fail(f"refusing to replace capture output: {output}")
    return output


def pass_through_probe(arguments: list[str]) -> int:
    base_value = os.environ.get("STEAM_ARM64_BASE", "")
    selected_value = os.environ.get("STEAM_ARM64_CAPTURE_REAL_BWRAP", "")
    if not base_value.startswith("/") or not selected_value.startswith("/"):
        fail("capture probe delegate and Steam base must be absolute")
    base = owned_directory(Path(base_value), "Steam base")
    expected = (
        base
        / "runtime"
        / "SteamLinuxRuntime_4-arm64"
        / "pressure-vessel"
        / "libexec"
        / "steam-runtime-tools-0"
        / "srt-bwrap"
    )
    selected = Path(selected_value)
    if selected != expected:
        fail("capture probe delegate is not the expected srt-bwrap")
    metadata = selected.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or selected.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not os.access(selected, os.X_OK)
    ):
        fail("capture probe delegate is not a protected executable")
    os.execv(selected, [str(selected), *arguments])
    fail("cannot execute capture probe delegate")


def locate_args_fd(arguments: list[str]) -> tuple[int, int, list[str]]:
    for index, argument in enumerate(arguments):
        if argument == "--args":
            if index + 1 >= len(arguments):
                fail("--args is missing its fd")
            value = arguments[index + 1]
            invocation = arguments.copy()
            invocation[index + 1] = "<args-fd>"
            break
        if argument.startswith("--args="):
            value = argument[7:]
            invocation = arguments.copy()
            invocation[index] = "--args=<args-fd>"
            break
    else:
        fail("Pressure Vessel invocation has no --args fd")
    if not value.isdecimal():
        fail("invalid --args fd")
    return int(value), index, invocation


def read_args(fd: int) -> list[str]:
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_ARGS_DATA:
        fail("unexpected --args fd type or size")
    data = os.pread(fd, metadata.st_size, 0)
    if len(data) != metadata.st_size or not data.endswith(b"\0"):
        fail("malformed --args data")
    return [os.fsdecode(item) for item in data[:-1].split(b"\0")]


def referenced_fds(arguments: list[str]) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    for index, argument in enumerate(arguments[:-1]):
        if argument not in FD_SOURCE_OPTIONS:
            continue
        value = arguments[index + 1]
        if not value.isdecimal():
            fail(f"{argument} has an invalid fd")
        fd = int(value)
        try:
            source = os.readlink(f"/proc/self/fd/{fd}")
        except OSError as error:
            fail(f"cannot resolve fd for {argument}: {error}")
        references.append(
            {"argument_index": index, "option": argument, "fd": fd, "source": source}
        )
    return references


def write_private_json(path: Path, payload: dict[str, object]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            fail(f"refusing to replace capture output: {path}")
        os.replace(temporary, path)
        temporary = ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def main() -> int:
    try:
        arguments = sys.argv[1:]
        if not any(
            argument == "--args" or argument.startswith("--args=")
            for argument in arguments
        ):
            return pass_through_probe(arguments)
        output = output_path()
        args_fd, args_index, invocation = locate_args_fd(arguments)
        bwrap_arguments = read_args(args_fd)
        payload_start = args_index + (2 if arguments[args_index] == "--args" else 1)
        payload = {
            "schema_version": 1,
            "kind": "pressure-vessel-bwrap-plan",
            "cwd": os.getcwd(),
            "invocation": invocation,
            "bwrap_args": bwrap_arguments,
            "payload_argv": arguments[payload_start:],
            "fd_sources": referenced_fds(bwrap_arguments),
        }
        write_private_json(output, payload)
        print(f"Captured Pressure Vessel plan without executing payload: {output}")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"capture-pressure-vessel-plan: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
