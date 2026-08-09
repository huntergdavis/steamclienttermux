#!/usr/bin/env python3
"""Print raw getdents64 types and guest-visible metadata for named entries."""

import ctypes
import os
import platform
import stat
import struct
import sys


SYSCALLS = {
    "aarch64": 61,
    "x86_64": 217,
}

TYPE_NAMES = {
    0: "DT_UNKNOWN",
    1: "DT_FIFO",
    2: "DT_CHR",
    4: "DT_DIR",
    6: "DT_BLK",
    8: "DT_REG",
    10: "DT_LNK",
    12: "DT_SOCK",
    14: "DT_WHT",
}


def raw_types(directory: str) -> dict[str, int]:
    machine = platform.machine()
    try:
        syscall_number = SYSCALLS[machine]
    except KeyError as error:
        raise SystemExit(f"unsupported architecture: {machine}") from error

    libc = ctypes.CDLL(None, use_errno=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    found: dict[str, int] = {}
    try:
        while True:
            buffer = ctypes.create_string_buffer(32768)
            size = libc.syscall(syscall_number, fd, buffer, len(buffer))
            if size < 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error), directory)
            if size == 0:
                break

            offset = 0
            data = buffer.raw
            while offset < size:
                _, _, record_size, entry_type = struct.unpack_from(
                    "=QqHB", data, offset
                )
                if record_size < 20 or offset + record_size > size:
                    raise RuntimeError(
                        f"malformed getdents64 record at offset {offset}"
                    )
                name_bytes = data[offset + 19 : offset + record_size]
                name = name_bytes.split(b"\0", 1)[0].decode(
                    errors="surrogateescape"
                )
                found[name] = entry_type
                offset += record_size
    finally:
        os.close(fd)
    return found


def mode_name(mode: int) -> str:
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFREG:
        return "regular"
    if kind == stat.S_IFLNK:
        return "symlink"
    if kind == stat.S_IFDIR:
        return "directory"
    return oct(kind)


def main() -> int:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} DIRECTORY NAME [NAME ...]", file=sys.stderr)
        return 2

    directory = os.path.abspath(sys.argv[1])
    types = raw_types(directory)
    for name in sys.argv[2:]:
        entry_type = types.get(name)
        if entry_type is None:
            print(f"{name}: missing from getdents64 output")
            continue

        path = os.path.join(directory, name)
        guest_type = mode_name(os.lstat(path).st_mode)
        try:
            target = os.readlink(path)
        except OSError as error:
            readlink_result = f"error={error.errno}:{error.strerror}"
        else:
            readlink_result = f"target={target}"

        print(
            f"{name}: d_type={entry_type}:{TYPE_NAMES.get(entry_type, 'unknown')} "
            f"lstat={guest_type} readlink={readlink_result}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
