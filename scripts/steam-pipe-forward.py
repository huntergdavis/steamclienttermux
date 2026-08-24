#!/usr/bin/env python3
"""Write one bounded, authenticated argv packet to Steam's singleton FIFO."""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import shlex
import stat


EX_UNAVAILABLE = 75


def fail(message: str) -> None:
    raise SystemExit(f"steam-pipe-forward: {message}")


def validate_directory(path: Path, expected_uid: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"private Steam directory is unavailable: {error}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        fail(f"private Steam directory failed validation: {path}")


def validate_fifo(path: Path, expected_uid: int) -> os.stat_result:
    validate_directory(path.parent, expected_uid)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise SystemExit(EX_UNAVAILABLE)
    except OSError as error:
        fail(f"Steam FIFO is unavailable: {error}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISFIFO(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        fail(f"Steam FIFO failed validation: {path}")
    return metadata


def send(path: Path, argv: list[str], expected_uid: int) -> int:
    if not path.is_absolute() or not argv:
        fail("an absolute FIFO and at least one argument are required")
    if any("\0" in argument or "\n" in argument or "\r" in argument for argument in argv):
        fail("arguments may not contain NUL or line separators")

    expected = validate_fifo(path, expected_uid)
    payload = (shlex.join(argv) + "\n").encode("utf-8")
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        )
    except OSError as error:
        if error.errno in (errno.ENXIO, errno.ENOENT):
            return EX_UNAVAILABLE
        fail(f"could not open Steam FIFO: {error}")
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISFIFO(opened.st_mode)
            or opened.st_dev != expected.st_dev
            or opened.st_ino != expected.st_ino
            or opened.st_uid != expected_uid
        ):
            fail("Steam FIFO identity changed while opening it")
        pipe_buf = os.fpathconf(descriptor, "PC_PIPE_BUF")
        if len(payload) > pipe_buf:
            fail(f"Steam request exceeds atomic FIFO capacity: {len(payload)}>{pipe_buf}")
        written = os.write(descriptor, payload)
        if written != len(payload):
            fail(f"short Steam FIFO write: {written}/{len(payload)}")
    finally:
        os.close(descriptor)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", type=Path, required=True)
    parser.add_argument("--expected-uid", type=int, required=True)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    forwarded = arguments.argv
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if arguments.expected_uid < 0:
        parser.error("--expected-uid must be nonnegative")
    return send(arguments.pipe, forwarded, arguments.expected_uid)


if __name__ == "__main__":
    raise SystemExit(main())
