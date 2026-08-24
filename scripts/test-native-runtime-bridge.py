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
    executable(base / "compat-bin" / "capture-pressure-vessel-plan.py")
    executable(base / "compat-bin" / "pressure-vessel-direct-dispatch.py")
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
    proton_dxvk = (
        base
        / "client"
        / "steamapps"
        / "common"
        / "Proton 11.0 (ARM64)"
        / "files"
        / "lib"
        / "wine"
        / "dxvk"
        / "i386-windows"
    )
    proton_dxvk.mkdir(parents=True)
    for name in (
        "d3d10core.dll",
        "d3d11.dll",
        "d3d8.dll",
        "d3d9.dll",
        "dxgi.dll",
    ):
        (proton_dxvk / name).write_bytes(b"bundled fixture\n")
    (base / "client" / "linuxarm64").mkdir(parents=True)
    (base / "native-home" / ".steam").mkdir(parents=True)
    (base / "native-home" / ".steam" / "sdkarm64").symlink_to(
        base / "client" / "linuxarm64"
    )
    (base / "config" / "proc-net").mkdir(parents=True)
    (base / "config" / "proc-net" / "route").write_text("route\n")
    (base / "config" / "proc-net" / "ipv6_route").write_text("route6\n")
    (base / "config" / "proc-stat").write_text(
        "cpu 20 0 10 100\ncpu0 10 0 5 50\ncpu1 10 0 5 50\n",
        encoding="ascii",
    )
    (base / "config" / "hosts-ipv4").write_text("127.0.0.1 localhost\n")
    executable(base / "config" / "steamlinuxruntime4-run-direct")
    (base / "mesa-kgsl" / "usr" / "lib" / "aarch64-linux-gnu").mkdir(
        parents=True
    )
    private_icd = base / "mesa-kgsl" / "icd.d" / "freedreno-private.json"
    private_icd.parent.mkdir(parents=True)
    private_icd.write_text("{}\n", encoding="utf-8")
    private_icd.chmod(0o600)
    bvb_icd = base / "bvb" / "icd.d" / "bvb_icd.aarch64.json"
    bvb_icd.parent.mkdir(parents=True)
    bvb_icd.write_text("{}\n", encoding="utf-8")
    bvb_icd.chmod(0o600)
    executable(
        prefix / "bin" / "proot-distro",
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
    )
    return prefix, base


def run_bridge(
    prefix: Path,
    base: Path,
    mode: str,
    capture_plan: Path | None = None,
    bvb_vulkan: bool = False,
    game_name: str = "Game",
) -> list[str]:
    removable_source = base.parent / "fixture-storage"
    removable_target = base / "removable-library"
    game_directory = removable_source / "steamapps" / "common" / game_name
    game_directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BRIDGE_MODE": mode,
            "GAME_OPTION_FIXTURE": "preserved value",
            "SDL_JOYSTICK_HIDAPI": "0",
            "STEAM_ARM64_HIDAPI": "disabled",
            "STEAM_ARM64_REMOVABLE_SOURCE": str(removable_source),
            "STEAM_ARM64_REMOVABLE_TARGET": str(removable_target),
            "STEAM_ARM64_REMOVABLE_STEAMAPPS": str(
                base / "removable-library-steamapps"
            ),
            "STEAM_ARM64_REMOVABLE_COMMON": str(
                removable_source / "steamapps" / "common"
            ),
            "STEAM_ARM64_REMOVABLE_COMPATDATA": str(
                base / "removable-library-compatdata"
            ),
            "STEAM_ARM64_REMOVABLE_DOWNLOADS": str(
                base / "removable-library-downloads"
            ),
        }
    )
    if capture_plan is not None:
        environment["STEAM_ARM64_BWRAP_CAPTURE_PLAN"] = str(capture_plan)
    if bvb_vulkan:
        environment["STEAM_ARM64_BVB_VULKAN"] = "1"
    executable_name = "TombRaider.exe" if game_name == "Tomb Raider" else "Game.exe"
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--fixture-argument",
            str(removable_source),
            str(
                removable_source
                / "steamapps"
                / "common"
                / game_name
                / executable_name
            ),
            f"{removable_source}-lookalike/Game.exe",
        ],
        env=environment,
        cwd=game_directory,
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


def run_capture_preflight(
    prefix: Path, base: Path, output: Path
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BWRAP_CHECK": "1",
            "STEAM_ARM64_BWRAP_CAPTURE_PLAN": str(output),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run_direct_preflight(prefix: Path, base: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PREFIX": str(prefix),
            "STEAM_ARM64_BASE": str(base),
            "STEAM_ARM64_NATIVE_BWRAP_CHECK": "1",
            "STEAM_ARM64_BWRAP_DIRECT": "1",
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run_rejected_preflight(
    prefix: Path, base: Path, proot_dir: Path
) -> subprocess.CompletedProcess[str]:
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
        assert "SDL_JOYSTICK_HIDAPI=0" not in bwrap
        assert "STEAM_ARM64_HIDAPI=disabled" not in bwrap
        assert route in bwrap
        guest_boundary = bwrap.index("--", bwrap.index("--shared-tmp"))
        assert bwrap[guest_boundary + 1 : guest_boundary + 5] == [
            "/usr/bin/env",
            f"HOME={base / 'native-home'}",
            f"PWD={base / 'removable-library/steamapps/common/Game'}",
            route,
        ]
        work_dir = bwrap.index("--work-dir")
        assert bwrap[work_dir + 1] == str(
            base / "removable-library/steamapps/common/Game"
        )
        assert f"PWD={base / 'removable-library/steamapps/common/Game'}" in bwrap
        assert (
            f"STEAM_ARM64_HOST_VK_DRIVER_FILES="
            f"{base / 'mesa-kgsl/icd.d/freedreno-private.json'}"
        ) in bwrap
        assert bwrap[-4:] == [
            "--fixture-argument",
            str(base / "removable-library"),
            str(base / "removable-library/steamapps/common/Game/Game.exe"),
            f"{base.parent / 'fixture-storage'}-lookalike/Game.exe",
        ]

        bvb = run_bridge(prefix, base, "bwrap", bvb_vulkan=True)
        assert (
            f"STEAM_ARM64_HOST_VK_DRIVER_FILES="
            f"{base / 'bvb/icd.d/bvb_icd.aarch64.json'}"
        ) in bvb

        runtime = run_bridge(prefix, base, "runtime")
        assert f"PRESSURE_VESSEL_BWRAP={route}" in runtime
        assert f"HOME={base / 'native-home'}" in runtime
        assert runtime_entry in runtime
        guest_boundary = runtime.index("--", runtime.index("--shared-tmp"))
        assert runtime[guest_boundary + 1 : guest_boundary + 5] == [
            "/usr/bin/env",
            f"HOME={base / 'native-home'}",
            f"PWD={base / 'removable-library/steamapps/common/Game'}",
            runtime_entry,
        ]
        work_dir = runtime.index("--work-dir")
        assert runtime[work_dir + 1] == str(
            base / "removable-library/steamapps/common/Game"
        )
        assert runtime[-4:] == [
            "--fixture-argument",
            str(base / "removable-library"),
            str(base / "removable-library/steamapps/common/Game/Game.exe"),
            f"{base.parent / 'fixture-storage'}-lookalike/Game.exe",
        ]

        capture_output = base / "logs" / "runtime-plans" / "fixture.json"
        capture_runtime = run_bridge(prefix, base, "runtime", capture_output)
        assert f"STEAM_ARM64_BASE={base}" in capture_runtime
        assert f"STEAM_ARM64_BWRAP_CAPTURE_PLAN={capture_output}" in capture_runtime
        assert (
            f"STEAM_ARM64_REAL_BWRAP="
            f"{base / 'compat-bin/capture-pressure-vessel-plan.py'}"
        ) in capture_runtime
        assert (
            f"STEAM_ARM64_CAPTURE_REAL_BWRAP="
            f"{base / 'runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap'}"
        ) in capture_runtime

        selected_proot = base / "src" / "native-profile" / "src"
        preflight = run_preflight(prefix, base, selected_proot)
        assert f"proot={selected_proot / 'proot'}" in preflight
        assert "native game boundary preflight: PASS" in preflight

        captured = run_capture_preflight(prefix, base, capture_output)
        assert captured.returncode == 0, captured.stderr
        assert f"real_bwrap={base / 'compat-bin/capture-pressure-vessel-plan.py'}" in captured.stdout
        assert f"capture_plan={capture_output}" in captured.stdout
        assert (
            f"capture_real_bwrap="
            f"{base / 'runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap'}"
        ) in captured.stdout

        direct = run_direct_preflight(prefix, base)
        assert direct.returncode == 0, direct.stderr
        assert "direct_dispatch=1" in direct.stdout
        assert (
            f"real_bwrap={base / 'compat-bin/pressure-vessel-direct-dispatch.py'}"
        ) in direct.stdout
        assert (
            f"direct_real_bwrap="
            f"{base / 'runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap'}"
        ) in direct.stdout

        outside_capture = run_capture_preflight(
            prefix, base, base.parent / "outside.json"
        )
        assert outside_capture.returncode == 125
        assert "new safe JSON path" in outside_capture.stderr

        capture_output.parent.mkdir(parents=True)
        capture_output.write_text("existing\n", encoding="utf-8")
        existing_capture = run_capture_preflight(prefix, base, capture_output)
        assert existing_capture.returncode == 125
        assert "new safe JSON path" in existing_capture.stderr

        bridge_source = SCRIPT.read_text(encoding="utf-8")
        assert "TGCOMPAT_EXEC_LD_PRELOAD" in bridge_source
        assert "TGCOMPAT_EXEC_SHELL" in bridge_source
        assert "TGCOMPAT_EXEC_PATH_FROM" in bridge_source
        assert "TGCOMPAT_EXEC_PATH_TO" in bridge_source

        entry_source = ENTRY_SOURCE.read_text(encoding="utf-8")
        assert '"TGCOMPAT_EXEC_SHELL"' in entry_source
        assert '"TGCOMPAT_EXEC_PATH_FROM"' in entry_source
        assert '"TGCOMPAT_EXEC_PATH_TO"' in entry_source
        assert 'setenv ("PATH", safe_path, 1)' in entry_source
        assert "tombraider-direct-dxvk-bind.state" not in bridge_source

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
