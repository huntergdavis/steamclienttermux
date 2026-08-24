#!/usr/bin/env python3

import hashlib
import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "scripts/manage-tombraider-dxvk-overlay.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("dxvk_overlay", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_tool()
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        base.chmod(0o700)
        fixtures = {
            "d3d10core.dll": b"x32-d3d10core-overlay-fixture",
            "d3d11.dll": b"x32-d3d11-overlay-fixture",
            "d3d9.dll": b"x32-d3d9-overlay-fixture",
            "dxgi.dll": b"x32-dxgi-overlay-fixture",
        }
        variant = "dxvk-fixture-x32"
        module.VARIANTS = {
            variant: (
                "fixture-dxvk-x32",
                "x32",
                {
                    name: (len(data), hashlib.sha256(data).hexdigest())
                    for name, data in fixtures.items()
                },
            )
        }
        candidate = (
            base
            / "candidates"
            / "fixture-dxvk-x32"
            / "x32"
        )
        candidate.mkdir(parents=True, mode=0o700)
        candidate.parent.chmod(0o700)
        candidate.parent.parent.chmod(0o700)
        game = base / "removable-library/steamapps/common/Tomb Raider"
        game.mkdir(parents=True)
        (base / "run").mkdir(mode=0o700)
        for name, data in fixtures.items():
            path = candidate / name
            path.write_bytes(data)
            path.chmod(0o600)

        module.activate(base, variant)
        state = base / "run/tombraider-dxvk-overlay/active.json"
        assert state.is_file()
        for name, data in fixtures.items():
            assert (game / name).read_bytes() == data

        evidence = module.restore(base, require_state=True)
        assert evidence and evidence.is_dir()
        assert not state.exists()
        assert (evidence / "manifest.json").is_file()
        for name, data in fixtures.items():
            assert not (game / name).exists()
            assert (evidence / name).read_bytes() == data
            assert (candidate / name).read_bytes() == data

        try:
            module.restore(base, require_state=True)
        except module.OverlayError as error:
            assert "no active" in str(error)
        else:
            raise AssertionError("restore accepted an inactive overlay")

        module.activate(base, variant)
        (game / "d3d11.dll").write_bytes(b"corrupt")
        try:
            module.restore(base, require_state=True)
        except module.OverlayError as error:
            assert "failed identity validation" in str(error)
        else:
            raise AssertionError("restore accepted a corrupt active DLL")

    source = TOOL.read_text(encoding="utf-8")
    assert "os.O_EXCL" in source and "os.O_NOFOLLOW" in source
    assert "os.replace(active, destination)" in source
    assert ".steamclienttermux-dxvk-overlays" in source
    assert "dxvk-1.10.3-x32" in source and "dxvk-2.4.1-x32" in source
    for name in ("d3d10core.dll", "d3d11.dll", "d3d9.dll", "dxgi.dll"):
        assert name in source
    print("Tomb Raider transactional DXVK overlay tests: PASS")


if __name__ == "__main__":
    main()
