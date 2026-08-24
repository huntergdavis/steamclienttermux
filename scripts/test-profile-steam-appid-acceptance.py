#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts/profile-steam-appid-acceptance.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("acceptance_profile", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_tool()
    with tempfile.TemporaryDirectory(prefix="steam-acceptance-profile.") as directory:
        root = Path(directory)
        aarch64 = root / "aarch64"
        x86 = root / "x86"
        aarch64.write_bytes(b"\x7fELF\x02\x01" + b"\0" * 12 + (183).to_bytes(2, "little"))
        x86.write_bytes(b"\x7fELF\x02\x01" + b"\0" * 12 + (62).to_bytes(2, "little"))
        assert module.elf_machine(aarch64) == "aarch64"
        assert module.elf_machine(x86) == "x86_64"
        first = {
            "user_ticks": 10,
            "system_ticks": 20,
            "threads": 2,
            "rss_kib": 100,
            "rchar_bytes": 1000,
            "storage_read_bytes": 4096,
            "read_syscalls": 4,
        }
        last = {
            "user_ticks": 60,
            "system_ticks": 45,
            "threads": 4,
            "rss_kib": 180,
            "rchar_bytes": 3000,
            "storage_read_bytes": 12288,
            "read_syscalls": 14,
        }
        assert module.delta(first, last, 100) == {
            "rchar_bytes": 2000,
            "storage_read_bytes": 8192,
            "read_syscalls": 10,
            "cpu_user_seconds": 0.5,
            "cpu_system_seconds": 0.25,
            "peak_threads": 4,
            "peak_rss_kib": 180,
        }
    source = TOOL.read_text(encoding="utf-8")
    assert "AppID {arguments.appid} adding PID" in source
    assert "steam_acceptance_emulation_observed" in source
    assert "FEXInterpreter".casefold() in source.casefold()
    print("Steam AppID acceptance profiler tests: PASS")


if __name__ == "__main__":
    main()
