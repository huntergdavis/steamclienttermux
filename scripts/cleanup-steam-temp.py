#!/usr/bin/env python3

"""Remove closed, aged Steam shared-memory files from Termux tmp."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import time


def scan_open_inodes(proc_root, uid):
    opened = set()
    errors = []
    for process in proc_root.glob("[0-9]*"):
        try:
            if process.stat().st_uid != uid:
                continue
            descriptors = list((process / "fd").iterdir())
        except FileNotFoundError:
            continue
        except (OSError, PermissionError) as error:
            if process.exists():
                errors.append(f"{process}: {error}")
            continue
        for descriptor in descriptors:
            try:
                details = descriptor.stat()
            except (FileNotFoundError, OSError, PermissionError):
                continue
            opened.add((details.st_dev, details.st_ino))
    return opened, errors


def eligible_files(tmp_root, uid, minimum_age, now):
    pattern = re.compile(rf"u{uid}-Shm_[0-9a-f]+")
    eligible = []
    skipped = []
    for candidate in tmp_root.iterdir():
        if pattern.fullmatch(candidate.name) is None:
            continue
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        reason = None
        if not stat.S_ISREG(details.st_mode):
            reason = "not_regular"
        elif details.st_uid != uid:
            reason = "wrong_owner"
        elif details.st_nlink != 1:
            reason = "multiple_links"
        elif stat.S_IMODE(details.st_mode) != 0o700:
            reason = "wrong_mode"
        elif details.st_size > 1024 * 1024 * 1024:
            reason = "oversized"
        elif now - details.st_mtime < minimum_age:
            reason = "too_new"
        if reason is None:
            eligible.append((candidate, details))
        else:
            skipped.append((candidate, reason, details.st_size))
    return eligible, skipped


def clean(arguments):
    uid = os.getuid()
    prefix = arguments.prefix
    tmp_root = prefix / "tmp"
    prefix_details = prefix.lstat()
    tmp_details = tmp_root.lstat()
    if not stat.S_ISDIR(prefix_details.st_mode) or prefix.is_symlink():
        raise RuntimeError(f"prefix is not a real directory: {prefix}")
    if not stat.S_ISDIR(tmp_details.st_mode) or tmp_root.is_symlink():
        raise RuntimeError(f"tmp root is not a real directory: {tmp_root}")
    if prefix_details.st_uid != uid or tmp_details.st_uid != uid:
        raise RuntimeError("prefix and tmp root must be owned by the current UID")

    now = time.time() if arguments.now is None else arguments.now
    eligible, skipped = eligible_files(tmp_root, uid, arguments.minimum_age, now)
    opened, errors = scan_open_inodes(arguments.proc_root, uid)
    if errors and arguments.apply:
        raise RuntimeError(
            "cannot prove all same-UID descriptors were scanned: " + "; ".join(errors)
        )

    removed = []
    open_files = []
    for candidate, original in eligible:
        key = (original.st_dev, original.st_ino)
        if key in opened:
            open_files.append((candidate, original.st_size))
            continue
        if not arguments.apply:
            removed.append((candidate, original.st_size))
            continue
        try:
            current = candidate.lstat()
        except FileNotFoundError:
            continue
        if (
            current.st_dev != original.st_dev
            or current.st_ino != original.st_ino
            or current.st_uid != uid
            or current.st_nlink != 1
            or stat.S_IMODE(current.st_mode) != 0o700
            or not stat.S_ISREG(current.st_mode)
            or now - current.st_mtime < arguments.minimum_age
        ):
            raise RuntimeError(f"candidate changed during validation: {candidate}")
        os.unlink(candidate)
        removed.append((candidate, current.st_size))

    return {
        "mode": "apply" if arguments.apply else "dry_run",
        "tmp_root": str(tmp_root),
        "minimum_age_seconds": arguments.minimum_age,
        "eligible_closed_count": len(removed),
        "eligible_closed_bytes": sum(size for _path, size in removed),
        "open_count": len(open_files),
        "open_bytes": sum(size for _path, size in open_files),
        "skipped_count": len(skipped),
        "descriptor_scan_errors": errors,
        "paths": [str(path) for path, _size in removed],
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Remove only closed, aged, exact-name Steam shared-memory files "
            "from PREFIX/tmp. The default is a non-mutating dry run."
        )
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--minimum-age", type=int, default=3600)
    parser.add_argument(
        "--prefix",
        type=Path,
        default=Path(os.environ.get("PREFIX", "/invalid/missing-prefix")),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"), help=argparse.SUPPRESS)
    parser.add_argument("--now", type=float, help=argparse.SUPPRESS)
    return parser


def main():
    parser = build_parser()
    arguments = parser.parse_args()
    if not 60 <= arguments.minimum_age <= 30 * 24 * 60 * 60:
        parser.error("--minimum-age must be between 60 seconds and 30 days")
    try:
        report = clean(arguments)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"cleanup-steam-temp: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
