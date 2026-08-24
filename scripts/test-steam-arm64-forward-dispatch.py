#!/usr/bin/env python3
"""Exact contracts for strict and authenticated fast Steam forwarding."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
DISPATCHER = REPO_ROOT / "bin" / "steam-arm64-forward-dispatch"
MATCHER = REPO_ROOT / "bin" / "steam-arm64-process-match.sh"
PIPE_FORWARDER = REPO_ROOT / "scripts" / "steam-pipe-forward.py"
PID = 4217
START_TICKS = 998877


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def nul_record(path: Path, values: list[str]) -> None:
    path.write_bytes(b"\0".join(value.encode() for value in values) + b"\0")


def stat_record(pid: int, start_ticks: int) -> str:
    # State is field 3; 18 zero fields place starttime at field 22.
    return f"{pid} (steam main) S " + " ".join(["0"] * 18) + f" {start_ticks}\n"


def make_process(
    proc_root: Path,
    pid: int,
    loader: Path,
    target: Path,
    library_path: str,
    environment: list[str],
    *,
    start_ticks: int = START_TICKS,
    status_uid: int | None = None,
    argv_loader: Path | None = None,
) -> None:
    process = proc_root / str(pid)
    process.mkdir()
    (process / "stat").write_text(stat_record(pid, start_ticks), encoding="utf-8")
    uid = os.getuid() if status_uid is None else status_uid
    (process / "status").write_text(
        f"Name:\tsteam\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )
    (process / "exe").symlink_to(loader)
    nul_record(
        process / "cmdline",
        [
            str(argv_loader or loader),
            "--inhibit-cache",
            "--library-path",
            library_path,
            "--argv0",
            str(target),
            str(target),
            "-silent",
        ],
    )
    nul_record(process / "environ", environment)


def phase_events(
    stderr: str, mode: str, expected_clock: str = "monotonic"
) -> list[str]:
    records = [
        line
        for line in stderr.splitlines()
        if line.startswith("steam-arm64-forward-phase ")
    ]
    assert records, stderr
    times: list[int] = []
    events: list[str] = []
    for record in records:
        assert "version=2" in record
        assert f"mode={mode}" in record
        match = re.search(
            r" event=([a-z0-9_]+) clock=(monotonic|realtime) "
            r"timestamp_cs=([0-9]+) ",
            record,
        )
        assert match, record
        assert match.group(2) == expected_clock, record
        events.append(match.group(1))
        times.append(int(match.group(3)))
    assert times == sorted(times), times
    return events


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="steam-forward-dispatch.") as temporary:
        home = Path(temporary)
        base = home / "base"
        compat_bin = base / "compat-bin"
        compat_bin.mkdir(parents=True)
        shutil.copy2(MATCHER, compat_bin / MATCHER.name)
        (compat_bin / MATCHER.name).chmod(0o600)
        shutil.copy2(PIPE_FORWARDER, compat_bin / PIPE_FORWARDER.name)
        (compat_bin / PIPE_FORWARDER.name).chmod(0o700)

        client_root = base / "client"
        client = client_root / "steamrtarm64"
        target = client / "steam"
        executable(target, "#!/bin/sh\nexit 0\n")
        (client / "libs").mkdir()
        (client_root / "linuxarm64").mkdir()

        candidate = home / ".local/share/tgcompat/glibc/revision"
        loader = candidate / "lib/ld-linux-aarch64.so.1"
        capture = home / "fast-capture"
        executable(
            loader,
            "#!/bin/bash\n"
            'printf "HOME=%s\\n" "$HOME" > "$CAPTURE"\n'
            'printf "DISPLAY=%s\\n" "$DISPLAY" >> "$CAPTURE"\n'
            'printf "control=%s\\n" "${STEAM_ARM64_FORWARD_BOOTSTRAP-}" >> "$CAPTURE"\n'
            'printf "proc_root=%s\\n" "${STEAM_ARM64_PROC_ROOT-}" >> "$CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$CAPTURE"\n',
        )

        prefix = home / "prefix"
        linux_root = prefix / "var/lib/proot-distro/containers/debian/rootfs"
        linux_lib = linux_root / "usr/lib/aarch64-linux-gnu"
        (linux_lib / "pulseaudio").mkdir(parents=True)
        (linux_root / "usr/lib").mkdir(exist_ok=True)
        mesa_lib = base / "mesa-kgsl/usr/lib/aarch64-linux-gnu"
        mesa_lib.mkdir(parents=True)
        icd = base / "mesa-kgsl/icd.d/freedreno-private.json"
        icd.parent.mkdir(parents=True)
        icd.write_text("{}\n", encoding="utf-8")

        strict_capture = home / "strict-capture"
        strict_launcher = home / "strict-launcher"
        executable(
            strict_launcher,
            "#!/bin/bash\n"
            'printf "control=%s\\n" "${STEAM_ARM64_FORWARD_BOOTSTRAP-}" > "$STRICT_CAPTURE"\n'
            'printf "arg=%s\\n" "$@" >> "$STRICT_CAPTURE"\n',
        )

        preload_member = "/lib/x86_64-linux-gnu/libm.so.6"
        preload = ":".join([preload_member] * 4)
        library_path = ":".join(
            [
                str(candidate / "lib"),
                str(client),
                str(client / "libs"),
                str(client_root / "linuxarm64"),
                str(mesa_lib),
                str(linux_lib),
                str(linux_lib / "pulseaudio"),
                str(linux_root / "usr/lib"),
            ]
        )
        native_home = base / "native-home"
        runtime_dir = base / "run/native-steam"
        native_home.mkdir()
        native_home.chmod(0o700)
        steam_private = native_home / ".steam"
        steam_private.mkdir(mode=0o700)
        steam_pipe = steam_private / "steam.pipe"
        os.mkfifo(steam_pipe, mode=0o600)
        runtime_dir.mkdir(parents=True)
        login_state = client_root / "config/loginusers.vdf"
        login_state.parent.mkdir()
        login_state.write_text('"RememberPassword" "1"\n', encoding="utf-8")
        cookie_state = native_home / "steam-login-cookie"
        cookie_state.write_text("preserve-authentication\n", encoding="utf-8")
        protected_state = {
            login_state: login_state.read_bytes(),
            cookie_state: cookie_state.read_bytes(),
        }
        fake_environment = [
            f"HOME={native_home}",
            "DISPLAY=:0",
            f"STEAM_ARM64_BASE={base}",
            f"TGCOMPAT_LD_SO={loader}",
            f"TGCOMPAT_LIBRARY_PATH={library_path}",
            f"TGCOMPAT_PROC_SELF_EXE={target}",
            f"LD_PRELOAD={preload}",
            f"TGCOMPAT_EXEC_LD_PRELOAD={preload}",
            f"STEAM_COMPAT_CLIENT_INSTALL_PATH={client_root}",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"VK_DRIVER_FILES={icd}",
            f"CAPTURE={capture}",
            "STEAM_ARM64_FORWARD_BOOTSTRAP=smuggled",
            "STEAM_ARM64_PROC_ROOT=/smuggled",
        ]
        proc_root = home / "proc"
        proc_root.mkdir()
        make_process(
            proc_root,
            PID,
            loader,
            target,
            library_path,
            fake_environment,
        )

        common_environment = {
            **os.environ,
            "HOME": str(home),
            "PREFIX": str(prefix),
            "DISPLAY": ":0",
            "STEAM_ARM64_BASE": str(base),
            "TGCOMPAT_GLIBC_ROOT": str(candidate),
            "STEAM_ARM64_PROC_ROOT": str(proc_root),
            "TGCOMPAT_EXEC_SHIM": preload_member,
            "TGCOMPAT_ROBUST_SHIM": preload_member,
            "STEAM_ARM64_TMP_SHIM": preload_member,
            "TERMUX_EXEC_GLIBC": preload_member,
            "STRICT_CAPTURE": str(strict_capture),
        }
        arguments = ["-silent", "-applaunch", "203160", "two words"]
        command = [
            "bash",
            str(DISPATCHER),
            "--steam-pid",
            str(PID),
            "--steam-start-ticks",
            str(START_TICKS),
            "--strict-launcher",
            str(strict_launcher),
            "--",
            *arguments,
        ]

        strict_environment = common_environment.copy()
        strict_environment.pop("STEAM_ARM64_FORWARD_BOOTSTRAP", None)
        strict = subprocess.run(
            command,
            env=strict_environment,
            text=True,
            capture_output=True,
            check=True,
        )
        assert phase_events(strict.stderr, "strict") == [
            "request",
            "strict_launch",
            "complete",
        ]
        assert strict_capture.read_text(encoding="utf-8").splitlines() == [
            "control=",
            *[f"arg={argument}" for argument in arguments],
        ]

        # Android can deny /proc/uptime despite a visible procfs entry. The
        # zero-subprocess realtime fallback must preserve all phase records.
        unreadable_clock = subprocess.run(
            command,
            env={
                **strict_environment,
                "STEAM_ARM64_UPTIME_FILE": str(home / "missing-uptime"),
            },
            text=True,
            capture_output=True,
            check=True,
        )
        assert phase_events(
            unreadable_clock.stderr, "strict", expected_clock="realtime"
        ) == ["request", "strict_launch", "complete"]

        pipe_reader = os.open(steam_pipe, os.O_RDONLY | os.O_NONBLOCK)
        fast = subprocess.run(
            command,
            env={**common_environment, "STEAM_ARM64_FORWARD_BOOTSTRAP": "fast"},
            text=True,
            capture_output=True,
            check=True,
        )
        assert phase_events(fast.stderr, "fast") == [
            "request",
            "fast_inspect",
            "session_valid",
            "pipe_launch",
            "complete",
        ], fast.stderr
        pipe_payload = b""
        for _ in range(100):
            pipe_payload += os.read(pipe_reader, 4096)
            if pipe_payload.endswith(b"\n"):
                break
            time.sleep(0.01)
        os.close(pipe_reader)
        assert pipe_payload.decode() == (
            f"{target} -no-cef-sandbox -cef-disable-gpu "
            "-chromeosnopreallocate -noverifyfiles -silent "
            "-applaunch 203160 'two words'\n"
        )
        assert not capture.exists()

        # A validated FIFO with no live reader retains the exact existing
        # second-client path rather than silently dropping the request.
        fast_fallback = subprocess.run(
            command,
            env={**common_environment, "STEAM_ARM64_FORWARD_BOOTSTRAP": "fast"},
            text=True,
            capture_output=True,
            check=True,
        )
        assert phase_events(fast_fallback.stderr, "fast") == [
            "request",
            "fast_inspect",
            "session_valid",
            "pipe_launch",
            "pipe_fallback",
            "fast_launch",
            "complete",
        ], fast_fallback.stderr
        fast_lines = capture.read_text(encoding="utf-8").splitlines()
        assert fast_lines[:4] == [
            f"HOME={native_home}",
            "DISPLAY=:0",
            "control=",
            "proc_root=",
        ]
        expected_loader_arguments = [
            "--inhibit-cache",
            "--library-path",
            library_path,
            "--argv0",
            str(target),
            str(target),
            "-no-cef-sandbox",
            "-cef-disable-gpu",
            "-chromeosnopreallocate",
            "-noverifyfiles",
            *arguments,
        ]
        assert fast_lines[4:] == [
            f"arg={argument}" for argument in expected_loader_arguments
        ]

        def assert_fallback(reason: str) -> None:
            strict_capture.unlink(missing_ok=True)
            result = subprocess.run(
                command,
                env={**common_environment, "STEAM_ARM64_FORWARD_BOOTSTRAP": "fast"},
                text=True,
                capture_output=True,
                check=True,
            )
            events = phase_events(result.stderr, "fast")
            assert events == [
                "request",
                "fast_inspect",
                "fast_fallback",
                "strict_launch",
                "complete",
            ]
            assert f"detail=reason={reason}" in result.stderr, result.stderr
            assert strict_capture.exists()

        # Stale start ticks reject PID reuse before any fast execution.
        stale_command = command.copy()
        stale_command[stale_command.index(str(START_TICKS))] = str(START_TICKS + 1)
        stale = subprocess.run(
            stale_command,
            env={**common_environment, "STEAM_ARM64_FORWARD_BOOTSTRAP": "fast"},
            text=True,
            capture_output=True,
            check=True,
        )
        assert "detail=reason=stale" in stale.stderr

        status = proc_root / str(PID) / "status"
        status.write_text("Name:\tsteam\nUid:\t1\t1\t1\t1\n", encoding="utf-8")
        assert_fallback("uid")
        status.write_text(
            f"Name:\tsteam\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n",
            encoding="utf-8",
        )

        wrong_profile = [
            entry if not entry.startswith("HOME=") else f"HOME={home / 'wrong-profile'}"
            for entry in fake_environment
        ]
        nul_record(proc_root / str(PID) / "environ", wrong_profile)
        assert_fallback("profile")
        nul_record(proc_root / str(PID) / "environ", fake_environment)

        wrong_loader = home / "wrong-loader"
        executable(wrong_loader, "#!/bin/sh\nexit 0\n")
        process_exe = proc_root / str(PID) / "exe"
        process_exe.unlink()
        process_exe.symlink_to(wrong_loader)
        assert_fallback("loader")
        process_exe.unlink()
        process_exe.symlink_to(loader)

        nul_record(
            proc_root / str(PID) / "cmdline",
            [
                str(wrong_loader),
                "--inhibit-cache",
                "--library-path",
                library_path,
                "--argv0",
                str(target),
                str(target),
            ],
        )
        assert_fallback("ambiguous")

        make_cmdline = [
            str(loader),
            "--inhibit-cache",
            "--library-path",
            library_path,
            "--argv0",
            str(target),
            str(target),
            "-silent",
        ]
        nul_record(proc_root / str(PID) / "cmdline", make_cmdline)

        make_process(
            proc_root,
            PID + 1,
            loader,
            target,
            library_path,
            fake_environment,
            start_ticks=START_TICKS + 10,
        )
        assert_fallback("ambiguous")

        for path, expected in protected_state.items():
            assert path.read_bytes() == expected, path

        installer = (REPO_ROOT / "scripts/install-project-files.sh").read_text(
            encoding="utf-8"
        )
        assert '"$repo_root/bin/steam-arm64-forward-dispatch"' in installer
        assert '"$base/compat-bin/steam-arm64-forward-dispatch" 700' in installer
        assert '"$repo_root/scripts/steam-pipe-forward.py"' in installer
        assert '"$base/compat-bin/steam-pipe-forward.py" 700' in installer

    print("Steam authenticated warm-forward dispatcher tests: PASS")


if __name__ == "__main__":
    main()
