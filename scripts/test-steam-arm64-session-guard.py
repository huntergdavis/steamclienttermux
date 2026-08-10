#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "bin" / "steam-arm64-session-guard.py"


def load_guard():
    spec = importlib.util.spec_from_file_location("steam_arm64_session_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_guard(*arguments, input_data=None, stdout=subprocess.PIPE):
    return subprocess.run(
        [sys.executable, str(GUARD), *map(str, arguments)],
        input=input_data,
        stdout=stdout,
        stderr=subprocess.PIPE,
        check=False,
    )


def assert_dev_null(path):
    assert path.is_symlink()
    assert os.readlink(path) == "/dev/null"


def test_crash_modes():
    for value in ("", "0"):
        result = run_guard("crash-mode", value)
        assert result.returncode == 0, result.stderr
        assert result.stdout == b"disabled\n"
    result = run_guard("crash-mode", "1")
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"enabled\n"
    for value in ("false", "00", "2", "yes", "-1"):
        result = run_guard("crash-mode", value)
        assert result.returncode == 2
        assert b"must be unset, 0, or 1" in result.stderr

    # The outer PRoot reads the caller's environment before guest --env
    # handling. Both launchers must actively remove disabled values.
    for script in (
        REPO_ROOT / "bin" / "steam-arm",
        REPO_ROOT / "scripts" / "run-ea-link2ea-direct.sh",
    ):
        source = script.read_text()
        assert "export PROOT_CRASH_LOG=1" in source
        assert "unset PROOT_CRASH_LOG" in source
        assert 'if [[ "$crash_log_mode" == enabled ]]' in source
        assert 'PROOT_CRASH_LOG=$PROOT_CRASH_LOG' not in source


def test_free_space(module, temporary):
    logs = temporary / "logs"
    logs.mkdir()
    module.ensure_free_space(logs, 1_000, 500, available=1_500)
    try:
        module.ensure_free_space(logs, 1_000, 500, available=1_499)
    except RuntimeError as error:
        assert "1499 bytes available, 1500 required" in str(error)
    else:
        raise AssertionError("free-space floor accepted an undersized filesystem")

    result = run_guard(
        "preflight",
        "--client-root",
        temporary / "client-invalid",
        "--logs-dir",
        logs,
        "--min-free-bytes",
        "invalid",
        "--log-cap-bytes",
        "512",
        "--stdout-cap-bytes",
        "512",
        "--steam-running",
        "no",
    )
    assert result.returncode == 2
    assert b"must be a base-10 integer" in result.stderr

    for option in ("--log-cap-bytes", "--stdout-cap-bytes"):
        arguments = {
            "--log-cap-bytes": "512",
            "--stdout-cap-bytes": "512",
        }
        arguments[option] = "255"
        result = run_guard(
            "preflight",
            "--client-root",
            temporary / f"client-{option}",
            "--logs-dir",
            logs,
            "--min-free-bytes",
            "0",
            "--log-cap-bytes",
            arguments["--log-cap-bytes"],
            "--stdout-cap-bytes",
            arguments["--stdout-cap-bytes"],
            "--steam-running",
            "no",
        )
        assert result.returncode == 2
        assert b"must be at least 256 bytes" in result.stderr

    # The actual CLI must reject a low-space launch before replacing CEF state.
    low_space_client = temporary / "low-space-client"
    live_candidate = low_space_client / module.NOISY_LOG_RELATIVE_PATHS[0]
    live_candidate.parent.mkdir(parents=True)
    live_candidate.write_text("preserve-before-space-check")
    result = run_guard(
        "preflight",
        "--client-root",
        low_space_client,
        "--logs-dir",
        logs,
        "--min-free-bytes",
        str(1 << 62),
        "--log-cap-bytes",
        "512",
        "--stdout-cap-bytes",
        "512",
        "--steam-running",
        "no",
    )
    assert result.returncode == 2
    assert b"insufficient free space" in result.stderr
    assert live_candidate.read_text() == "preserve-before-space-check"
    peer = low_space_client / module.NOISY_LOG_RELATIVE_PATHS[1]
    assert not peer.exists() and not peer.is_symlink()


def test_cef_states(module, temporary):
    # Correct links are idempotent even while Steam is running.
    correct = temporary / "correct"
    for relative in module.NOISY_LOG_RELATIVE_PATHS:
        path = correct / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to("/dev/null")
    module.prepare_noisy_logs(correct, steam_running=True)
    for relative in module.NOISY_LOG_RELATIVE_PATHS:
        assert_dev_null(correct / relative)

    # Any incorrect live state fails before either path is changed.
    live = temporary / "live"
    first = live / module.NOISY_LOG_RELATIVE_PATHS[0]
    second = live / module.NOISY_LOG_RELATIVE_PATHS[1]
    first.parent.mkdir(parents=True)
    first.write_text("active-writer-offset-must-survive")
    try:
        module.prepare_noisy_logs(live, steam_running=True)
    except RuntimeError as error:
        assert "Steam is already running" in str(error)
    else:
        raise AssertionError("live regular CEF log was accepted")
    assert first.read_text() == "active-writer-offset-must-survive"
    assert not second.exists() and not second.is_symlink()

    # Missing and closed regular files are the only replaceable stopped states.
    stopped = temporary / "stopped"
    regular = stopped / module.NOISY_LOG_RELATIVE_PATHS[0]
    regular.parent.mkdir(parents=True)
    regular.write_bytes(b"closed-log")
    module.prepare_noisy_logs(stopped, steam_running=False)
    for relative in module.NOISY_LOG_RELATIVE_PATHS:
        assert_dev_null(stopped / relative)

    # Wrong links and non-regular types fail before a valid peer is touched.
    for kind in ("wrong-link", "directory", "fifo"):
        root = temporary / kind
        unexpected = root / module.NOISY_LOG_RELATIVE_PATHS[0]
        peer = root / module.NOISY_LOG_RELATIVE_PATHS[1]
        unexpected.parent.mkdir(parents=True)
        peer.parent.mkdir(parents=True)
        peer.write_text("peer-must-survive")
        if kind == "wrong-link":
            unexpected.symlink_to("/tmp/not-dev-null")
        elif kind == "directory":
            unexpected.mkdir()
        else:
            os.mkfifo(unexpected)
        try:
            module.prepare_noisy_logs(root, steam_running=False)
        except RuntimeError as error:
            assert "unexpected CEF log path" in str(error)
        else:
            raise AssertionError(f"unexpected {kind} CEF path was accepted")
        assert peer.read_text() == "peer-must-survive"
        assert not peer.is_symlink()


def test_stream_caps_and_drain(temporary):
    cap = 512
    payload = bytes(range(256)) * 6
    log = temporary / "bounded.log"
    log.touch(mode=0o600)
    sentinel = temporary / "producer-completed"
    producer = (
        "import os, pathlib, sys; "
        f"os.write(1, {payload!r}); "
        f"pathlib.Path({str(sentinel)!r}).write_text('drained'); "
        "raise SystemExit(23)"
    )
    command = (
        "set -o pipefail; "
        f"{shlex.quote(sys.executable)} -c {shlex.quote(producer)} 2>&1 | "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD))} stream "
        f"--log {shlex.quote(str(log))} --log-cap-bytes {cap} "
        f"--stdout-cap-bytes {cap}"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 23
    assert sentinel.read_text() == "drained"
    assert len(log.read_bytes()) <= cap
    assert len(result.stdout) <= cap
    assert b"canonical log truncated" in log.read_bytes()
    assert b"mirrored stdout truncated" in result.stdout

    # Closing mirrored stdout must not close the input pipe or SIGPIPE a child.
    closed_log = temporary / "closed-stdout.log"
    closed_log.touch(mode=0o600)
    closed_sentinel = temporary / "closed-stdout-completed"
    producer = (
        "import os, pathlib; "
        f"os.write(1, {payload!r}); "
        f"pathlib.Path({str(closed_sentinel)!r}).write_text('drained')"
    )
    command = (
        "set -o pipefail; "
        f"{shlex.quote(sys.executable)} -c {shlex.quote(producer)} | "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(GUARD))} stream "
        f"--log {shlex.quote(str(closed_log))} --log-cap-bytes {cap} "
        f"--stdout-cap-bytes {cap} >&-"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert closed_sentinel.read_text() == "drained"
    assert len(closed_log.read_bytes()) <= cap
    assert b"canonical log truncated" in closed_log.read_bytes()


def test_secure_unique_logs(temporary):
    logs = temporary / "unique"
    logs.mkdir()
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(GUARD),
                "create-log",
                "--logs-dir",
                str(logs),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _index in range(24)
    ]
    paths = []
    for process in processes:
        stdout, stderr = process.communicate()
        assert process.returncode == 0, stderr
        paths.append(Path(stdout.decode().strip()))
    assert len(set(paths)) == len(paths)
    for path in paths:
        assert path.parent == logs
        assert path.is_file() and not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def main():
    module = load_guard()
    test_crash_modes()
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        test_free_space(module, temporary)
        test_cef_states(module, temporary)
        test_stream_caps_and_drain(temporary)
        test_secure_unique_logs(temporary)
    print("Steam ARM64 session guard tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
