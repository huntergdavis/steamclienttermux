#!/usr/bin/env python3

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "scripts/prefetch-game-files.py"
LAUNCHER = ROOT / "scripts/start-tombraider-direct-dispatch.sh"
INSTALLER = ROOT / "scripts/install-project-files.sh"


def run(tool_root: Path, manifest: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--root",
            str(tool_root),
            "--manifest",
            str(manifest),
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="game-prefetch.") as directory:
        root = Path(directory)
        game = root / "game"
        game.mkdir()
        (game / "one.bin").write_bytes(b"a" * 4096)
        (game / "two.bin").write_bytes(b"b" * 8192)
        manifest = root / "manifest.json"
        document = {
            "schema": 1,
            "maximum_total_bytes": 16384,
            "files": [
                {"path": "one.bin", "expected_size": 4096, "read_bytes": 2048},
                {"path": "two.bin", "expected_size": 8192, "read_bytes": 8192},
            ],
        }
        manifest.write_text(json.dumps(document), encoding="utf-8")
        checked = run(game, manifest, "--check")
        assert checked.returncode == 0, checked.stderr
        assert json.loads(checked.stdout) == {
            "schema": 1,
            "status": "validated",
            "files": 2,
            "bytes": 10240,
        }
        warmed = run(game, manifest)
        assert warmed.returncode == 0, warmed.stderr
        result = json.loads(warmed.stdout)
        assert result["status"] == "complete"
        assert result["files"] == 2 and result["bytes"] == 10240

        (game / "link.bin").symlink_to("one.bin")
        document["files"][0]["path"] = "link.bin"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        rejected = run(game, manifest)
        assert rejected.returncode != 0
        assert "identity validation" in rejected.stderr

        document["files"][0]["path"] = "../escape.bin"
        manifest.write_text(json.dumps(document), encoding="utf-8")
        rejected = run(game, manifest)
        assert rejected.returncode != 0
        assert "escapes" in rejected.stderr

    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert "TOMB_RAIDER_STARTUP_PREFETCH" in launcher
    assert "startup_prefetch_start" in launcher
    assert "startup_prefetch_complete" in launcher
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "prefetch-game-files.py" in installer
    assert "tombraider-startup-prefetch.json" in installer
    print("game startup prefetch tests: PASS")


if __name__ == "__main__":
    main()
