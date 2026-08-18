#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "bin/prepare-proc-net-shadow.sh"
VALID_STAT = (
    "cpu  20 0 10 100 0 0 0 0 0 0\n"
    "cpu0 10 0 5 50 0 0 0 0 0 0\n"
    "cpu1 10 0 5 50 0 0 0 0 0 0\n"
    "intr 0\n"
)


def run_preparer(base: Path, source: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(base.parent / "prefix"),
            "STEAM_ARM_IPV4": "192.168.1.20",
            "STEAM_ARM_INTERFACE": "wlan0",
            "STEAM_ARM_NETMASK": "255.255.255.0",
            "STEAM_ARM_GATEWAY": "192.168.1.1",
            "STEAM_ARM_PROC_STAT_SOURCE": str(source),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), str(base)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def private_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")
    path.chmod(0o600)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="prepare-proc-shadows.") as directory:
        root = Path(directory)
        base = root / "base"
        source = root / "prefix/var/lib/proot/sysdata/stat"
        private_fixture(source, VALID_STAT)

        result = run_preparer(base, source)
        assert result.returncode == 0, result.stderr
        assert "and /proc/stat with 2 CPUs" in result.stdout
        proc_stat = base / "config/proc-stat"
        assert proc_stat.read_text(encoding="ascii") == VALID_STAT
        assert proc_stat.stat().st_mode & 0o777 == 0o600
        assert (base / "config/proc-net/route").stat().st_mode & 0o777 == 0o600
        assert (base / "config/proc-net/ipv6_route").stat().st_mode & 0o777 == 0o600

        private_fixture(source, "cpu 10 0 5 50\ncpu1 10 0 5 50\n")
        rejected = run_preparer(base, source)
        assert rejected.returncode != 0
        assert "invalid CPU table" in rejected.stderr
        assert proc_stat.read_text(encoding="ascii") == VALID_STAT

        private_fixture(source, VALID_STAT)
        proc_stat.unlink()
        proc_stat.symlink_to(source)
        rejected = run_preparer(base, source)
        assert rejected.returncode != 0
        assert "refusing non-regular destination entry" in rejected.stderr

    print("synthetic proc shadow preparation tests: PASS")


if __name__ == "__main__":
    main()
