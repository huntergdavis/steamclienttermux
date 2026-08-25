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

    with tempfile.TemporaryDirectory(prefix="termux-dependency-install-test.") as directory:
        root = Path(directory)
        installed: dict[str, str] = {}
        calls: list[list[str]] = []

        def query(package: str) -> str | None:
            return installed.get(package)

        def runner(arguments: list[str]) -> int:
            calls.append(arguments)
            assert arguments[:3] == ["/fake/pkg", "install", "-y"]
            for package in arguments[3:]:
                installed[package] = f"installed-{package}"
            return 0

        base = root / "stack"
        result = MODULE.install_dependencies(
            profile, PROFILE, base, Path("/fake/pkg"), query=query, runner=runner
        )
        assert result == "installed"
        assert len(calls) == 2
        assert calls[0][3:] == ["x11-repo", "glibc-repo"]
        assert set(calls[1][3:]) == set(groups[1][1])
        receipt, transaction = MODULE.dependency_state_paths(base)
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        assert payload["package_count"] == len(packages)
        assert payload["initially_missing"] == packages
        assert payload["removal_policy"] == "preserve shared Termux packages by default"
        assert not transaction.exists()
        assert (
            MODULE.install_dependencies(
                profile, PROFILE, base, Path("/fake/pkg"), query=query, runner=runner
            )
            == "already-ready"
        )
        assert len(calls) == 2

        interrupted_base = root / "interrupted"
        interrupted_installed: dict[str, str] = {}
        failed_once = False

        def interrupted_query(package: str) -> str | None:
            return interrupted_installed.get(package)

        def interrupted_runner(arguments: list[str]) -> int:
            nonlocal failed_once
            if arguments[3] not in ("x11-repo", "glibc-repo") and not failed_once:
                failed_once = True
                return 29
            for package in arguments[3:]:
                interrupted_installed[package] = "1"
            return 0

        expect_failure(
            lambda: MODULE.install_dependencies(
                profile,
                PROFILE,
                interrupted_base,
                Path("/fake/pkg"),
                query=interrupted_query,
                runner=interrupted_runner,
            ),
            "status 29",
        )
        _receipt, interrupted_transaction = MODULE.dependency_state_paths(
            interrupted_base
        )
        assert interrupted_transaction.is_file()
        assert (
            MODULE.install_dependencies(
                profile,
                PROFILE,
                interrupted_base,
                Path("/fake/pkg"),
                query=interrupted_query,
                runner=interrupted_runner,
            )
            == "installed"
        )
        assert not interrupted_transaction.exists()

    missing_confirmation = subprocess.run(
        [str(SCRIPT), "dependencies", "--install"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert missing_confirmation.returncode != 0
    assert "requires explicit --yes" in missing_confirmation.stderr

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
