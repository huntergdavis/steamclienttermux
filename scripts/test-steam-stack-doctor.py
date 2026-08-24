#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


SCRIPT = Path(__file__).with_name("steam-stack-doctor.py")
SPEC = importlib.util.spec_from_file_location("steam_stack_doctor", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-stack-doctor.") as directory:
        root = Path(directory)
        repo = root / "repo"
        prefix = root / "prefix"
        home = root / "home"
        base = home / "steam-arm64"
        prefix.mkdir()
        home.mkdir()
        for relative in MODULE.REQUIRED_SOURCE:
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")

        runtime_files = (
            base / "client/steamrtarm64/steam",
            base / "mesa-kgsl/icd.d/freedreno-private.json",
            base / "prepare-pulseaudio-tcp.sh",
            home / "start-steam-native.sh",
        )
        for path in runtime_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
            path.chmod(0o700)
        glibc = home / ".local/share/tgcompat/glibc/package"
        (glibc / "lib").mkdir(parents=True)
        (glibc / "lib/ld-linux-aarch64.so.1").write_text("fixture\n")
        (glibc / ".tgcompat-package-sha256").write_text("0" * 64 + "\n")
        (glibc.parent / "current").symlink_to(glibc.name)

        def run(arguments):
            if tuple(arguments) == ("getprop", "ro.product.cpu.abi"):
                return 0, "arm64-v8a"
            if arguments[:2] == ("pm", "path"):
                return 0, f"package:/data/app/{arguments[2]}/base.apk"
            raise AssertionError(arguments)

        checks = MODULE.collect_checks(
            "runtime",
            base,
            prefix,
            home,
            4 * 1024**3,
            repo_root=repo,
            machine=lambda: "aarch64",
            lookup=lambda command: f"/fake/{command}",
            run=run,
            disk_usage=lambda path: SimpleNamespace(free=8 * 1024**3),
        )
        assert not [check for check in checks if check.status == "fail"], checks
        assert [check.name for check in checks if check.status == "warn"] == [
            "project license"
        ]
        table = MODULE.render_table(checks)
        assert "| architecture         | PASS" in table
        assert "| native glibc         | PASS" in table

        failed = MODULE.collect_checks(
            "bootstrap",
            base,
            prefix,
            home,
            4 * 1024**3,
            repo_root=repo,
            machine=lambda: "x86_64",
            lookup=lambda command: None if command == "clang" else f"/fake/{command}",
            run=lambda arguments: (1, ""),
            disk_usage=lambda path: SimpleNamespace(free=1024**3),
        )
        failures = {check.name: check for check in failed if check.status == "fail"}
        assert {"architecture", "android ABI", "Termux package", "Termux:X11 package", "build tools", "free storage"} <= failures.keys()
        assert "missing: clang" in failures["build tools"].detail

    print("Steam stack doctor tests: PASS")


if __name__ == "__main__":
    main()
