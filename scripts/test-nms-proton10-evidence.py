#!/usr/bin/env python3

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/nms-proton10-termux-x11-20260825.json"
PROFILE = ROOT / "docs/NO_MANS_SKY.md"
RESEARCH = ROOT / "docs/research/GAMENATIVE_PROTON10_TERMUX_X11.md"


def main() -> None:
    data = json.loads(EVIDENCE.read_text())
    results = {gate["name"]: gate["result"] for gate in data["gates"]}

    assert data["schema"] == 1
    assert data["game"]["appid"] == 275850
    assert results["Termux:X11 Windows graphics"] == "pass"
    assert results["Steam-authenticated NMS"] == "not_run"
    assert results["controller in Proton 10"] == "not_run"
    assert results["NMS gameplay and FPS"] == "not_run"
    assert data["x11_discriminator"]["passing_tmpdir"] == "$PREFIX/tmp"
    assert data["steam_boundary"]["helper_license"].startswith("proprietary")
    assert data["claims"] == {
        "proton10_graphical_smoke": True,
        "nms_gameplay": False,
        "controller": False,
        "fps": False,
        "easy_installer_complete": False,
    }

    profile = PROFILE.read_text()
    research = RESEARCH.read_text()
    assert "Proton 10 ARM64EC discriminator" in profile
    assert "Steam-authenticated NMS | Not yet" in research
    assert "A synthetic frame does not establish" in research
    print("NMS Proton 10 evidence boundary: PASS")


if __name__ == "__main__":
    main()
