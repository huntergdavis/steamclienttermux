#!/usr/bin/env python3

"""Bound Steam launcher output and prepare its high-risk log paths safely."""

import argparse
import datetime
import errno
import fcntl
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


MINIMUM_CAP_BYTES = 256
READ_SIZE = 64 * 1024
NOISY_LOG_RELATIVE_PATHS = (
    Path("logs/steamwebhelper.log"),
    Path("config/htmlcache/chrome_debug.log"),
)


def nonnegative_integer(value):
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a base-10 integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def cap_integer(value):
    parsed = nonnegative_integer(value)
    if parsed < MINIMUM_CAP_BYTES:
        raise argparse.ArgumentTypeError(
            f"must be at least {MINIMUM_CAP_BYTES} bytes"
        )
    return parsed


def crash_mode(value):
    if value in ("", "0"):
        return "disabled"
    if value == "1":
        return "enabled"
    raise ValueError("PROOT_CRASH_LOG must be unset, 0, or 1")


def exact_dev_null_symlink(path):
    try:
        return stat.S_ISLNK(path.lstat().st_mode) and os.readlink(path) == "/dev/null"
    except FileNotFoundError:
        return False


def describe_path(path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return f"symlink to {os.readlink(path)!r}"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    return "unsupported file type"


def install_dev_null_symlink(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.steam-arm64-{os.getpid()}"
    try:
        os.symlink("/dev/null", temporary)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    if not exact_dev_null_symlink(path):
        raise RuntimeError(f"failed to install exact /dev/null symlink: {path}")


def prepare_noisy_logs(client_root, steam_running):
    paths = [client_root / relative for relative in NOISY_LOG_RELATIVE_PATHS]

    # Inspect the complete set before changing anything. In particular, a
    # forwarded steam:// invocation must not unlink a file held by live CEF.
    states = [(path, describe_path(path)) for path in paths]
    incorrect = [
        (path, description)
        for path, description in states
        if not exact_dev_null_symlink(path)
    ]
    if steam_running and incorrect:
        details = ", ".join(f"{path} ({description})" for path, description in incorrect)
        raise RuntimeError(
            "Steam is already running; refusing to replace active CEF log path(s): "
            + details
        )

    for path, description in states:
        if exact_dev_null_symlink(path):
            continue
        if description not in ("missing", "regular file"):
            raise RuntimeError(
                f"refusing to replace unexpected CEF log path: {path} ({description})"
            )

    for path, _description in states:
        if not exact_dev_null_symlink(path):
            install_dev_null_symlink(path)


def ensure_free_space(logs_dir, minimum_free_bytes, log_cap_bytes, available=None):
    required = minimum_free_bytes + log_cap_bytes
    if available is None:
        available = shutil.disk_usage(logs_dir).free
    if available < required:
        raise RuntimeError(
            f"insufficient free space at {logs_dir}: {available} bytes available, "
            f"{required} required ({minimum_free_bytes} byte floor plus "
            f"{log_cap_bytes} byte session-log budget)"
        )


def preflight(args):
    logs_dir = Path(args.logs_dir)
    client_root = Path(args.client_root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    ensure_free_space(logs_dir, args.min_free_bytes, args.log_cap_bytes)
    prepare_noisy_logs(client_root, args.steam_running == "yes")


def create_log(logs_dir):
    logs_dir = Path(logs_dir)
    prefix = datetime.datetime.now().strftime("steam-%Y%m%d-%H%M%S-")
    descriptor, path = tempfile.mkstemp(prefix=prefix, suffix=".log", dir=logs_dir)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return path


def write_all(descriptor, data):
    offset = 0
    while offset < len(data):
        try:
            written = os.write(descriptor, data[offset:])
        except InterruptedError:
            continue
        if written == 0:
            raise OSError(errno.EIO, "zero-byte write")
        offset += written


def safe_diagnostic(message):
    try:
        write_all(2, (message + "\n").encode("utf-8", "replace"))
    except OSError:
        pass


class CappedSink:
    def __init__(self, descriptor, cap_bytes, label, close_descriptor=False):
        self.descriptor = descriptor
        self.cap_bytes = cap_bytes
        self.label = label
        self.close_descriptor = close_descriptor
        self.marker = (
            f"\n[steam-arm64 logger: {label} truncated at {cap_bytes} bytes; "
            "remaining child output drained]\n"
        ).encode()
        if len(self.marker) >= cap_bytes:
            raise ValueError(f"{label} cap is too small for its truncation marker")
        self.payload_limit = cap_bytes - len(self.marker)
        self.payload_written = 0
        self.truncated = False
        self.failed = False

    def _write(self, data):
        if self.failed or not data:
            return
        try:
            write_all(self.descriptor, data)
        except OSError as error:
            self.failed = True
            safe_diagnostic(
                f"steam-arm64 logger: disabling {self.label} after write error: {error}"
            )

    def feed(self, data):
        if self.failed or self.truncated or not data:
            return
        remaining = self.payload_limit - self.payload_written
        prefix = data[:remaining]
        self._write(prefix)
        if self.failed:
            return
        self.payload_written += len(prefix)
        if len(data) > len(prefix):
            self._write(self.marker)
            if not self.failed:
                self.truncated = True

    def close(self):
        if self.close_descriptor:
            try:
                os.close(self.descriptor)
            except OSError:
                pass


def open_canonical_log(path):
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    if descriptor <= 2:
        replacement = fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 3)
        os.close(descriptor)
        descriptor = replacement
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise RuntimeError("canonical session log is not a singly linked regular file")
    return descriptor


def stream_output(log_path, log_cap_bytes, stdout_cap_bytes):
    try:
        log_descriptor = open_canonical_log(log_path)
    except (OSError, RuntimeError) as error:
        log_descriptor = None
        safe_diagnostic(f"steam-arm64 logger: canonical log unavailable: {error}")

    sinks = [CappedSink(1, stdout_cap_bytes, "mirrored stdout")]
    if log_descriptor is not None:
        sinks.append(
            CappedSink(
                log_descriptor,
                log_cap_bytes,
                "canonical log",
                close_descriptor=True,
            )
        )
    try:
        while True:
            try:
                data = os.read(0, READ_SIZE)
            except InterruptedError:
                continue
            if not data:
                break
            for sink in sinks:
                sink.feed(data)
    finally:
        for sink in sinks:
            sink.close()


def build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    crash = commands.add_parser("crash-mode")
    crash.add_argument("value")

    prepare = commands.add_parser("preflight")
    prepare.add_argument("--client-root", required=True)
    prepare.add_argument("--logs-dir", required=True)
    prepare.add_argument("--min-free-bytes", required=True, type=nonnegative_integer)
    prepare.add_argument("--log-cap-bytes", required=True, type=cap_integer)
    prepare.add_argument("--stdout-cap-bytes", required=True, type=cap_integer)
    prepare.add_argument("--steam-running", required=True, choices=("yes", "no"))

    create = commands.add_parser("create-log")
    create.add_argument("--logs-dir", required=True)

    stream = commands.add_parser("stream")
    stream.add_argument("--log", required=True)
    stream.add_argument("--log-cap-bytes", required=True, type=cap_integer)
    stream.add_argument("--stdout-cap-bytes", required=True, type=cap_integer)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        if args.command == "crash-mode":
            print(crash_mode(args.value))
        elif args.command == "preflight":
            preflight(args)
        elif args.command == "create-log":
            print(create_log(args.logs_dir))
        elif args.command == "stream":
            stream_output(args.log, args.log_cap_bytes, args.stdout_cap_bytes)
        else:
            raise AssertionError(f"unhandled command: {args.command}")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"steam-arm64 session guard: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
