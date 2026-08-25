#!/usr/bin/env python3
"""Apply a measured, reversible 1080p No Man's Sky graphics profile."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import xml.etree.ElementTree as ET


MAX_SETTINGS_BYTES = 1024 * 1024
DETAILS = {
    "TextureQuality": "High",
    "AnimationQuality": "High",
    "ShadowQuality": "Standard",
    "PostProcessingEffects": "Standard",
    "ReflectionsQuality": "Standard",
    "VolumetricsQuality": "Standard",
    "TerrainTessellation": "Standard",
    "PlanetQuality": "Standard",
    "WaterQuality": "Standard",
    "BaseQuality": "Standard",
}


class ProfileError(RuntimeError):
    pass


def default_settings() -> Path:
    override = os.environ.get("STEAM_ARM64_NMS_SETTINGS")
    if override:
        return Path(override)
    base = Path(os.environ.get("STEAM_ARM64_BASE", Path.home() / "steam-arm64"))
    return (
        base
        / "removable-library/steamapps/common/No Man's Sky"
        / "Binaries/SETTINGS/TKGRAPHICSSETTINGS.MXML"
    )


def direct_properties(parent: ET.Element) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    for child in parent:
        if child.tag != "Property":
            continue
        name = child.get("name")
        if not name:
            continue
        if name in result:
            raise ProfileError(f"duplicate property: {name}")
        result[name] = child
    return result


def require(properties: dict[str, ET.Element], name: str) -> ET.Element:
    try:
        return properties[name]
    except KeyError as error:
        raise ProfileError(f"required property is missing: {name}") from error


def set_value(element: ET.Element, value: str, changes: list[dict[str, str]]) -> None:
    name = element.get("name", "")
    old = element.get("value")
    if old is None:
        raise ProfileError(f"property has no value: {name}")
    if old != value:
        changes.append({"property": name, "old": old, "new": value})
        element.set("value", value)


def profile_values(fsr: str, fps: int) -> dict[str, str]:
    return {
        "FullScreen": "true",
        "Borderless": "false",
        "ResolutionWidth": "1920",
        "ResolutionHeight": "1080",
        "ResolutionScale": "1.000000",
        "VsyncEx": "Off",
        "MotionBlurStrength": "0.000000",
        "VignetteAndScanlines": "false",
        "MaxframeRate": str(fps),
        "NumHighThreads": "0",
        "NumLowThreads": "0",
        "TextureStreamingVk": "Auto",
        "UseTerrainTextureCache": "false",
        "UseArbSparseTexture": "false",
        "HDRMode": "Off",
        "NumGraphicsThreadsBeta": "0",
        "AmbientOcclusion": "GTAO_Low",
        "AnisotropyLevel": "4",
        "AntiAliasing": "FFXSR2",
        "FFXSRQuality": "Off",
        "FFXSR2Quality": fsr.capitalize(),
        "DLSSFrameGeneration": "Off",
        "NVIDIAReflexLowLatency": "Off",
    }


def load_settings(path: Path) -> tuple[bytes, os.stat_result, ET.ElementTree]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ProfileError(f"settings must be a regular non-symlink file: {path}")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SETTINGS_BYTES:
        raise ProfileError(f"settings size is invalid: {metadata.st_size}")
    payload = path.read_bytes()
    try:
        tree = ET.ElementTree(ET.fromstring(payload))
    except ET.ParseError as error:
        raise ProfileError(f"settings XML is invalid: {error}") from error
    root = tree.getroot()
    if root.tag != "Data" or root.get("template") != "TkGraphicsSettings":
        raise ProfileError("settings root is not TkGraphicsSettings")
    return payload, metadata, tree


def apply_profile(tree: ET.ElementTree, fsr: str, fps: int) -> list[dict[str, str]]:
    root = tree.getroot()
    top = direct_properties(root)
    graphics = require(top, "GraphicsDetail")
    graphics_properties = direct_properties(graphics)
    changes: list[dict[str, str]] = []

    values = profile_values(fsr, fps)
    for name in (
        "FullScreen",
        "Borderless",
        "ResolutionWidth",
        "ResolutionHeight",
        "ResolutionScale",
        "VsyncEx",
        "MotionBlurStrength",
        "VignetteAndScanlines",
        "MaxframeRate",
        "NumHighThreads",
        "NumLowThreads",
        "TextureStreamingVk",
        "UseTerrainTextureCache",
        "UseArbSparseTexture",
        "HDRMode",
        "NumGraphicsThreadsBeta",
    ):
        set_value(require(top, name), values[name], changes)

    for name, detail in DETAILS.items():
        category = require(graphics_properties, name)
        category_properties = direct_properties(category)
        set_value(require(category_properties, "GraphicDetail"), detail, changes)

    for name in (
        "AmbientOcclusion",
        "AnisotropyLevel",
        "AntiAliasing",
        "FFXSRQuality",
        "FFXSR2Quality",
        "DLSSFrameGeneration",
        "NVIDIAReflexLowLatency",
    ):
        set_value(require(graphics_properties, name), values[name], changes)
    return changes


def write_profile(
    path: Path, original: bytes, metadata: os.stat_result, tree: ET.ElementTree
) -> Path:
    current = path.lstat()
    if (
        current.st_dev != metadata.st_dev
        or current.st_ino != metadata.st_ino
        or current.st_size != metadata.st_size
        or current.st_mtime_ns != metadata.st_mtime_ns
    ):
        raise ProfileError("settings changed while the profile was being prepared")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.pre-steamclienttermux-{stamp}")
    with backup.open("xb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    backup.chmod(stat.S_IMODE(metadata.st_mode))

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            tree.write(stream, encoding="utf-8", xml_declaration=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(stat.S_IMODE(metadata.st_mode))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the reversible 1080p tuned No Man's Sky profile."
    )
    parser.add_argument("--settings", type=Path, default=default_settings())
    parser.add_argument(
        "--fsr", choices=("quality", "balanced", "performance"), default="quality"
    )
    parser.add_argument("--fps", type=int, choices=(30, 40, 60), default=30)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    try:
        original, metadata, tree = load_settings(arguments.settings)
        changes = apply_profile(tree, arguments.fsr, arguments.fps)
        backup = None
        if changes and not arguments.dry_run:
            backup = write_profile(arguments.settings, original, metadata, tree)
    except (OSError, ProfileError) as error:
        parser.error(str(error))
    result = {
        "backup": str(backup) if backup else None,
        "changed": len(changes),
        "dry_run": arguments.dry_run,
        "fps": arguments.fps,
        "fsr": arguments.fsr,
        "output": "1920x1080",
        "settings": str(arguments.settings),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
