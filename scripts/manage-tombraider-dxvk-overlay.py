#!/usr/bin/env python3
"""Activate or recover a reversible Tomb Raider-local DXVK overlay."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time


VARIANTS = {
    "dxvk-1.10.3-x32": (
        "tombraider-dxvk-1.10.3-x32-8d1a3c91",
        "x32",
        {
            "d3d10core.dll": (
                1114126,
                "83d3e6155c04f31aaaef92303e89f5065db0fee56ea0f09f6c433302b30da959",
            ),
            "d3d11.dll": (
                3526670,
                "da35effaadeb4d09455a315de7352320d5445aca386c0d8e0a1094a48d585246",
            ),
            "d3d9.dll": (
                3305486,
                "b6cfa2cd62af73b80d461085d126004b0e22dd3944c9246c58e3a68e747b56b6",
            ),
            "dxgi.dll": (
                2338830,
                "7674136f2e894cf5a2fbb24ff283215301c591e08b6fc787aff27654afe34c49",
            ),
        },
    ),
    "dxvk-2.4.1-x32": (
        "tombraider-dxvk-2.4.1-x32-7b23db4e",
        "x32",
        {
            "d3d10core.dll": (
                196622,
                "e7a4d2b8d32124b3768e0c958fdcda4dcf97fcdd2b983917689c321d4e3c162c",
            ),
            "d3d11.dll": (
                4517902,
                "0b560b0d24b14ac2ee3dbc05a12d480eed341a575d713647305d7a040f33abb9",
            ),
            "d3d9.dll": (
                4124686,
                "cc556331fc3388989749620bceead4c2da95c3932ed38cf5cc24f3f0a878866e",
            ),
            "dxgi.dll": (
                2998286,
                "4b5d6275d5987de5e64f6ce42f5f7b888fb75bd414326d2ecc792effd9a385da",
            ),
        },
    ),
}


class OverlayError(RuntimeError):
    pass


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def private_directory(path: Path, label: str, *, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise OverlayError(f"{label} is unsafe: {path}")
    return path


def regular(
    path: Path,
    label: str,
    size: int,
    sha256: str,
    *,
    expected_uid: int | None = None,
) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OverlayError(f"{label} is unavailable: {path}: {error}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != (
            os.geteuid() if expected_uid is None else expected_uid
        )
        or metadata.st_size != size
        or digest(path) != sha256
    ):
        raise OverlayError(f"{label} failed identity validation: {path}")


def atomic_json(path: Path, document: dict) -> None:
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_text)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_state(path: Path) -> dict:
    try:
        metadata = path.lstat()
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError(f"DXVK overlay state is unavailable: {error}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
        or not isinstance(document, dict)
        or document.get("schema") != 1
        or document.get("variant") not in VARIANTS
        or document.get("status") not in ("activating", "active")
        or not isinstance(document.get("run_id"), str)
        or not document["run_id"].startswith("overlay-")
    ):
        raise OverlayError("DXVK overlay state failed validation")
    return document


def copy_exclusive(source: Path, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with source.open("rb") as input_stream, os.fdopen(
            descriptor, "wb", closefd=False
        ) as output:
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(descriptor)


def paths(base: Path) -> tuple[Path, Path, Path]:
    game = base / "removable-library/steamapps/common/Tomb Raider"
    runtime = base / "run/tombraider-dxvk-overlay"
    return game, runtime, runtime / "active.json"


def variant_payload(base: Path, variant: str) -> tuple[Path, dict[str, tuple[int, str]]]:
    try:
        candidate_name, architecture, files = VARIANTS[variant]
    except KeyError as error:
        raise OverlayError(f"unsupported DXVK overlay variant: {variant}") from error
    return base / "candidates" / candidate_name / architecture, files


def restore(base: Path, *, require_state: bool) -> Path | None:
    game, runtime, state_path = paths(base)
    if not state_path.exists() and not state_path.is_symlink():
        if require_state:
            raise OverlayError("no active Tomb Raider DXVK overlay exists")
        return None
    document = read_state(state_path)
    candidate, files = variant_payload(base, document["variant"])
    expected_file_records = [
        {"name": name, "size_bytes": size, "sha256": sha256}
        for name, (size, sha256) in files.items()
    ]
    if (
        document.get("candidate") != str(candidate)
        or document.get("game") != str(game)
        or document.get("files") != expected_file_records
    ):
        raise OverlayError("DXVK overlay state payload failed validation")
    game_metadata = game.lstat()
    if not stat.S_ISDIR(game_metadata.st_mode) or game.is_symlink():
        raise OverlayError(f"Tomb Raider game directory is unsafe: {game}")
    active_files: list[tuple[str, Path]] = []
    for name, (size, sha256) in files.items():
        active = game / name
        if not active.exists() and not active.is_symlink():
            if document["status"] == "activating":
                continue
            raise OverlayError(f"active DXVK overlay file disappeared: {active}")
        regular(
            active,
            "active DXVK overlay",
            size,
            sha256,
            expected_uid=game_metadata.st_uid,
        )
        active_files.append((name, active))
    evidence_root = game / ".steamclienttermux-dxvk-overlays"
    evidence_root.mkdir(mode=0o700, exist_ok=True)
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise OverlayError(f"DXVK overlay evidence root is unsafe: {evidence_root}")
    evidence = evidence_root / document["run_id"]
    if evidence.exists() or evidence.is_symlink():
        raise OverlayError(f"DXVK overlay evidence already exists: {evidence}")
    evidence.mkdir(mode=0o700)
    moved = []
    try:
        for name, active in active_files:
            destination = evidence / name
            os.replace(active, destination)
            moved.append(name)
        atomic_json(evidence / "manifest.json", {**document, "status": "restored"})
        sync_directory(evidence)
        sync_directory(game)
        state_path.unlink()
        sync_directory(runtime)
    except BaseException:
        # Never silently remove evidence or overwrite a destination. Exact
        # moved files remain recoverable in the run-specific evidence folder.
        raise
    print(
        f"DXVK_OVERLAY_RESTORED={evidence} files={len(moved)}",
        flush=True,
    )
    return evidence


def activate(base: Path, variant: str) -> None:
    game, runtime, state_path = paths(base)
    candidate, files = variant_payload(base, variant)
    private_directory(candidate, "DXVK candidate")
    game_metadata = game.lstat()
    if not stat.S_ISDIR(game_metadata.st_mode) or game.is_symlink():
        raise OverlayError(f"Tomb Raider game directory is unsafe: {game}")
    private_directory(runtime, "DXVK overlay runtime", create=True)
    if state_path.exists() or state_path.is_symlink():
        restore(base, require_state=True)
    for name, (size, sha256) in files.items():
        regular(candidate / name, "DXVK candidate file", size, sha256)
        active = game / name
        if active.exists() or active.is_symlink():
            raise OverlayError(f"Tomb Raider already has an app-local DLL: {active}")

    run_id = "overlay-" + dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    ) + f"-{os.getpid()}-{time.time_ns()}"
    state = {
        "schema": 1,
        "status": "activating",
        "variant": variant,
        "run_id": run_id,
        "candidate": str(candidate),
        "game": str(game),
        "files": [
            {"name": name, "size_bytes": size, "sha256": sha256}
            for name, (size, sha256) in files.items()
        ],
    }
    atomic_json(state_path, state)
    try:
        for name, (size, sha256) in files.items():
            active = game / name
            copy_exclusive(candidate / name, active)
            regular(
                active,
                "active DXVK overlay",
                size,
                sha256,
                expected_uid=game_metadata.st_uid,
            )
        sync_directory(game)
        state["status"] = "active"
        atomic_json(state_path, state)
    except BaseException:
        restore(base, require_state=True)
        raise
    print(f"DXVK_OVERLAY_ACTIVE={game} variant={variant}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "restore"))
    parser.add_argument(
        "--base", default=str(Path.home() / "steam-arm64")
    )
    parser.add_argument("--variant", choices=tuple(VARIANTS))
    arguments = parser.parse_args()
    base = private_directory(Path(arguments.base), "Steam base")
    _, runtime, _ = paths(base)
    private_directory(runtime, "DXVK overlay runtime", create=True)
    lock_path = runtime / "lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if arguments.action == "activate":
            if arguments.variant is None:
                raise OverlayError("activate requires --variant")
            activate(base, arguments.variant)
        else:
            restore(base, require_state=True)
    except BlockingIOError as error:
        raise OverlayError("another DXVK overlay operation is active") from error
    finally:
        os.close(descriptor)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OverlayError as error:
        print(f"manage-tombraider-dxvk-overlay: {error}", file=os.sys.stderr)
        raise SystemExit(1)
