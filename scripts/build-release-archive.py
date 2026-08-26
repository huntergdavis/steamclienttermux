#!/usr/bin/env python3
"""Build a deterministic, proprietary-free project bootstrap archive."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
INCLUDED_ROOTS = (
    "assets/",
    "bin/",
    "config/",
    "desktop/",
    "diagnostics/",
    "experiments/",
    "patches/",
    "probes/",
    "scripts/",
)
INCLUDED_FILES = {
    ".gitattributes",
    ".gitignore",
    "install.sh",
    "README.md",
    "LICENSE",
    "docs/ARCHITECTURE.md",
    "docs/NATIVE_STEAM_SPEED.md",
    "docs/NO_MANS_SKY.md",
    "docs/PACKAGING.md",
    "docs/PERFORMANCE.md",
    "docs/PRODUCTIZATION_RESEARCH.md",
    "docs/PROPRIETARY_AND_BINARY_INPUTS.md",
    "docs/research/OPTION_A_RED_TEAM.md",
    "docs/STEAM_TIMINGS.md",
    "docs/evidence/gtaiv-main-menu-2026-08-13.png",
}
REQUIRED_FILES = {
    "install.sh",
    "README.md",
    "LICENSE",
    "config/debian-runtime-lock.json",
    "config/glibc-runtime-lock.json",
    "config/proot-runtime-lock.json",
    "config/steam-arm64-bootstrap-lock.json",
    "config/termux-setup-profile.json",
    "config/turnip-runtime-lock.json",
    "config/tgcompat-runtime-lock.json",
    "scripts/bootstrap-steam-arm64-client.py",
    "scripts/bootstrap-termux-stack.sh",
    "scripts/build-release-archive.py",
    "scripts/check-project.sh",
    "scripts/setup-steam-stack.py",
    "scripts/install-turnip-runtime.py",
    "scripts/install-tgcompat-runtime.py",
    "scripts/install-glibc-runtime.py",
    "scripts/install-proot-runtime.py",
    "scripts/install-debian-runtime.py",
    "scripts/install-project-files.sh",
    "scripts/build-proot.sh",
    "scripts/steam-stack-doctor.py",
    "assets/nms-openvr-stub/openvr_api.dll.b64",
    "assets/nms-xinput/xinput1_4.dll",
    "assets/nms-xinput/xinput9_1_0.dll",
    "docs/PRODUCTIZATION_RESEARCH.md",
}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ReleaseError(RuntimeError):
    pass


def git_bytes(*arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), *arguments], stderr=subprocess.PIPE
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr.decode("utf-8", "replace").strip()
        raise ReleaseError(f"git {' '.join(arguments)} failed: {detail}") from error


def resolve_commit(revision: str) -> str:
    value = git_bytes("rev-parse", "--verify", f"{revision}^{{commit}}")
    commit = value.decode("ascii", "strict").strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ReleaseError("git returned a noncanonical commit identity")
    return commit


def included(path: str) -> bool:
    return path in INCLUDED_FILES or path.startswith(INCLUDED_ROOTS)


def safe_repo_path(path: str) -> None:
    candidate = PurePosixPath(path)
    if (
        not path
        or path.startswith("/")
        or "\x00" in path
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.as_posix() != path
    ):
        raise ReleaseError(f"unsafe Git path: {path!r}")


def commit_files(commit: str) -> list[dict[str, object]]:
    listing = git_bytes("ls-tree", "-r", "-z", "--full-tree", commit)
    files: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in listing.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise ReleaseError("could not decode Git tree entry") from error
        if not included(path):
            continue
        safe_repo_path(path)
        if path in seen:
            raise ReleaseError(f"duplicate Git path: {path}")
        seen.add(path)
        if object_type != "blob" or mode not in ("100644", "100755"):
            raise ReleaseError(f"unsupported release entry {mode} {object_type} {path}")
        payload = git_bytes("cat-file", "blob", object_id)
        files.append(
            {
                "path": path,
                "mode": int(mode[-3:], 8),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "payload": payload,
            }
        )
    files.sort(key=lambda item: str(item["path"]))
    missing = sorted(REQUIRED_FILES - {str(item["path"]) for item in files})
    if missing:
        raise ReleaseError(f"release is missing required files: {', '.join(missing)}")
    return files


def add_glibc_artifact(
    files: list[dict[str, object]], package: Path
) -> list[dict[str, object]]:
    lock_entry = next(
        (item for item in files if item["path"] == "config/glibc-runtime-lock.json"),
        None,
    )
    if lock_entry is None:
        raise ReleaseError("release is missing the glibc runtime lock")
    try:
        lock = json.loads(bytes(lock_entry["payload"]))
        artifact = lock["artifact"]
        filename = artifact["filename"]
        expected_size = artifact["size"]
        expected_sha256 = artifact["sha256"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReleaseError("glibc runtime lock is malformed") from error
    artifact_path = f"artifacts/{filename}"
    safe_repo_path(artifact_path)
    if (
        not isinstance(filename, str)
        or PurePosixPath(filename).name != filename
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ReleaseError("glibc artifact lock is malformed")
    if not package.is_file() or package.is_symlink():
        raise ReleaseError(f"glibc package is missing or unsafe: {package}")
    payload = package.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != expected_size or digest != expected_sha256:
        raise ReleaseError("glibc package does not match the committed release lock")
    if any(item["path"] == artifact_path for item in files):
        raise ReleaseError(f"duplicate release path: {artifact_path}")
    result = list(files)
    result.append(
        {
            "path": artifact_path,
            "mode": 0o644,
            "size": len(payload),
            "sha256": digest,
            "payload": payload,
        }
    )
    result.sort(key=lambda item: str(item["path"]))
    return result


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def zip_info(path: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, FIXED_ZIP_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.extra = b""
    info.comment = b""
    return info


def build_archive(commit: str, glibc_package: Path) -> tuple[bytes, dict[str, object]]:
    files = add_glibc_artifact(commit_files(commit), glibc_package)
    prefix = f"steamclienttermux-{commit[:12]}"
    public_files = [
        {key: item[key] for key in ("path", "mode", "size", "sha256")}
        for item in files
    ]
    release_manifest = {
        "schema_version": 1,
        "project": "steamclienttermux",
        "source_commit": commit,
        "prefix": prefix,
        "payload_file_count": len(public_files),
        "license_present": any(
            str(item["path"]).lower() in ("license", "license.md", "license.txt")
            for item in files
        ),
        "redistributes_valve_binaries": False,
        "redistributed_open_source_artifacts": [
            "artifacts/glibc_2.44_aarch64.deb"
        ],
        "files": public_files,
    }
    embedded_manifest = json_bytes(release_manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", allowZip64=True) as archive:
        archive.comment = b""
        for item in files:
            archive.writestr(
                zip_info(f"{prefix}/{item['path']}", int(item["mode"])),
                item["payload"],
            )
        archive.writestr(
            zip_info(f"{prefix}/RELEASE-MANIFEST.json", 0o644),
            embedded_manifest,
        )
    payload = stream.getvalue()
    external_manifest = dict(release_manifest)
    external_manifest["archive"] = {
        "filename": f"{prefix}.zip",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "compression": "ZIP_STORED",
    }
    external_manifest["embedded_manifest_sha256"] = hashlib.sha256(
        embedded_manifest
    ).hexdigest()
    return payload, external_manifest


def write_release(destination: Path, payload: bytes, manifest: dict[str, object]) -> None:
    if destination.exists() or destination.is_symlink():
        raise ReleaseError(f"destination already exists: {destination}")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ReleaseError(f"destination parent is not a safe directory: {parent}")
    destination.mkdir(mode=0o755)
    archive = manifest["archive"]
    assert isinstance(archive, dict)
    archive_path = destination / str(archive["filename"])
    manifest_path = destination / "release-manifest.json"
    try:
        with archive_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with manifest_path.open("xb") as stream:
            stream.write(json_bytes(manifest))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        (destination / "INCOMPLETE").touch(exist_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD", help="exact Git revision to package")
    parser.add_argument(
        "--glibc-package",
        required=True,
        type=Path,
        help="audited patched glibc .deb matching the committed lock",
    )
    parser.add_argument(
        "--destination",
        required=True,
        type=Path,
        help="new directory for the ZIP and release-manifest.json",
    )
    arguments = parser.parse_args()
    try:
        commit = resolve_commit(arguments.commit)
        payload, manifest = build_archive(commit, arguments.glibc_package.resolve())
        write_release(arguments.destination.resolve(), payload, manifest)
    except ReleaseError as error:
        print(f"build-release-archive: {error}", file=sys.stderr)
        return 1
    archive = manifest["archive"]
    assert isinstance(archive, dict)
    print(f"RELEASE_COMMIT={commit}")
    print(f"RELEASE_ARCHIVE={arguments.destination.resolve() / str(archive['filename'])}")
    print(f"RELEASE_SIZE={archive['size']}")
    print(f"RELEASE_SHA256={archive['sha256']}")
    print(f"RELEASE_LICENSE_PRESENT={int(bool(manifest['license_present']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
