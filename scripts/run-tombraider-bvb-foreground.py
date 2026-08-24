#!/usr/bin/env python3

"""Launch the Tomb Raider BVB probe from an Android top-app lineage."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any


TERMUX_PREFIX = Path("/data/data/com.termux/files/usr")
TERMUX_PACKAGE = "com.termux"
RUN_COMMAND_COMPONENT = "com.termux/.app.RunCommandService"
RUN_COMMAND_ACTION = "com.termux.RUN_COMMAND"
X11_COMPONENT = "com.termux.x11/.MainActivity"
TOP_APP = "/top-app"
PROBE_HANDOFF_MARKER = b"Starting Tomb Raider BVB probe:"
ENV_PREFIXES = ("BVB_", "STEAM_", "TOMB_RAIDER_")
ENV_NAMES = {"DISPLAY", "PULSE_SERVER", "XDG_RUNTIME_DIR", "TMPDIR"}


class ForegroundError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ForegroundError(message)


def require_regular(path: Path, label: str, *, executable: bool = False) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ForegroundError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"{label} is not a regular non-symlink file: {path}")
    if executable and not os.access(path, os.X_OK):
        fail(f"{label} is not executable: {path}")


def atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        fail(f"unsafe output parent: {path.parent}")
    descriptor, temporary_text = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_text)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_json(path: Path, document: dict[str, Any]) -> None:
    atomic_write(
        path,
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_cgroups(payload: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in payload.splitlines():
        _index, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, value = remainder.partition(":")
        if not separator:
            continue
        for controller in controllers.split(","):
            if controller:
                result[controller] = value
    return result


def cgroups_at(path: Path) -> dict[str, str]:
    try:
        return parse_cgroups(path.read_text(encoding="ascii"))
    except (FileNotFoundError, PermissionError, UnicodeError, OSError):
        return {}


def require_top_app(path: Path, label: str) -> dict[str, str]:
    groups = cgroups_at(path)
    if groups.get("cpuset") != TOP_APP or groups.get("cpu") != TOP_APP:
        fail(
            f"{label} is not in Android top-app cgroups "
            f"(cpuset={groups.get('cpuset', 'unknown')}, "
            f"cpu={groups.get('cpu', 'unknown')})"
        )
    return groups


def process_start_ticks(stat_payload: str) -> int:
    closing = stat_payload.rfind(") ")
    if closing < 0:
        fail("invalid process stat record")
    fields = stat_payload[closing + 2 :].split()
    if len(fields) < 20 or not fields[19].isdigit():
        fail("process stat record has no valid start time")
    return int(fields[19])


def process_cmdline(path: Path) -> list[str]:
    try:
        return [
            os.fsdecode(token)
            for token in path.read_bytes().split(b"\0")
            if token
        ]
    except (FileNotFoundError, PermissionError, OSError):
        return []


def parse_bounds(value: str) -> tuple[int, int, int, int]:
    fields = value.split(",")
    if len(fields) != 4 or any(not re.fullmatch(r"-?[0-9]{1,5}", item) for item in fields):
        raise argparse.ArgumentTypeError("bounds must be LEFT,TOP,RIGHT,BOTTOM")
    left, top, right, bottom = (int(item) for item in fields)
    if not (-10000 <= left < right <= 10000 and -10000 <= top < bottom <= 10000):
        raise argparse.ArgumentTypeError("bounds are empty or outside the safe range")
    return left, top, right, bottom


def run_checked(command: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ForegroundError(f"command failed to run: {command[0]}: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        fail(f"command failed ({result.returncode}): {' '.join(command)}: {detail}")
    return result


def reload_settings(command: Path) -> None:
    require_regular(command, "Termux settings reload command", executable=True)
    run_checked([str(command)])


class PropertyGuard:
    def __init__(self, path: Path, reload_command: Path):
        self.path = path
        self.reload_command = reload_command
        self.original: bytes | None = None
        self.changed = False

    def enable(self) -> str:
        require_regular(self.path, "Termux properties")
        original = self.path.read_bytes()
        self.original = original
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ForegroundError("Termux properties are not UTF-8") from error
        disabled = re.compile(
            r"(?m)^(?P<indent>[ \t]*)#[ \t]*"
            r"allow-external-apps[ \t]*=[ \t]*true[ \t]*$"
        )
        enabled = re.compile(r"(?m)^[ \t]*allow-external-apps[ \t]*=[ \t]*true[ \t]*$")
        disabled_matches = list(disabled.finditer(text))
        enabled_matches = list(enabled.finditer(text))
        if len(disabled_matches) + len(enabled_matches) != 1:
            fail("termux.properties must contain exactly one true allow-external-apps setting")
        if disabled_matches:
            match = disabled_matches[0]
            replacement = f"{match.group('indent')}allow-external-apps = true"
            candidate = text[: match.start()] + replacement + text[match.end() :]
            atomic_write(
                self.path,
                candidate.encode("utf-8"),
                stat.S_IMODE(self.path.stat().st_mode),
            )
            self.changed = True
            reload_settings(self.reload_command)
        return sha256_bytes(original)

    def restore(self) -> str:
        if self.original is None:
            fail("Termux property guard was not initialized")
        if self.changed:
            atomic_write(self.path, self.original, stat.S_IMODE(self.path.stat().st_mode))
            reload_settings(self.reload_command)
            self.changed = False
        restored = self.path.read_bytes()
        if restored != self.original:
            fail("termux.properties was not restored byte-for-byte")
        return sha256_bytes(restored)


def runcommand_arguments(
    am: Path,
    python: Path,
    tool: Path,
    mode: str,
    value: Path,
    workdir: Path,
) -> list[str]:
    values = [str(tool), mode, str(value)]
    if any("," in item for item in values):
        fail("RunCommand arguments may not contain commas")
    return [
        str(am),
        "startservice",
        "--user",
        "0",
        "-n",
        RUN_COMMAND_COMPONENT,
        "-a",
        RUN_COMMAND_ACTION,
        "--es",
        "com.termux.RUN_COMMAND_PATH",
        str(python),
        "--esa",
        "com.termux.RUN_COMMAND_ARGUMENTS",
        ",".join(values),
        "--es",
        "com.termux.RUN_COMMAND_WORKDIR",
        str(workdir),
        "--ez",
        "com.termux.RUN_COMMAND_BACKGROUND",
        "true",
    ]


def launch_runcommand(command: list[str]) -> None:
    result = run_checked(command)
    output = f"{result.stdout}\n{result.stderr}"
    if "Error:" in output or "SecurityException" in output:
        fail(f"Termux RunCommandService rejected the request: {output.strip()}")


def service_probe(path: Path) -> int:
    groups = require_top_app(
        Path(os.environ.get("TOMB_RAIDER_FOREGROUND_SELF_CGROUP", "/proc/self/cgroup")),
        "RunCommand readiness probe",
    )
    atomic_json(
        path,
        {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "cpuset": groups["cpuset"],
            "cpu": groups["cpu"],
        },
    )
    return 0


def selected_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if name in ENV_NAMES or name.startswith(ENV_PREFIXES)
    }


def child_main(request_directory: Path) -> int:
    request = request_directory / "request.json"
    document = read_json(request)
    if document is None:
        fail(f"foreground request is invalid: {request}")
    probe = Path(str(document.get("probe", "")))
    arguments = document.get("arguments")
    environment = document.get("environment")
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        fail("foreground request arguments are invalid")
    if not isinstance(environment, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in environment.items()
    ):
        fail("foreground request environment is invalid")
    require_regular(probe, "BVB probe", executable=True)
    groups = require_top_app(
        Path(os.environ.get("TOMB_RAIDER_FOREGROUND_SELF_CGROUP", "/proc/self/cgroup")),
        "Activity-owned BVB controller",
    )
    state = request_directory / "state.json"
    result_path = request_directory / "result.json"
    log = Path(str(document.get("log", "")))
    atomic_json(
        state,
        {
            "status": "running",
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "cpuset": groups["cpuset"],
            "cpu": groups["cpu"],
        },
    )
    with contextlib.suppress(FileNotFoundError):
        request.unlink()
    child_environment = dict(os.environ)
    child_environment.update(environment)
    log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if log.parent.is_symlink():
        fail(f"unsafe foreground log parent: {log.parent}")
    with log.open("xb") as output:
        process = subprocess.Popen(
            [str(probe), *arguments],
            env=child_environment,
            cwd=Path.home(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        termination_signal: int | None = None
        termination_deadline = 0.0

        def stop_probe(signum: int, _frame: object) -> None:
            nonlocal termination_signal, termination_deadline
            if termination_signal is None:
                termination_signal = signum
                termination_deadline = time.monotonic() + 10
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)

        signal.signal(signal.SIGINT, stop_probe)
        signal.signal(signal.SIGTERM, stop_probe)
        while True:
            try:
                return_code = process.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if termination_signal is None or time.monotonic() < termination_deadline:
                    continue
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait()
                break
        if termination_signal is not None:
            return_code = 128 + termination_signal
    atomic_json(
        result_path,
        {
            "status": "complete",
            "return_code": return_code,
            "pid": os.getpid(),
            "log": str(log),
        },
    )
    return return_code


def wait_for_document(path: Path, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = read_json(path)
        if document is not None:
            return document
        time.sleep(0.05)
    fail(f"timed out waiting for structured state: {path}")


def validate_child(
    document: dict[str, Any],
    proc_root: Path,
    python: Path,
    tool: Path,
    request: Path,
) -> tuple[int, int]:
    pid = document.get("pid")
    ppid = document.get("ppid")
    if type(pid) is not int or pid <= 0 or type(ppid) is not int or ppid <= 0:
        fail("Activity-owned child reported invalid process IDs")
    process = proc_root / str(pid)
    parent = proc_root / str(ppid)
    groups = require_top_app(process / "cgroup", "Activity-owned BVB controller")
    arguments = process_cmdline(process / "cmdline")
    expected = [str(python), str(tool), "--child", str(request)]
    if arguments[:4] != expected:
        fail(f"Activity-owned child command line changed: {arguments!r}")
    parent_arguments = process_cmdline(parent / "cmdline")
    if not parent_arguments or parent_arguments[0] != TERMUX_PACKAGE:
        fail(
            "Activity-owned child parent is not the Termux Activity process: "
            f"{parent_arguments!r}"
        )
    try:
        start_ticks = process_start_ticks((process / "stat").read_text(encoding="ascii"))
    except (FileNotFoundError, UnicodeError, OSError) as error:
        raise ForegroundError("could not read Activity-owned child identity") from error
    if groups["cpuset"] != document.get("cpuset") or groups["cpu"] != document.get("cpu"):
        fail("Activity-owned child cgroup state changed during validation")
    print(
        "Tomb Raider BVB foreground controller ready: "
        f"pid={pid} parent={ppid} start_ticks={start_ticks} cpuset=/top-app cpu=/top-app",
        flush=True,
    )
    return pid, start_ticks


def adb_shell(adb: Path, serial: str, *arguments: str, timeout: float = 30) -> str:
    return run_checked([str(adb), "-s", serial, "shell", *arguments], timeout=timeout).stdout


def find_x11_task_id(task_dump: str) -> int:
    recent_tasks = task_dump.split("\n  Visible recent tasks", 1)[0]
    records = re.split(r"(?=\n?  \* Recent #[0-9]+: Task\{)", recent_tasks)
    matches: list[int] = []
    for record in records:
        components = (
            "realActivity={com.termux.x11/com.termux.x11.MainActivity}",
            "mActivityComponent=com.termux.x11/.MainActivity",
        )
        if not any(component in record for component in components):
            continue
        match = re.search(r"Recent #[0-9]+: Task\{[^\n]* #([1-9][0-9]{0,9}) ", record)
        if match:
            matches.append(int(match.group(1)))
    if len(set(matches)) != 1:
        fail(f"expected one exact Termux:X11 task, found {sorted(set(matches))}")
    return matches[0]


def process_still_top_app(proc_root: Path, pid: int) -> bool:
    groups = cgroups_at(proc_root / str(pid) / "cgroup")
    return groups.get("cpuset") == TOP_APP and groups.get("cpu") == TOP_APP


def wait_for_result(
    path: Path,
    timeout: float,
    proc_root: Path,
    pid: int,
    expected_start_ticks: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = read_json(path)
        if document is not None:
            return document
        try:
            observed_start_ticks = process_start_ticks(
                (proc_root / str(pid) / "stat").read_text(encoding="ascii")
            )
        except (
            ForegroundError,
            FileNotFoundError,
            PermissionError,
            OSError,
            UnicodeError,
        ):
            fail("Activity-owned BVB controller exited without a structured result")
        if observed_start_ticks != expected_start_ticks:
            fail("Activity-owned BVB controller identity changed before its result")
        time.sleep(0.1)
    fail(f"timed out waiting for the foreground BVB result: {path}")


def probe_handoff_ready(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"foreground log became unsafe: {path}")
    with path.open("rb") as stream:
        if metadata.st_size > 1024 * 1024:
            stream.seek(-(1024 * 1024), os.SEEK_END)
        return PROBE_HANDOFF_MARKER in stream.read()


def promote_x11(adb: Path, serial: str, bounds: tuple[int, int, int, int]) -> int:
    adb_shell(
        adb,
        serial,
        "am",
        "start",
        "--user",
        "0",
        "-W",
        "--windowingMode",
        "5",
        "--activity-reorder-to-front",
        "-n",
        X11_COMPONENT,
    )
    task_dump = adb_shell(adb, serial, "dumpsys", "activity", "recents")
    task_id = find_x11_task_id(task_dump)
    adb_shell(adb, serial, "am", "task", "resize", str(task_id), *(str(value) for value in bounds))
    return task_id


def expand_x11_full_display(
    adb: Path,
    serial: str,
    task_id: int,
    bounds: tuple[int, int, int, int],
    settle_timeout_seconds: float = 30.0,
) -> tuple[int, int]:
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    adb_shell(
        adb,
        serial,
        "am",
        "task",
        "resize",
        str(task_id),
        *(str(value) for value in bounds),
    )
    # Samsung DeX keeps the performance cgroup only while this task remains
    # freeform. Its title-bar expand control removes every decoration without
    # converting the task to Android's demoting fullscreen mode.
    toggle_x = right - round(width * 0.061)
    toggle_y = top + round(height * 0.060)
    adb_shell(adb, serial, "input", "tap", str(toggle_x), str(toggle_y))
    expected = (
        f"Requested w={width} h={height}",
        f"mBounds=Rect({left}, {top} - {right}, {bottom})",
        f"frame=[{left},{top}][{right},{bottom}]",
        "mGivenContentInsets=[0,0][0,0]",
        "mSystemDecorRect=[0,0][0,0]",
    )
    deadline = time.monotonic() + settle_timeout_seconds
    missing = list(expected)
    while time.monotonic() < deadline:
        window_dump = adb_shell(adb, serial, "dumpsys", "window", "windows")
        marker = f"taskId={task_id} "
        start = window_dump.find(marker)
        if start >= 0:
            block_start = window_dump.rfind("  Window #", 0, start)
            block_end = window_dump.find("\n  Window #", start)
            block = window_dump[
                block_start : block_end if block_end >= 0 else None
            ]
            missing = [item for item in expected if item not in block]
            if not missing:
                return toggle_x, toggle_y
        time.sleep(0.1)
    if start < 0:
        fail("Termux:X11 full-display window is absent")
    fail(
        "Termux:X11 did not enter verified borderless full-display mode: "
        + ", ".join(missing)
    )


def restore_x11(adb: Path, serial: str) -> None:
    adb_shell(
        adb,
        serial,
        "am",
        "start",
        "--user",
        "0",
        "-W",
        "--windowingMode",
        "1",
        "--activity-reorder-to-front",
        "-n",
        X11_COMPONENT,
    )


def controller_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the installed Tomb Raider BVB probe in Android top-app cgroups."
    )
    parser.add_argument(
        "--x11-bounds", type=parse_bounds, default=parse_bounds("40,40,520,360")
    )
    parser.add_argument(
        "--x11-fullscreen",
        action="store_true",
        help=(
            "bootstrap Termux:X11 in freeform top-app, then expand it to a "
            "verified borderless full-display surface"
        ),
    )
    parser.add_argument(
        "--x11-fullscreen-bounds",
        type=parse_bounds,
        default=parse_bounds("0,0,2800,1752"),
        help="full-display bounds used after the top-app bootstrap",
    )
    parser.add_argument("--service-settle-seconds", type=float, default=5.0)
    parser.add_argument("--promotion-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--result-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("probe_arguments", nargs=argparse.REMAINDER)
    return parser


def controller_main(arguments: argparse.Namespace) -> int:
    home = Path.home()
    base = Path(os.environ.get("STEAM_ARM64_BASE", home / "steam-arm64"))
    tool = Path(
        os.environ.get(
            "TOMB_RAIDER_FOREGROUND_TOOL",
            base / "compat-bin/run-tombraider-bvb-foreground.py",
        )
    )
    python = Path(
        os.environ.get("TOMB_RAIDER_FOREGROUND_PYTHON", sys.executable)
    ).resolve(strict=True)
    am = Path(os.environ.get("TOMB_RAIDER_FOREGROUND_AM", TERMUX_PREFIX / "bin/am"))
    reload_command = Path(
        os.environ.get(
            "TOMB_RAIDER_FOREGROUND_RELOAD_SETTINGS",
            TERMUX_PREFIX / "bin/termux-reload-settings",
        )
    )
    properties = Path(
        os.environ.get(
            "TOMB_RAIDER_FOREGROUND_PROPERTIES", home / ".termux/termux.properties"
        )
    )
    probe = Path(
        os.environ.get("TOMB_RAIDER_FOREGROUND_PROBE", home / "start-tombraider-bvb-probe")
    )
    proc_root = Path(os.environ.get("TOMB_RAIDER_FOREGROUND_PROC_ROOT", "/proc"))
    adb = Path(os.environ.get("BVB_ADB_COMMAND", TERMUX_PREFIX / "bin/adb"))
    serial = os.environ.get("BVB_ACTIVITY_ADB_SERIAL", "")
    allow_no_x11 = os.environ.get("TOMB_RAIDER_FOREGROUND_ALLOW_NO_X11", "0") == "1"
    require_regular(tool, "foreground controller", executable=True)
    require_regular(python, "Termux Python", executable=True)
    require_regular(am, "Termux Activity manager", executable=True)
    require_regular(probe, "installed BVB probe", executable=True)
    if not allow_no_x11:
        require_regular(adb, "paired ADB client", executable=True)
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", serial):
            fail("BVB_ACTIVITY_ADB_SERIAL must name the paired tablet")
        if run_checked([str(adb), "-s", serial, "get-state"]).stdout.strip() != "device":
            fail("paired ADB device is unavailable")
    run_root = base / "run/bvb-foreground"
    log_root = base / "logs"
    if run_root.is_symlink() or log_root.is_symlink():
        fail("unsafe foreground runtime or log directory")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_directory = run_root / f"{stamp}-{os.getpid()}"
    request_directory.mkdir(mode=0o700, parents=True)
    log = log_root / f"tombraider-bvb-foreground-{stamp}-{os.getpid()}.log"
    request = request_directory / "request.json"
    state = request_directory / "state.json"
    result_path = request_directory / "result.json"
    probe_state = request_directory / "service-probe.json"
    atomic_json(
        request,
        {
            "probe": str(probe),
            "arguments": arguments.probe_arguments,
            "environment": selected_environment(),
            "log": str(log),
        },
    )
    guard = PropertyGuard(properties, reload_command)
    original_sha = ""
    promoted = False
    full_display_ready = False
    child_pid: int | None = None
    child_start_ticks: int | None = None
    try:
        original_sha = guard.enable()
        time.sleep(arguments.service_settle_seconds)
        launch_runcommand(
            runcommand_arguments(am, python, tool, "--service-probe", probe_state, home)
        )
        readiness = wait_for_document(probe_state, 15)
        if readiness.get("cpuset") != TOP_APP or readiness.get("cpu") != TOP_APP:
            fail("RunCommandService readiness probe did not enter top-app")
        task_id: int | None = None
        if arguments.x11_fullscreen and not allow_no_x11:
            # A child created while Android considers X11 a normal fullscreen
            # task is immediately demoted. Bootstrap the Activity as a small
            # freeform task first so the new controller is born in top-app;
            # expand it only after the explicit workload handoff marker.
            task_id = promote_x11(adb, serial, arguments.x11_bounds)
            promoted = True
        launch_runcommand(
            runcommand_arguments(am, python, tool, "--child", request_directory, home)
        )
        child_state = wait_for_document(state, 30)
        child_pid, child_start_ticks = validate_child(
            child_state, proc_root, python, tool, request_directory
        )
        restored_sha = guard.restore()
        if restored_sha != original_sha:
            fail("Termux property hash changed after restoration")
        print(f"Termux external-command property restored: sha256={restored_sha}", flush=True)
        if arguments.x11_fullscreen and not allow_no_x11:
            deadline = time.monotonic() + arguments.promotion_timeout_seconds
            while time.monotonic() < deadline:
                if result_path.exists():
                    fail("benchmark exited before full-display expansion")
                if probe_handoff_ready(log):
                    break
                if not process_still_top_app(proc_root, child_pid):
                    fail("benchmark controller left top-app before its handoff marker")
                time.sleep(0.1)
            else:
                fail("benchmark did not emit its full-display handoff marker")
            assert task_id is not None
            toggle = expand_x11_full_display(
                adb, serial, task_id, arguments.x11_fullscreen_bounds
            )
            full_display_ready = True
            if not process_still_top_app(proc_root, child_pid):
                fail("full-display X11 expansion moved the controller out of top-app")
            print(
                "Termux:X11 borderless full-display ready: "
                f"task={task_id} bounds="
                f"{','.join(str(value) for value in arguments.x11_fullscreen_bounds)} "
                f"toggle={toggle[0]},{toggle[1]}; controller remains top-app; "
                "Android polling stopped before the timed scene",
                flush=True,
            )
        elif not allow_no_x11:
            deadline = time.monotonic() + arguments.promotion_timeout_seconds
            while time.monotonic() < deadline:
                if result_path.exists():
                    fail("BVB probe exited before Android foreground promotion")
                if probe_handoff_ready(log) or not process_still_top_app(
                    proc_root, child_pid
                ):
                    task_id = promote_x11(adb, serial, arguments.x11_bounds)
                    promoted = True
                    top_deadline = time.monotonic() + 10
                    while time.monotonic() < top_deadline:
                        if process_still_top_app(proc_root, child_pid):
                            break
                        time.sleep(0.1)
                    else:
                        fail("Termux:X11 promotion did not restore the BVB controller to top-app")
                    print(
                        "Termux:X11 foreground keeper ready: "
                        f"task={task_id} "
                        f"bounds={','.join(str(value) for value in arguments.x11_bounds)}; "
                        "Android polling stopped before the timed scene",
                        flush=True,
                    )
                    break
                time.sleep(0.1)
            else:
                fail("BVB Activity never displaced the controller before the promotion timeout")
        result = wait_for_result(
            result_path,
            arguments.result_timeout_seconds,
            proc_root,
            child_pid,
            child_start_ticks,
        )
        return_code = result.get("return_code")
        if type(return_code) is not int or not 0 <= return_code <= 255:
            fail("foreground child returned invalid structured status")
        print(
            f"Tomb Raider BVB foreground run complete: status={return_code} "
            f"log={log}",
            flush=True,
        )
        return return_code
    finally:
        if guard.original is not None:
            try:
                restored_sha = guard.restore()
                if original_sha and restored_sha != original_sha:
                    print(
                        "run-tombraider-bvb-foreground: property restoration hash mismatch",
                        file=sys.stderr,
                    )
            except Exception as error:  # cleanup must report but preserve the original failure
                print(
                    "run-tombraider-bvb-foreground: property restoration failed: "
                    f"{error}",
                    file=sys.stderr,
                )
        if promoted:
            try:
                if arguments.x11_fullscreen and not full_display_ready:
                    task_id = promote_x11(adb, serial, arguments.x11_bounds)
                    expand_x11_full_display(
                        adb, serial, task_id, arguments.x11_fullscreen_bounds
                    )
                elif not arguments.x11_fullscreen:
                    restore_x11(adb, serial)
            except Exception as error:
                print(
                    "run-tombraider-bvb-foreground: X11 fullscreen restoration failed: "
                    f"{error}",
                    file=sys.stderr,
                )
        if child_pid is not None and not result_path.exists():
            process = proc_root / str(child_pid)
            if process.exists():
                arguments_now = process_cmdline(process / "cmdline")
                expected = [str(python), str(tool), "--child", str(request_directory)]
                if arguments_now[:4] == expected:
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.kill(child_pid, signal.SIGTERM)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--service-probe":
        return service_probe(Path(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        return child_main(Path(sys.argv[2]))
    return controller_main(controller_parser().parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ForegroundError as error:
        print(f"run-tombraider-bvb-foreground: {error}", file=sys.stderr)
        raise SystemExit(1)
