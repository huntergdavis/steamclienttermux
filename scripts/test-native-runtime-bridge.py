#!/usr/bin/env python3

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm64-native-bwrap"
ENTRY_SOURCE = (
    Path(__file__).resolve().parents[1] / "diagnostics" / "native-bwrap-entry.c"
)


def executable(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def stamped_proot(path: Path, include_required_patch: bool = True) -> None:
    executable(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    patches = (
        "proot-runtime-directory-bind-target.patch"
        if include_required_patch
        else "unrelated.patch"
    )
    (path.parent.parent / ".steamclienttermux-patchset").write_text(
        f"patches={patches}\nproot_sha256={digest}\n", encoding="utf-8"
    )


def prepare(root: Path) -> tuple[Path, Path]:
    prefix = root / "prefix"
    base = root / "base"
    runtime = base / "runtime" / "SteamLinuxRuntime_4-arm64"

    stamped_proot(base / "src" / "proot-production" / "src" / "proot")
    executable(base / "compat-bin" / "steam-arm64-bwrap-route")
    executable(runtime / "_v2-entry-point")
    executable(
        runtime
        / "pressure-vessel"
        / "libexec"
        / "steam-runtime-tools-0"
        / "srt-bwrap"
    )
    (runtime / ".steamclienttermux-runtime-shadow").write_text(
        "test fixture\n", encoding="utf-8"
    )
    (base / "client" / "steamapps" / "common" / "SteamLinuxRuntime_4-arm64").mkdir(
        parents=True
    )
    (base / "config" / "proc-net").mkdir(parents=True)
    (base / "config" / "proc-net" / "route").write_text("route\n")
    (base / "config" / "proc-net" / "ipv6_route").write_text("route6\n")
    (base / "config" / "hosts-ipv4").write_text("127.0.0.1 localhost\n")
    executable(base / "config" / "steamlinuxruntime4-run-direct")
    (base / "mesa-kgsl" / "usr" / "lib" / "aarch64-linux-gnu").mkdir(
        parents=True
    )
    executable(
        prefix / "bin" / "proot-distro",
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
    )
    return prefix, base


def run_bridge(prefix: Path, base: Path, mode: str) -> list[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BRIDGE_MODE": mode,
            "GAME_OPTION_FIXTURE": "preserved value",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT), "--fixture-argument"],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.splitlines()


def run_preflight(prefix: Path, base: Path, proot_dir: Path) -> list[str]:
    stamped_proot(proot_dir / "proot")
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BWRAP_CHECK": "1",
            "STEAM_ARM64_PROOT_DIR": str(proot_dir),
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.splitlines()


def run_rejected_preflight(prefix: Path, base: Path, proot_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BWRAP_CHECK": "1",
            "STEAM_ARM64_PROOT_DIR": str(proot_dir),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="native-runtime-bridge.") as directory:
        prefix, base = prepare(Path(directory))
        route = str(base / "compat-bin" / "steam-arm64-bwrap-route")
        runtime_entry = str(
            base
            / "client"
            / "steamapps"
            / "common"
            / "SteamLinuxRuntime_4-arm64"
            / "_v2-entry-point"
        )

        bwrap = run_bridge(prefix, base, "bwrap")
        assert "--env" in bwrap
        assert "GAME_OPTION_FIXTURE=preserved value" in bwrap
        assert route in bwrap
        assert bwrap[-1] == "--fixture-argument"

        runtime = run_bridge(prefix, base, "runtime")
        assert f"PRESSURE_VESSEL_BWRAP={route}" in runtime
        assert runtime_entry in runtime
        assert runtime[-1] == "--fixture-argument"

        selected_proot = base / "src" / "native-profile" / "src"
        preflight = run_preflight(prefix, base, selected_proot)
        assert f"proot={selected_proot / 'proot'}" in preflight
        assert "native game boundary preflight: PASS" in preflight

        bridge_source = SCRIPT.read_text(encoding="utf-8")
        assert "TGCOMPAT_EXEC_LD_PRELOAD" in bridge_source
        assert "TGCOMPAT_EXEC_SHELL" in bridge_source
        assert "TGCOMPAT_EXEC_PATH_FROM" in bridge_source
        assert "TGCOMPAT_EXEC_PATH_TO" in bridge_source

        entry_source = ENTRY_SOURCE.read_text(encoding="utf-8")
        assert '"TGCOMPAT_EXEC_SHELL"' in entry_source
        assert '"TGCOMPAT_EXEC_PATH_FROM"' in entry_source
        assert '"TGCOMPAT_EXEC_PATH_TO"' in entry_source

        (selected_proot / "proot").write_text("changed after stamp\n", encoding="utf-8")
        changed = run_rejected_preflight(prefix, base, selected_proot)
        assert changed.returncode == 125
        assert "does not match its build stamp" in changed.stderr

        missing_patch = base / "src" / "missing-required-patch" / "src"
        stamped_proot(missing_patch / "proot", include_required_patch=False)
        rejected_patch = run_rejected_preflight(prefix, base, missing_patch)
        assert rejected_patch.returncode == 125
        assert "lacks proot-runtime-directory-bind-target.patch" in rejected_patch.stderr

    print("native runtime bridge tests: PASS")


if __name__ == "__main__":
    main()
