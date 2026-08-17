#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).with_name("capture-pressure-vessel-plan.py")


def run_capture(base: Path, output: Path, secret: str = "not-recorded") -> subprocess.CompletedProcess[str]:
    args_fd, args_path = tempfile.mkstemp(prefix="bwrap-args-", dir=base)
    source_fd = os.open(base / "source", os.O_RDONLY | os.O_DIRECTORY)
    arguments = [
        "--proc",
        "/proc",
        "--ro-bind-fd",
        str(source_fd),
        "/fixture",
        "--setenv",
        "FIXTURE",
        "value",
        "--",
        "/bin/true",
    ]
    os.write(args_fd, b"\0".join(os.fsencode(item) for item in arguments) + b"\0")
    environment = os.environ.copy()
    environment.update(
        {
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_BWRAP_CAPTURE_PLAN": str(output),
            "SECRET_MARKER": secret,
        }
    )
    try:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--args", str(args_fd), "payload", "argument"],
            env=environment,
            pass_fds=(args_fd, source_fd),
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        os.close(args_fd)
        os.close(source_fd)
        os.unlink(args_path)


def run_probe(base: Path, delegate: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_CAPTURE_REAL_BWRAP": str(delegate),
        }
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="capture-pv-plan-") as directory:
        base = Path(directory) / "base"
        base.mkdir(mode=0o700)
        (base / "logs").mkdir(mode=0o700)
        (base / "source").mkdir()
        delegate = (
            base
            / "runtime"
            / "SteamLinuxRuntime_4-arm64"
            / "pressure-vessel"
            / "libexec"
            / "steam-runtime-tools-0"
            / "srt-bwrap"
        )
        delegate.parent.mkdir(parents=True)
        delegate.write_text(
            "#!/bin/sh\nprintf 'PROBE:%s\\n' \"$*\"\n", encoding="utf-8"
        )
        delegate.chmod(0o700)
        output = base / "logs" / "runtime-plans" / "fixture.json"
        secret = "credential-like-value-must-not-appear"

        probe = run_probe(base, delegate)
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout == "PROBE:--version\n"
        assert not (base / "logs" / "runtime-plans").exists()

        wrong_delegate = run_probe(base, base / "wrong-bwrap")
        assert wrong_delegate.returncode == 125
        assert "expected srt-bwrap" in wrong_delegate.stderr

        result = run_capture(base, output, secret)
        assert result.returncode == 0, result.stderr
        assert output.is_file() and output.stat().st_mode & 0o777 == 0o600
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["kind"] == "pressure-vessel-bwrap-plan"
        assert payload["bwrap_args"][-2:] == ["--", "/bin/true"]
        assert payload["payload_argv"] == ["payload", "argument"]
        assert payload["invocation"][-2:] == ["payload", "argument"]
        assert payload["invocation"].count("payload") == 1
        assert payload["fd_sources"] == [
            {
                "argument_index": 2,
                "option": "--ro-bind-fd",
                "fd": payload["fd_sources"][0]["fd"],
                "source": str(base / "source"),
            }
        ]
        assert secret not in output.read_text(encoding="utf-8")

        repeated = run_capture(base, output)
        assert repeated.returncode == 125
        assert "refusing to replace" in repeated.stderr

        outside = run_capture(base, base / "outside.json")
        assert outside.returncode == 125
        assert "safe JSON name" in outside.stderr

    print("Pressure Vessel plan capture tests: PASS")


if __name__ == "__main__":
    main()
