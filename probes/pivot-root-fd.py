#!/usr/bin/env python3
"""Exercise Bubblewrap's detached-old-root file-descriptor sequence."""

import ctypes
import errno
import os
import sys


SYS_UMOUNT2_AARCH64 = 39
SYS_PIVOT_ROOT_AARCH64 = 41
MNT_DETACH = 2


def checked_syscall(libc: ctypes.CDLL, number: int, *args: object) -> None:
    result = libc.syscall(number, *args)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error or errno.EIO, os.strerror(error or errno.EIO))


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} NEW_ROOT EXPECTED_CHILD", file=sys.stderr)
        return 2

    new_root = os.path.abspath(sys.argv[1])
    expected_child = sys.argv[2]
    libc = ctypes.CDLL(None, use_errno=True)
    old_root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)

    os.chdir(new_root)
    checked_syscall(libc, SYS_PIVOT_ROOT_AARCH64, b".", b".")
    os.fchdir(old_root_fd)
    checked_syscall(libc, SYS_UMOUNT2_AARCH64, b".", MNT_DETACH)
    os.chdir("/")

    if os.getcwd() != "/":
        raise AssertionError(f"unexpected cwd after pivot: {os.getcwd()!r}")
    if not os.path.exists(os.path.join("/", expected_child)):
        raise AssertionError(f"new root does not expose {expected_child!r}")

    print("pivot-root-fd: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
