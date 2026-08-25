#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("summarize-mangohud-csv.py")


def run(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), str(path), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def fixture() -> str:
    rows = [
        "v1",
        "v0.7.1",
        "--------------------FRAME METRICS--------------------",
        "fps,frametime,elapsed",
    ]
    for index, fps in enumerate((10, 20, 30, 40, 50)):
        rows.append(f"{fps},{1000 / fps},{index * 1_000_000_000}")
    return "\n".join(rows) + "\n"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mangohud-summary-test.") as directory:
        root = Path(directory)
        source = root / "metrics.csv"
        source.write_text(fixture(), encoding="utf-8")
        result = run(source, "--start-seconds", "1", "--duration-seconds", "3")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["selection"]["samples"] == 3
        assert payload["sampled_fps"]["mean"] == 30
        assert payload["sampled_fps"]["median"] == 30
        assert payload["sampled_fps"]["minimum"] == 20
        assert payload["sampled_fps"]["maximum"] == 40
        assert "not per-frame" in payload["claim_boundary"]

        unsafe = root / "unsafe.csv"
        unsafe.symlink_to(source)
        rejected = run(unsafe)
        assert rejected.returncode != 0
        assert "non-symlink" in rejected.stderr

        malformed = root / "malformed.csv"
        malformed.write_text(fixture().replace("30,", "nan,"), encoding="utf-8")
        invalid = run(malformed)
        assert invalid.returncode != 0
        assert "non-finite" in invalid.stderr
    print("MangoHud CSV summary tests: PASS")


if __name__ == "__main__":
    main()
