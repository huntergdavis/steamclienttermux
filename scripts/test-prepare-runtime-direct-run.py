#!/usr/bin/env python3

from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "prepare-runtime-direct-run.sh"
SOURCE = """#!/bin/sh
# Generated file, do not edit
export PRESSURE_VESSEL_COPY_RUNTIME=1
exec \"${pressure_vessel}/bin/pressure-vessel-unruntime\" \"$@\"
"""


def invoke(base: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(base)],
        text=True,
        capture_output=True,
        check=check,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="runtime-direct-run.") as directory:
        base = Path(directory)
        source = base / "runtime" / "SteamLinuxRuntime_4-arm64" / "run"
        source.parent.mkdir(parents=True)
        source.write_text(SOURCE, encoding="utf-8")
        source.chmod(0o700)

        invoke(base)
        destination = base / "config" / "steamlinuxruntime4-run-direct"
        expected = SOURCE.replace(
            "export PRESSURE_VESSEL_COPY_RUNTIME=1",
            "export PRESSURE_VESSEL_COPY_RUNTIME=0",
        )
        assert destination.read_text(encoding="utf-8") == expected
        assert destination.stat().st_mode & 0o777 == 0o700
        first_mtime = destination.stat().st_mtime_ns
        invoke(base)
        assert destination.stat().st_mtime_ns == first_mtime

        source.write_text(SOURCE.replace("COPY_RUNTIME=1", "COPY_RUNTIME=yes"))
        rejected = invoke(base, check=False)
        assert rejected.returncode != 0
        assert "unexpected copy policy" in rejected.stderr

    print("direct Runtime 4 policy tests: PASS")


if __name__ == "__main__":
    main()
