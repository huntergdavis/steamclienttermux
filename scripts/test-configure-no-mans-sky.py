#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).with_name("configure-no-mans-sky.py")
DETAIL_NAMES = (
    "TextureQuality",
    "AnimationQuality",
    "ShadowQuality",
    "PostProcessingEffects",
    "ReflectionsQuality",
    "VolumetricsQuality",
    "TerrainTessellation",
    "PlanetQuality",
    "WaterQuality",
    "BaseQuality",
)


def fixture() -> bytes:
    details = "\n".join(
        f'''    <Property name="{name}" value="TkGraphicsDetailTypes">
      <Property name="GraphicDetail" value="Ultra" />
    </Property>'''
        for name in DETAIL_NAMES
    )
    return f'''<?xml version="1.0" encoding="utf-8"?>
<Data template="TkGraphicsSettings">
  <Property name="Version" value="9" />
  <Property name="FullScreen" value="false" />
  <Property name="Borderless" value="true" />
  <Property name="ResolutionWidth" value="2800" />
  <Property name="ResolutionHeight" value="1752" />
  <Property name="ResolutionScale" value="0.500000" />
  <Property name="VsyncEx" value="Triple" />
  <Property name="GraphicsDetail" value="TkGraphicsDetailPreset">
{details}
    <Property name="AmbientOcclusion" value="GTAO_Ultra" />
    <Property name="AnisotropyLevel" value="16" />
    <Property name="AntiAliasing" value="DLAA" />
    <Property name="FFXSRQuality" value="UltraQuality" />
    <Property name="FFXSR2Quality" value="Balanced" />
    <Property name="DLSSFrameGeneration" value="On" />
    <Property name="NVIDIAReflexLowLatency" value="On" />
  </Property>
  <Property name="MotionBlurStrength" value="180.000000" />
  <Property name="VignetteAndScanlines" value="true" />
  <Property name="MaxframeRate" value="160" />
  <Property name="NumHighThreads" value="6" />
  <Property name="NumLowThreads" value="6" />
  <Property name="TextureStreamingVk" value="Off" />
  <Property name="UseTerrainTextureCache" value="true" />
  <Property name="UseArbSparseTexture" value="true" />
  <Property name="HDRMode" value="HDR1000" />
  <Property name="NumGraphicsThreadsBeta" value="3" />
</Data>
'''.encode()


def direct(parent: ET.Element) -> dict[str, ET.Element]:
    return {item.get("name", ""): item for item in parent if item.tag == "Property"}


def run(settings: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), "--settings", str(settings), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nms-profile-test.") as directory:
        settings = Path(directory) / "TKGRAPHICSSETTINGS.MXML"
        original = fixture()
        settings.write_bytes(original)
        dry = run(settings, "--dry-run", "--fsr", "balanced")
        assert dry.returncode == 0, dry.stderr
        assert json.loads(dry.stdout)["changed"] > 0
        assert settings.read_bytes() == original

        applied = run(settings, "--fsr", "balanced", "--fps", "30")
        assert applied.returncode == 0, applied.stderr
        report = json.loads(applied.stdout)
        assert report["output"] == "1920x1080"
        backup = Path(report["backup"])
        assert backup.read_bytes() == original
        root = ET.parse(settings).getroot()
        top = direct(root)
        assert top["FullScreen"].get("value") == "true"
        assert top["Borderless"].get("value") == "false"
        assert top["ResolutionWidth"].get("value") == "1920"
        assert top["ResolutionHeight"].get("value") == "1080"
        assert top["MaxframeRate"].get("value") == "30"
        graphics = direct(top["GraphicsDetail"])
        assert graphics["AntiAliasing"].get("value") == "FFXSR2"
        assert graphics["FFXSR2Quality"].get("value") == "Balanced"
        assert direct(graphics["TextureQuality"])["GraphicDetail"].get("value") == "High"
        assert direct(graphics["VolumetricsQuality"])["GraphicDetail"].get("value") == "Standard"

        repeated = run(settings, "--fsr", "balanced", "--fps", "30")
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(repeated.stdout)["changed"] == 0
        assert json.loads(repeated.stdout)["backup"] is None

        unsafe = Path(directory) / "unsafe.MXML"
        unsafe.symlink_to(settings)
        rejected = run(unsafe)
        assert rejected.returncode != 0
        assert "non-symlink" in rejected.stderr
    print("No Man's Sky 1080p profile tests: PASS")


if __name__ == "__main__":
    main()
