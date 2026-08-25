#!/usr/bin/env python3
"""Read-only prerequisite checks for the Steam ARM64 Termux stack."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SOURCE = (
    "config/steam-arm64-bootstrap-lock.json",
    "config/glibc-runtime-lock.json",
    "config/tgcompat-runtime-lock.json",
    "config/termux-setup-profile.json",
    "config/turnip-runtime-lock.json",
    "scripts/bootstrap-termux-stack.sh",
    "scripts/bootstrap-steam-arm64-client.py",
    "scripts/build-release-archive.py",
    "scripts/install-tgcompat-runtime.py",
    "scripts/install-glibc-runtime.py",
    "scripts/install-turnip-runtime.py",
    "scripts/steam-stack-doctor.py",
    "artifacts/glibc_2.44_aarch64.deb",
)
REQUIRED_TOOLS = ("bash", "python3", "git", "clang", "cmake", "pkg-config")
DEFAULT_MIN_FREE_BYTES = 4 * 1024**3


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def command_output(arguments: Sequence[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, result.stdout.strip()


def safe_directory(name: str, path: Path) -> Check:
    if not path.is_absolute():
        return Check(name, "fail", f"not absolute: {path}", "use an absolute path")
    if path.is_symlink() or not path.is_dir():
        return Check(name, "fail", f"missing or unsafe: {path}", "create a real private directory")
    return Check(name, "pass", str(path))


def collect_checks(
    mode: str,
    base: Path,
    prefix: Path,
    home: Path,
    min_free_bytes: int,
    *,
    repo_root: Path = REPO_ROOT,
    machine: Callable[[], str] = platform.machine,
    lookup: Callable[[str], str | None] = shutil.which,
    run: Callable[[Sequence[str]], tuple[int, str]] = command_output,
    disk_usage: Callable[[Path], object] = shutil.disk_usage,
) -> list[Check]:
    checks: list[Check] = []

    architecture = machine().lower()
    checks.append(
        Check(
            "architecture",
            "pass" if architecture in ("aarch64", "arm64") else "fail",
            architecture,
            "use an AArch64 Android device",
        )
    )
    abi_status, abi = run(("getprop", "ro.product.cpu.abi"))
    checks.append(
        Check(
            "android ABI",
            "pass" if abi_status == 0 and abi == "arm64-v8a" else "fail",
            abi or "unavailable",
            "install on an arm64-v8a Android device",
        )
    )
    checks.extend((safe_directory("Termux PREFIX", prefix), safe_directory("Termux HOME", home)))
    try:
        base.relative_to(home)
        private_storage = True
    except ValueError:
        private_storage = False
    checks.append(
        Check(
            "storage profile",
            "pass" if private_storage else "warn",
            "Termux private/internal" if private_storage else f"custom: {base}",
            "use the default private/internal base unless removable storage is required",
        )
    )

    for package, label in (("com.termux", "Termux package"), ("com.termux.x11", "Termux:X11 package")):
        status, output = run(("pm", "path", package))
        present = status == 0 and any(line.startswith("package:/") for line in output.splitlines())
        checks.append(
            Check(
                label,
                "pass" if present else "fail",
                "installed" if present else "not found",
                "install Termux and matching Termux:X11 from one trusted source",
            )
        )

    missing_tools = [tool for tool in REQUIRED_TOOLS if lookup(tool) is None]
    checks.append(
        Check(
            "build tools",
            "pass" if not missing_tools else "fail",
            "all present" if not missing_tools else f"missing: {', '.join(missing_tools)}",
            "install the missing packages with pkg",
        )
    )
    backends = [tool for tool in ("make", "ninja") if lookup(tool) is not None]
    checks.append(
        Check(
            "build backend",
            "pass" if backends else "fail",
            ", ".join(backends) if backends else "missing: make or ninja",
            "install make or ninja with pkg",
        )
    )

    free_bytes = int(getattr(disk_usage(home), "free"))
    checks.append(
        Check(
            "free storage",
            "pass" if free_bytes >= min_free_bytes else "fail",
            f"{free_bytes / 1024**3:.2f} GiB free; {min_free_bytes / 1024**3:.2f} GiB required",
            "free private/internal storage before bootstrap",
        )
    )

    missing_source = [path for path in REQUIRED_SOURCE if not (repo_root / path).is_file()]
    checks.append(
        Check(
            "release source",
            "pass" if not missing_source else "fail",
            "complete" if not missing_source else f"missing: {', '.join(missing_source)}",
            "extract a complete verified release archive",
        )
    )

    license_present = any((repo_root / name).is_file() for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"))
    checks.append(
        Check(
            "project license",
            "pass" if license_present else "warn",
            "tracked" if license_present else "missing; local research only",
            "project owner must choose a license before public release",
        )
    )

    if mode == "runtime":
        runtime_files = (
            ("Steam client", base / "client/steamrtarm64/steam", True),
            ("Turnip manifest", base / "mesa-kgsl/icd.d/freedreno-private.json", False),
            ("PulseAudio helper", base / "prepare-pulseaudio-tcp.sh", True),
            ("native launcher", home / "start-steam-native.sh", True),
        )
        for name, path, executable in runtime_files:
            valid = path.is_file() and not path.is_symlink()
            if executable:
                valid = valid and os.access(path, os.X_OK)
            checks.append(
                Check(
                    name,
                    "pass" if valid else "fail",
                    str(path),
                    "run the transactional stack installer",
                )
            )
        glibc = home / ".local/share/tgcompat/glibc/current"
        try:
            glibc_root = glibc.resolve(strict=True)
        except OSError:
            glibc_root = None
        valid_glibc = bool(
            glibc_root
            and (glibc_root / "lib/ld-linux-aarch64.so.1").is_file()
            and (glibc_root / ".tgcompat-package-sha256").is_file()
        )
        checks.append(
            Check(
                "native glibc",
                "pass" if valid_glibc else "fail",
                str(glibc_root or glibc),
                "build and promote the locked glibc compatibility package",
            )
        )
        tgcompat = base / "tgcompat/current"
        try:
            tgcompat_root = tgcompat.resolve(strict=True)
        except OSError:
            tgcompat_root = None
        tgcompat_files = (
            "build/tgcompatd",
            "build/libtgcompat-exec.so",
            "build/libtgcompat-robust.so",
            ".steamclienttermux-tgcompat-receipt.json",
        )
        valid_tgcompat = bool(
            tgcompat_root
            and all(
                (tgcompat_root / relative).is_file()
                and not (tgcompat_root / relative).is_symlink()
                for relative in tgcompat_files
            )
        )
        checks.append(
            Check(
                "native tgcompat",
                "pass" if valid_tgcompat else "fail",
                str(tgcompat_root or tgcompat),
                "run the locked tgcompat runtime installer",
            )
        )

    return checks


def render_table(checks: Sequence[Check]) -> str:
    lines = [
        "+----------------------+--------+------------------------------------------+",
        "| Check                | Status | Detail                                   |",
        "+----------------------+--------+------------------------------------------+",
    ]
    for check in checks:
        detail = check.detail if len(check.detail) <= 40 else check.detail[:37] + "..."
        lines.append(f"| {check.name[:20]:<20} | {check.status.upper():<6} | {detail:<40} |")
    lines.append("+----------------------+--------+------------------------------------------+")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bootstrap", "runtime"), default="bootstrap")
    parser.add_argument("--base", type=Path, default=None)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args()
    if arguments.min_free_bytes < 1024**3:
        parser.error("--min-free-bytes must be at least 1 GiB")
    home = Path(os.environ.get("HOME", ""))
    prefix = Path(os.environ.get("PREFIX", ""))
    base = arguments.base or home / "steam-arm64"
    checks = collect_checks(arguments.mode, base, prefix, home, arguments.min_free_bytes)
    failed = sum(check.status == "fail" for check in checks)
    warned = sum(check.status == "warn" for check in checks)
    result = {
        "schema_version": 1,
        "mode": arguments.mode,
        "status": "fail" if failed else "pass",
        "failed": failed,
        "warned": warned,
        "checks": [asdict(check) for check in checks],
    }
    if arguments.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_table(checks))
        print(f"DOCTOR_STATUS={result['status']} FAILED={failed} WARNED={warned}")
        for check in checks:
            if check.status != "pass" and check.fix:
                print(f"FIX {check.name}: {check.fix}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
