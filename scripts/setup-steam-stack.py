#!/usr/bin/env python3
"""Prepare, inspect, or safely roll back the locked Steam ARM64 seed."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = Path(__file__).with_name("bootstrap-steam-arm64-client.py")
DOCTOR_SCRIPT = Path(__file__).with_name("steam-stack-doctor.py")
DEFAULT_LOCK = REPO_ROOT / "config/steam-arm64-bootstrap-lock.json"
DEFAULT_PACKAGE_PROFILE = REPO_ROOT / "config/termux-setup-profile.json"
STATE_DIRECTORY = ".steamclienttermux"
RECEIPT_NAME = "steam-seed-receipt.json"
TRANSACTION_NAME = "steam-seed-transaction.json"
DEPENDENCY_RECEIPT_NAME = "termux-dependencies-receipt.json"
DEPENDENCY_TRANSACTION_NAME = "termux-dependencies-transaction.json"
INSTALL_SHAPE = {
    "schema_version": 1,
    "shape_id": "two-apks-one-termux-command",
    "recommendation": "option-a-now-option-b-long-term",
    "summary": "Install Termux and Termux:X11, then run one Termux setup command.",
    "delivery": {
        "current": "signed-checksummed-release-archive",
        "long_term": "signed-termux-package-repository",
        "package_format": "deb",
        "invariant": "the archive and package invoke the same setup engine and locks",
    },
    "storage": {
        "default": "termux-private-internal",
        "removable": "optional-compatibility-profile",
    },
    "phases": [
        {
            "id": "termux-apk",
            "owner": "user-or-adb",
            "state": "manual-prerequisite",
            "action": "Install official Termux from one trusted signing source.",
        },
        {
            "id": "termux-x11-apk",
            "owner": "user-or-adb",
            "state": "manual-prerequisite",
            "action": "Install the compatible official Termux:X11 Android app.",
        },
        {
            "id": "termux-packages",
            "owner": "setup-command",
            "state": "implemented",
            "action": "Install the Termux:X11 companion and locked build/runtime dependencies.",
        },
        {
            "id": "steam-seed",
            "owner": "setup-command",
            "state": "implemented",
            "action": "Fetch, verify, receipt, and safely roll back Valve's ARM64 Steam seed.",
        },
        {
            "id": "open-source-runtime",
            "owner": "setup-command",
            "state": "partial",
            "action": "Install locked Turnip and tgcompat; glibc, PRoot, launchers, and final profiles remain.",
        },
        {
            "id": "steam-account",
            "owner": "user",
            "state": "manual-required",
            "action": "Sign in to Valve Steam and complete Steam Guard inside Valve's client.",
        },
    ],
    "out_of_scope": [
        "thin Android control-panel APK using RUN_COMMAND",
        "standalone APK that claims to control an unconfigured Termux install",
        "shared-UID add-on signed independently from the installed Termux app",
        "monolithic privately signed Termux and Termux:X11 fork",
        "ADB-assisted installation as the consumer product path",
        "archive or APK that redistributes Valve, Proton, game, or account payloads",
    ],
}
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,63}$")


class SetupError(RuntimeError):
    pass


def render_install_plan() -> str:
    lines = [
        "+----+----------------------+---------------------+--------------------------+",
        "| #  | Phase                | Owner               | State                    |",
        "+----+----------------------+---------------------+--------------------------+",
    ]
    for index, phase in enumerate(INSTALL_SHAPE["phases"], 1):
        assert isinstance(phase, dict)
        lines.append(
            f"| {index:<2} | {str(phase['id'])[:20]:<20} | "
            f"{str(phase['owner'])[:19]:<19} | {str(phase['state'])[:24]:<24} |"
        )
    lines.extend(
        [
            "+----+----------------------+---------------------+--------------------------+",
            f"INSTALL_SHAPE={INSTALL_SHAPE['shape_id']}",
            "USER_FLOW=install two Android apps, run one Termux command, sign in to Steam",
        ]
    )
    return "\n".join(lines)


def load_package_profile(path: Path) -> dict[str, object]:
    payload = read_json(path, "Termux package profile")
    if payload.get("schema_version") != 1:
        raise SetupError("unsupported Termux package profile schema")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise SetupError("Termux package profile has no ID")
    platform = payload.get("platform")
    if not isinstance(platform, dict) or platform.get("architectures") != ["aarch64"]:
        raise SetupError("Termux package profile must target aarch64")
    minimum_sdk = platform.get("minimum_android_sdk")
    if not isinstance(minimum_sdk, int) or isinstance(minimum_sdk, bool) or minimum_sdk < 26:
        raise SetupError("Termux package profile has an invalid Android SDK floor")
    groups = payload.get("install_groups")
    if not isinstance(groups, list) or [group.get("id") for group in groups if isinstance(group, dict)] != [
        "repositories",
        "build-and-runtime",
    ]:
        raise SetupError("Termux package profile has invalid install groups")
    packages: list[str] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("packages"), list):
            raise SetupError("Termux package profile contains an invalid group")
        for package in group["packages"]:
            if not isinstance(package, str) or PACKAGE_NAME.fullmatch(package) is None:
                raise SetupError(f"invalid Termux package name: {package!r}")
            if package in packages:
                raise SetupError(f"duplicate Termux package: {package}")
            packages.append(package)
    commands = payload.get("required_commands")
    if not isinstance(commands, dict) or not commands:
        raise SetupError("Termux package profile has no command map")
    for command, package in commands.items():
        if (
            not isinstance(command, str)
            or PACKAGE_NAME.fullmatch(command) is None
            or not isinstance(package, str)
            or package not in packages
        ):
            raise SetupError(f"invalid command/package mapping: {command!r}")
    tested = payload.get("tested_on")
    if not isinstance(tested, dict) or not isinstance(tested.get("versions"), dict):
        raise SetupError("Termux package profile has no tested version evidence")
    if set(tested["versions"]) != set(packages):
        raise SetupError("tested versions must cover every declared package exactly")
    return payload


def package_groups(profile: dict[str, object]) -> list[tuple[str, list[str]]]:
    groups = profile["install_groups"]
    assert isinstance(groups, list)
    result: list[tuple[str, list[str]]] = []
    for group in groups:
        assert isinstance(group, dict) and isinstance(group["id"], str)
        packages = group["packages"]
        assert isinstance(packages, list) and all(isinstance(item, str) for item in packages)
        result.append((group["id"], list(packages)))
    return result


def render_dependency_plan(profile: dict[str, object]) -> str:
    lines = [f"TERMUX_PACKAGE_PROFILE={profile['profile_id']}"]
    for group_id, packages in package_groups(profile):
        lines.append(f"# {group_id}")
        lines.append("pkg install -y " + " ".join(packages))
    platform = profile["platform"]
    assert isinstance(platform, dict)
    graphics = platform["graphics"]
    assert isinstance(graphics, dict)
    lines.append(f"GRAPHICS_PROFILE={graphics['implemented']}")
    lines.append(f"OTHER_GPU_FAMILIES={graphics['other_gpu_families']}")
    return "\n".join(lines)


def query_installed_package(package: str) -> str | None:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}\t${Version}", package],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    status_text, separator, version = result.stdout.strip().partition("\t")
    if separator != "\t" or status_text != "install ok installed" or not version:
        return None
    return version


def dependency_report(
    profile: dict[str, object], query: Any = query_installed_package
) -> dict[str, object]:
    packages = [package for _group, values in package_groups(profile) for package in values]
    installed: dict[str, str] = {}
    missing: list[str] = []
    for package in packages:
        version = query(package)
        if version is None:
            missing.append(package)
        else:
            installed[package] = version
    return {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "status": "pass" if not missing else "fail",
        "installed": installed,
        "missing": missing,
    }


def dependency_state_paths(base: Path) -> tuple[Path, Path]:
    state = base / STATE_DIRECTORY
    return state / DEPENDENCY_RECEIPT_NAME, state / DEPENDENCY_TRANSACTION_NAME


def run_package_manager(arguments: list[str]) -> int:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        check=False,
    ).returncode


def install_dependencies(
    profile: dict[str, object],
    profile_path: Path,
    base: Path,
    package_manager: Path,
    *,
    query: Any = query_installed_package,
    runner: Any = run_package_manager,
) -> str:
    base = ensure_base(base)
    profile_path = profile_path.resolve()
    profile_sha = sha256_file(profile_path)
    receipt_path, transaction_path = dependency_state_paths(base)
    packages = [package for _group, values in package_groups(profile) for package in values]

    if receipt_path.exists() or receipt_path.is_symlink():
        receipt = read_json(receipt_path, "Termux dependency receipt")
        if (
            receipt.get("schema_version") != 1
            or receipt.get("kind") != "termux-dependencies"
            or receipt.get("profile_sha256") != profile_sha
        ):
            raise SetupError("Termux dependency receipt does not match this profile")
        report = dependency_report(profile, query)
        if report["status"] != "pass":
            raise SetupError(
                "receipted Termux dependencies are missing: "
                + ", ".join(report["missing"])
            )
        return "already-ready"

    if transaction_path.exists() or transaction_path.is_symlink():
        transaction = read_json(transaction_path, "Termux dependency transaction")
        if (
            transaction.get("schema_version") != 1
            or transaction.get("kind") != "install-termux-dependencies"
            or transaction.get("profile_sha256") != profile_sha
        ):
            raise SetupError("a different Termux dependency transaction requires recovery")
        initial_missing = transaction.get("initial_missing")
        if (
            not isinstance(initial_missing, list)
            or not all(isinstance(item, str) and item in packages for item in initial_missing)
            or len(initial_missing) != len(set(initial_missing))
        ):
            raise SetupError("Termux dependency transaction is malformed")
    else:
        initial_report = dependency_report(profile, query)
        initial_missing = list(initial_report["missing"])
        atomic_json(
            transaction_path,
            {
                "schema_version": 1,
                "kind": "install-termux-dependencies",
                "profile_sha256": profile_sha,
                "initial_missing": initial_missing,
                "completed_groups": [],
            },
        )

    completed_groups: list[str] = []
    for group_id, group_packages in package_groups(profile):
        missing = [package for package in group_packages if query(package) is None]
        if missing:
            result = runner([str(package_manager), "install", "-y", *missing])
            if result != 0:
                raise SetupError(
                    f"package manager failed for group {group_id!r} with status {result}"
                )
        still_missing = [package for package in group_packages if query(package) is None]
        if still_missing:
            raise SetupError(
                f"package group {group_id!r} remains incomplete: "
                + ", ".join(still_missing)
            )
        completed_groups.append(group_id)
        atomic_json(
            transaction_path,
            {
                "schema_version": 1,
                "kind": "install-termux-dependencies",
                "profile_sha256": profile_sha,
                "initial_missing": initial_missing,
                "completed_groups": completed_groups,
            },
        )

    report = dependency_report(profile, query)
    if report["status"] != "pass":
        raise SetupError("Termux dependency installation did not converge")
    atomic_json(
        receipt_path,
        {
            "schema_version": 1,
            "kind": "termux-dependencies",
            "profile_id": profile["profile_id"],
            "profile_sha256": profile_sha,
            "installed_versions": report["installed"],
            "initially_missing": initial_missing,
            "package_count": len(packages),
            "removal_policy": "preserve shared Termux packages by default",
        },
    )
    remove_regular(transaction_path)
    return "installed" if initial_missing else "receipted-existing"


def resolve_package_manager() -> Path:
    prefix_value = os.environ.get("PREFIX", "")
    if not prefix_value:
        raise SetupError("PREFIX is unset; run dependency installation inside Termux")
    prefix = Path(prefix_value)
    if not prefix.is_absolute() or not prefix.is_dir() or prefix.is_symlink():
        raise SetupError(f"unsafe Termux PREFIX: {prefix}")
    candidate_value = shutil.which("pkg")
    if not candidate_value:
        raise SetupError("Termux package manager is unavailable: pkg")
    candidate = Path(candidate_value)
    metadata = candidate.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise SetupError(f"Termux package manager is not a regular file: {candidate}")
    if metadata.st_uid != os.getuid():
        raise SetupError(f"Termux package manager has the wrong owner: {candidate}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to((prefix / "bin").resolve())
    except ValueError as error:
        raise SetupError(f"Termux package manager is outside PREFIX/bin: {resolved}") from error
    return resolved


def load_bootstrap() -> Any:
    spec = importlib.util.spec_from_file_location("steam_seed_bootstrap", BOOTSTRAP_SCRIPT)
    if not spec or not spec.loader:
        raise SetupError(f"cannot load bootstrap engine: {BOOTSTRAP_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise SetupError(f"state directory is a symlink: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def read_json(path: Path, label: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise SetupError(f"{label} is missing or unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SetupError(f"cannot read {label}: {error}") from error
    if not isinstance(payload, dict):
        raise SetupError(f"{label} is not a JSON object")
    return payload


def ensure_base(base: Path) -> Path:
    if not base.is_absolute():
        raise SetupError("--base must be absolute")
    if base.exists():
        if not base.is_dir() or base.is_symlink():
            raise SetupError(f"base is not a safe directory: {base}")
    else:
        parent = base.parent
        if not parent.is_dir() or parent.is_symlink():
            raise SetupError(f"base parent is not a safe directory: {parent}")
        base.mkdir(mode=0o700)
        fsync_directory(parent)
    return base.resolve()


def state_paths(base: Path) -> tuple[Path, Path]:
    state = base / STATE_DIRECTORY
    return state / RECEIPT_NAME, state / TRANSACTION_NAME


def inventory_digest(root: Path) -> tuple[int, int, str]:
    if not root.is_dir() or root.is_symlink():
        raise SetupError(f"seed destination is missing or unsafe: {root}")
    records: list[dict[str, object]] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            records.append({"path": relative, "type": "directory", "mode": mode})
        elif stat.S_ISREG(metadata.st_mode):
            size = metadata.st_size
            records.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "size": size,
                    "sha256": sha256_file(path),
                }
            )
            file_count += 1
            total_bytes += size
        elif stat.S_ISLNK(metadata.st_mode):
            records.append(
                {"path": relative, "type": "symlink", "target": os.readlink(path)}
            )
        else:
            raise SetupError(f"unsupported seed entry: {path}")
    encoded = json.dumps(records, separators=(",", ":"), sort_keys=True).encode()
    return file_count, total_bytes, hashlib.sha256(encoded).hexdigest()


def build_receipt(base: Path, lock_path: Path, lock: dict[str, object], bootstrap: Any) -> dict[str, object]:
    destination = base / "client-seed"
    try:
        bootstrap.verify_seed_executable(destination, lock)
    except bootstrap.BootstrapError as error:
        raise SetupError(str(error)) from error
    file_count, total_bytes, digest = inventory_digest(destination)
    seed = lock["seed_executable"]
    assert isinstance(seed, dict)
    return {
        "schema_version": 1,
        "kind": "steam-arm64-seed",
        "build_id": lock["build_id"],
        "destination_relative": "client-seed",
        "lock_sha256": sha256_file(lock_path),
        "seed_executable_sha256": seed["sha256"],
        "inventory": {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "sha256": digest,
        },
        "redistributes_valve_binaries": False,
    }


def validate_receipt(
    base: Path,
    lock_path: Path,
    receipt: dict[str, object],
    bootstrap: Any,
    destination: Path | None = None,
) -> None:
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "steam-arm64-seed":
        raise SetupError("unsupported seed receipt")
    if receipt.get("destination_relative") != "client-seed":
        raise SetupError("seed receipt has an unexpected destination")
    if receipt.get("lock_sha256") != sha256_file(lock_path):
        raise SetupError("seed receipt does not match the current lock")
    try:
        lock = bootstrap.load_lock(lock_path)
    except bootstrap.BootstrapError as error:
        raise SetupError(str(error)) from error
    if receipt.get("build_id") != lock["build_id"]:
        raise SetupError("seed receipt build ID mismatch")
    destination = destination or base / "client-seed"
    try:
        bootstrap.verify_seed_executable(destination, lock)
    except bootstrap.BootstrapError as error:
        raise SetupError(str(error)) from error
    inventory = receipt.get("inventory")
    if not isinstance(inventory, dict):
        raise SetupError("seed receipt is missing its inventory")
    file_count, total_bytes, digest = inventory_digest(destination)
    if (
        inventory.get("file_count") != file_count
        or inventory.get("total_bytes") != total_bytes
        or inventory.get("sha256") != digest
    ):
        raise SetupError("seed tree differs from its exact receipt")


def remove_regular(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.is_symlink():
            raise SetupError(f"refusing to remove unsafe state file: {path}")
        path.unlink()
        fsync_directory(path.parent)


def finish_prepared(base: Path, lock_path: Path, bootstrap: Any) -> dict[str, object]:
    receipt_path, transaction_path = state_paths(base)
    try:
        lock = bootstrap.load_lock(lock_path)
    except bootstrap.BootstrapError as error:
        raise SetupError(str(error)) from error
    receipt = build_receipt(base, lock_path, lock, bootstrap)
    atomic_json(receipt_path, receipt)
    remove_regular(transaction_path)
    return receipt


def prepare(base: Path, lock_path: Path, archive: Path | None = None) -> str:
    base = ensure_base(base)
    bootstrap = load_bootstrap()
    lock_path = lock_path.resolve()
    try:
        lock = bootstrap.load_lock(lock_path)
    except bootstrap.BootstrapError as error:
        raise SetupError(str(error)) from error
    receipt_path, transaction_path = state_paths(base)
    destination = base / "client-seed"

    if receipt_path.exists() or receipt_path.is_symlink():
        receipt = read_json(receipt_path, "seed receipt")
        validate_receipt(base, lock_path, receipt, bootstrap)
        return "already-ready"

    if transaction_path.exists() or transaction_path.is_symlink():
        transaction = read_json(transaction_path, "seed transaction")
        if transaction.get("schema_version") != 1 or transaction.get("kind") != "prepare":
            raise SetupError("a different bootstrap transaction requires recovery")
        if transaction.get("lock_sha256") != sha256_file(lock_path):
            raise SetupError("prepared transaction uses a different lock")
        if destination.exists() or destination.is_symlink():
            finish_prepared(base, lock_path, bootstrap)
            return "recovered"
    elif destination.exists() or destination.is_symlink():
        raise SetupError("unreceipted seed destination already exists")
    else:
        atomic_json(
            transaction_path,
            {
                "schema_version": 1,
                "kind": "prepare",
                "destination_relative": "client-seed",
                "lock_sha256": sha256_file(lock_path),
            },
        )

    if archive is not None:
        try:
            bootstrap.extract_archive(archive.resolve(), destination, lock)
        except bootstrap.BootstrapError as error:
            raise SetupError(str(error)) from error
    else:
        arguments = argparse.Namespace(
            cache=base / "download-cache", destination=destination
        )
        try:
            bootstrap.command_install(arguments, lock)
        except bootstrap.BootstrapError as error:
            raise SetupError(str(error)) from error
    finish_prepared(base, lock_path, bootstrap)
    return "prepared"


def status(base: Path, lock_path: Path) -> str:
    if not base.is_absolute() or not base.is_dir() or base.is_symlink():
        return "not-prepared"
    base = base.resolve()
    receipt_path, transaction_path = state_paths(base)
    if transaction_path.exists() or transaction_path.is_symlink():
        return "recovery-required"
    if not (receipt_path.exists() or receipt_path.is_symlink()):
        return "not-prepared"
    bootstrap = load_bootstrap()
    validate_receipt(base, lock_path.resolve(), read_json(receipt_path, "seed receipt"), bootstrap)
    return "ready"


def finish_rollback(base: Path, lock_path: Path, transaction: dict[str, object]) -> Path:
    receipt_path, transaction_path = state_paths(base)
    if transaction.get("schema_version") != 1 or transaction.get("kind") != "rollback":
        raise SetupError("a different bootstrap transaction requires recovery")
    if transaction.get("lock_sha256") != sha256_file(lock_path):
        raise SetupError("rollback transaction uses a different lock")
    relative = transaction.get("quarantine_relative")
    if not isinstance(relative, str) or not relative.startswith("rollback/steam-seed-"):
        raise SetupError("rollback transaction has an unsafe quarantine path")
    quarantine = base / relative
    if not quarantine.is_dir() or quarantine.is_symlink():
        raise SetupError("rollback quarantine is missing or unsafe")
    archived_receipt = read_json(quarantine / "receipt.json", "archived seed receipt")
    if receipt_path.exists() or receipt_path.is_symlink():
        if read_json(receipt_path, "seed receipt") != archived_receipt:
            raise SetupError("active and archived seed receipts differ")
    destination = base / "client-seed"
    payload = quarantine / "payload"
    destination_present = destination.exists() or destination.is_symlink()
    payload_present = payload.exists() or payload.is_symlink()
    if destination_present == payload_present:
        raise SetupError("rollback has an ambiguous destination state")
    bootstrap = load_bootstrap()
    validate_receipt(
        base,
        lock_path,
        archived_receipt,
        bootstrap,
        destination if destination_present else payload,
    )
    if destination_present:
        os.replace(destination, payload)
        fsync_directory(quarantine)
        fsync_directory(base)
    remove_regular(receipt_path)
    remove_regular(transaction_path)
    atomic_json(
        quarantine / "ROLLBACK-COMPLETE.json",
        {"schema_version": 1, "status": "complete"},
    )
    return quarantine


def rollback(base: Path, lock_path: Path, label: str | None = None) -> Path:
    base = ensure_base(base)
    lock_path = lock_path.resolve()
    receipt_path, transaction_path = state_paths(base)
    if transaction_path.exists() or transaction_path.is_symlink():
        transaction = read_json(transaction_path, "seed transaction")
        if transaction.get("kind") == "rollback":
            return finish_rollback(base, lock_path, transaction)
        raise SetupError("bootstrap transaction requires prepare recovery before rollback")
    receipt = read_json(receipt_path, "seed receipt")
    bootstrap = load_bootstrap()
    validate_receipt(base, lock_path, receipt, bootstrap)
    safe_label = label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not safe_label.replace("-", "").replace("_", "").isalnum():
        raise SetupError("rollback label must contain only letters, numbers, '-' or '_'")
    rollback_root = base / "rollback"
    rollback_root.mkdir(mode=0o700, exist_ok=True)
    if rollback_root.is_symlink():
        raise SetupError("rollback directory is a symlink")
    quarantine = rollback_root / f"steam-seed-{safe_label}"
    if quarantine.exists() or quarantine.is_symlink():
        raise SetupError(f"rollback destination already exists: {quarantine}")
    quarantine.mkdir(mode=0o700)
    atomic_json(quarantine / "receipt.json", receipt)
    atomic_json(
        transaction_path,
        {
            "schema_version": 1,
            "kind": "rollback",
            "destination_relative": "client-seed",
            "quarantine_relative": quarantine.relative_to(base).as_posix(),
            "lock_sha256": sha256_file(lock_path),
        },
    )
    return finish_rollback(base, lock_path, read_json(transaction_path, "seed transaction"))


def run_doctor(base: Path, minimum_free_bytes: int) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(DOCTOR_SCRIPT),
            "--mode",
            "bootstrap",
            "--base",
            str(base),
            "--min-free-bytes",
            str(minimum_free_bytes),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise SetupError("bootstrap doctor failed; fix the reported prerequisites")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--package-profile", type=Path, default=DEFAULT_PACKAGE_PROFILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_base = Path(os.environ.get("HOME", "")) / "steam-arm64"
    plan_parser = subparsers.add_parser(
        "plan", help="show the authoritative manual and automated setup boundary"
    )
    plan_parser.add_argument("--json", action="store_true", dest="as_json")
    dependencies_parser = subparsers.add_parser(
        "dependencies", help="show or check the locked Termux package set"
    )
    dependencies_parser.add_argument("--json", action="store_true", dest="as_json")
    dependencies_parser.add_argument("--check", action="store_true")
    dependencies_parser.add_argument("--install", action="store_true")
    dependencies_parser.add_argument("--yes", action="store_true")
    dependencies_parser.add_argument("--base", type=Path, default=default_base)
    prepare_parser = subparsers.add_parser("prepare", help="doctor, acquire, verify, and receipt the Steam seed")
    prepare_parser.add_argument("--base", type=Path, default=default_base)
    prepare_parser.add_argument("--archive", type=Path)
    prepare_parser.add_argument("--min-free-bytes", type=int, default=4 * 1024**3)
    status_parser = subparsers.add_parser("status", help="verify the prepared seed without changing it")
    status_parser.add_argument("--base", type=Path, default=default_base)
    rollback_parser = subparsers.add_parser("rollback", help="quarantine the exact receipted seed")
    rollback_parser.add_argument("--base", type=Path, default=default_base)
    rollback_parser.add_argument("--label")
    arguments = parser.parse_args()
    try:
        if arguments.command == "plan":
            if arguments.as_json:
                print(json.dumps(INSTALL_SHAPE, indent=2, sort_keys=True))
            else:
                print(render_install_plan())
        elif arguments.command == "dependencies":
            profile = load_package_profile(arguments.package_profile.resolve())
            if arguments.install:
                if arguments.check or arguments.as_json:
                    raise SetupError("--install cannot be combined with --check or --json")
                if not arguments.yes:
                    raise SetupError("--install requires explicit --yes confirmation")
                result = install_dependencies(
                    profile,
                    arguments.package_profile,
                    arguments.base,
                    resolve_package_manager(),
                )
                print(f"TERMUX_DEPENDENCIES={result}")
                return 0
            elif arguments.yes:
                raise SetupError("--yes is only valid with --install")
            elif arguments.check:
                report = dependency_report(profile)
                if arguments.as_json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    print(f"TERMUX_DEPENDENCIES={report['status']}")
                    print("MISSING=" + ",".join(report["missing"]))
                return 0 if report["status"] == "pass" else 1
            if arguments.as_json:
                print(json.dumps(profile, indent=2, sort_keys=True))
            else:
                print(render_dependency_plan(profile))
        elif arguments.command == "prepare":
            run_doctor(arguments.base.resolve(), arguments.min_free_bytes)
            result = prepare(arguments.base, arguments.lock, arguments.archive)
            print(f"STEAM_STACK_PREPARE={result}")
            print(f"STEAM_SEED={arguments.base.resolve() / 'client-seed'}")
        elif arguments.command == "status":
            result = status(arguments.base, arguments.lock)
            print(f"STEAM_STACK_STATUS={result}")
            return 0 if result == "ready" else 1
        else:
            quarantine = rollback(arguments.base, arguments.lock, arguments.label)
            print(f"STEAM_STACK_ROLLBACK=complete")
            print(f"STEAM_SEED_QUARANTINE={quarantine}")
    except (SetupError, OSError) as error:
        print(f"setup-steam-stack: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
