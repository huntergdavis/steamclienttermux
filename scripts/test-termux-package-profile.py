#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


SCRIPT = Path(__file__).with_name("setup-steam-stack.py")
PROFILE = SCRIPT.parents[1] / "config/termux-setup-profile.json"
SPEC = importlib.util.spec_from_file_location("steam_stack_packages", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def expect_failure(callback, phrase: str) -> None:
    try:
        callback()
    except MODULE.SetupError as error:
        assert phrase in str(error), str(error)
    else:
        raise AssertionError(f"expected failure containing {phrase!r}")


def main() -> None:
    profile = MODULE.load_package_profile(PROFILE)
    groups = MODULE.package_groups(profile)
    assert [group_id for group_id, _packages in groups] == [
        "repositories",
        "build-and-runtime",
    ]
    packages = [package for _group, values in groups for package in values]
    assert len(packages) == len(set(packages))
    assert {"x11-repo", "glibc-repo", "termux-x11-nightly", "glibc-runner"}.issubset(
        packages
    )
    assert profile["platform"]["graphics"] == {
        "implemented": "qualcomm-adreno-kgsl-turnip",
        "other_gpu_families": "profile-required",
    }
    plan = MODULE.render_dependency_plan(profile)
    assert "pkg install -y x11-repo glibc-repo" in plan
    assert "pkg install -y bash binutils clang cmake" in plan
    assert "OTHER_GPU_FAMILIES=profile-required" in plan

    passed = MODULE.dependency_report(profile, lambda package: f"test-{package}")
    assert passed["status"] == "pass" and passed["missing"] == []
    failed = MODULE.dependency_report(
        profile, lambda package: None if package in ("glibc-runner", "xdotool") else "1"
    )
    assert failed["status"] == "fail"
    assert failed["missing"] == ["glibc-runner", "xdotool"]

    cli_profile = subprocess.run(
        [str(SCRIPT), "dependencies", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(cli_profile.stdout) == profile

    with tempfile.TemporaryDirectory(prefix="termux-package-profile-test.") as directory:
        root = Path(directory)
        duplicate = json.loads(PROFILE.read_text(encoding="utf-8"))
        duplicate["install_groups"][1]["packages"].append("x11-repo")
        duplicate_path = root / "duplicate.json"
        duplicate_path.write_text(json.dumps(duplicate), encoding="utf-8")
        expect_failure(
            lambda: MODULE.load_package_profile(duplicate_path),
            "duplicate Termux package",
        )

        undeclared = json.loads(PROFILE.read_text(encoding="utf-8"))
        undeclared["required_commands"]["false-command"] = "missing-package"
        undeclared_path = root / "undeclared.json"
        undeclared_path.write_text(json.dumps(undeclared), encoding="utf-8")
        expect_failure(
            lambda: MODULE.load_package_profile(undeclared_path),
            "invalid command/package mapping",
        )

    print("Termux package profile tests: PASS")


if __name__ == "__main__":
    main()
