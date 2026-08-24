#!/usr/bin/env python3
"""Profile Steam's work between an AppID request and acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import time


MACHINES = {62: "x86_64", 183: "aarch64"}


def fail(message: str) -> None:
    raise SystemExit(f"profile-steam-appid-acceptance: {message}")


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return b""


def elf_machine(path: Path | None) -> str:
    if path is None:
        return "unknown"
    data = read_bytes(path)[:20]
    if len(data) < 20 or data[:4] != b"\x7fELF":
        return "unknown"
    byteorder = "little" if data[5] == 1 else "big" if data[5] == 2 else None
    if byteorder is None:
        return "unknown"
    return MACHINES.get(int.from_bytes(data[18:20], byteorder), "other")


def proc_stat(path: Path) -> tuple[int, int, int, int] | None:
    try:
        fields = path.read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
        return int(fields[1]), int(fields[11]), int(fields[12]), int(fields[17])
    except (FileNotFoundError, PermissionError, OSError, IndexError, ValueError):
        return None


def proc_metrics(directory: Path) -> dict[str, int]:
    parsed = proc_stat(directory / "stat")
    if parsed is None:
        return {}
    _ppid, user_ticks, system_ticks, threads = parsed
    values = {
        "user_ticks": user_ticks,
        "system_ticks": system_ticks,
        "threads": threads,
        "rchar_bytes": 0,
        "storage_read_bytes": 0,
        "read_syscalls": 0,
        "rss_kib": 0,
    }
    for line in read_bytes(directory / "io").decode("utf-8", "replace").splitlines():
        key, separator, value = line.partition(":")
        if not separator or not value.strip().isdecimal():
            continue
        destination = {
            "rchar": "rchar_bytes",
            "read_bytes": "storage_read_bytes",
            "syscr": "read_syscalls",
        }.get(key)
        if destination:
            values[destination] = int(value.strip())
    for line in read_bytes(directory / "status").decode("utf-8", "replace").splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) >= 2 and fields[1].isdecimal():
                values["rss_kib"] = int(fields[1])
            break
    return values


def payload_path(arguments: tuple[str, ...]) -> Path | None:
    try:
        index = arguments.index("--argv0")
    except ValueError:
        index = -1
    candidates = []
    if index >= 0 and index + 1 < len(arguments):
        candidates.append(arguments[index + 1])
    if arguments:
        candidates.append(arguments[0])
    for candidate in candidates:
        path = Path(candidate)
        try:
            metadata = path.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if stat.S_ISREG(metadata.st_mode):
            return path
    return None


def snapshot(proc_root: Path, root_pid: int) -> dict[int, dict[str, object]]:
    raw: dict[int, dict[str, object]] = {}
    for directory in proc_root.iterdir():
        if not directory.name.isdecimal():
            continue
        parsed = proc_stat(directory / "stat")
        if parsed is None:
            continue
        ppid = parsed[0]
        arguments = tuple(
            part.decode("utf-8", "replace")
            for part in read_bytes(directory / "cmdline").split(b"\0")
            if part
        )
        raw[int(directory.name)] = {
            "directory": directory,
            "ppid": ppid,
            "arguments": arguments,
        }
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, process in raw.items():
            if pid not in descendants and process["ppid"] in descendants:
                descendants.add(pid)
                changed = True
    return {pid: raw[pid] for pid in descendants if pid in raw}


def role(arguments: tuple[str, ...], pid: int, root_pid: int) -> str:
    joined = "\0".join(arguments)
    if pid == root_pid:
        return "steam_main"
    if "steamwebhelper" in joined:
        return "steamwebhelper"
    return "steam_descendant"


def identity(directory: Path, arguments: tuple[str, ...], pid: int, root_pid: int) -> dict[str, object]:
    try:
        executable = Path(os.readlink(directory / "exe"))
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        executable = None
    payload = payload_path(arguments)
    maps = read_bytes(directory / "maps").decode("utf-8", "replace").casefold()
    fex_mapped = any(marker in maps for marker in ("fexinterpreter", "libfex", "/fex-"))
    parsed = proc_stat(directory / "stat")
    return {
        "pid": pid,
        "ppid": parsed[0] if parsed else None,
        "role": role(arguments, pid, root_pid),
        "executable": str(executable) if executable else None,
        "executable_machine": elf_machine(executable),
        "payload": str(payload) if payload else None,
        "payload_machine": elf_machine(payload),
        "fex_mapped": fex_mapped,
    }


def delta(first: dict[str, int], last: dict[str, int], ticks: int) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for key in ("rchar_bytes", "storage_read_bytes", "read_syscalls"):
        result[key] = max(0, last.get(key, 0) - first.get(key, 0))
    result["cpu_user_seconds"] = round(
        max(0, last.get("user_ticks", 0) - first.get("user_ticks", 0)) / ticks, 3
    )
    result["cpu_system_seconds"] = round(
        max(0, last.get("system_ticks", 0) - first.get("system_ticks", 0)) / ticks, 3
    )
    result["peak_threads"] = max(first.get("threads", 0), last.get("threads", 0))
    result["peak_rss_kib"] = max(first.get("rss_kib", 0), last.get("rss_kib", 0))
    return result


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appid", type=int, required=True)
    parser.add_argument("--steam-pid", type=int, required=True)
    parser.add_argument("--gameprocess-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--poll", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=120.0)
    arguments = parser.parse_args()
    if arguments.appid <= 0 or arguments.steam_pid <= 0:
        parser.error("AppID and Steam PID must be positive")
    if not 0.05 <= arguments.poll <= 2.0 or not 1 <= arguments.timeout <= 600:
        parser.error("poll or timeout is outside its bounded range")
    root = arguments.proc_root / str(arguments.steam_pid)
    if not root.is_dir():
        fail(f"Steam PID is unavailable: {arguments.steam_pid}")
    initial_arguments = tuple(
        part.decode("utf-8", "replace")
        for part in read_bytes(root / "cmdline").split(b"\0")
        if part
    )
    if not any("steamrtarm64/steam" in item for item in initial_arguments):
        fail(f"PID {arguments.steam_pid} is not the native ARM64 Steam client")
    try:
        offset = arguments.gameprocess_log.stat().st_size
    except FileNotFoundError:
        offset = 0
    marker = f"AppID {arguments.appid} adding PID"
    started_wall = datetime.now(timezone.utc)
    started = time.monotonic()
    deadline = started + arguments.timeout
    records: dict[int, dict[str, object]] = {}
    accepted_line = None
    samples = 0
    while time.monotonic() < deadline:
        samples += 1
        for pid, process in snapshot(arguments.proc_root, arguments.steam_pid).items():
            directory = process["directory"]
            metrics = proc_metrics(directory)
            if not metrics:
                continue
            record = records.get(pid)
            if record is None:
                record = {
                    **identity(directory, process["arguments"], pid, arguments.steam_pid),
                    "first_metrics": metrics,
                    "last_metrics": metrics,
                    "peak_threads": metrics["threads"],
                    "peak_rss_kib": metrics["rss_kib"],
                }
                records[pid] = record
            else:
                record["last_metrics"] = metrics
                record["peak_threads"] = max(record["peak_threads"], metrics["threads"])
                record["peak_rss_kib"] = max(record["peak_rss_kib"], metrics["rss_kib"])
        try:
            with arguments.gameprocess_log.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                text = handle.read()
                offset = handle.tell()
        except FileNotFoundError:
            text = ""
        for line in text.splitlines():
            if marker in line:
                accepted_line = line.strip()[:512]
                break
        if accepted_line is not None:
            break
        time.sleep(arguments.poll)
    elapsed = round(time.monotonic() - started, 3)
    ticks = int(os.sysconf("SC_CLK_TCK"))
    processes = []
    aggregate: dict[str, dict[str, int | float]] = {}
    for record in sorted(records.values(), key=lambda item: item["pid"]):
        metrics_delta = delta(record.pop("first_metrics"), record.pop("last_metrics"), ticks)
        metrics_delta["peak_threads"] = record.pop("peak_threads")
        metrics_delta["peak_rss_kib"] = record.pop("peak_rss_kib")
        record["delta"] = metrics_delta
        processes.append(record)
        group = aggregate.setdefault(record["role"], {})
        for key in ("cpu_user_seconds", "cpu_system_seconds", "rchar_bytes", "storage_read_bytes", "read_syscalls"):
            group[key] = round(group.get(key, 0) + metrics_delta[key], 3)
    translated = [item["pid"] for item in processes if item["fex_mapped"] or item["payload_machine"] == "x86_64"]
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "accepted" if accepted_line is not None else "timeout",
        "appid": arguments.appid,
        "steam_pid": arguments.steam_pid,
        "started_at": started_wall.isoformat(timespec="milliseconds"),
        "elapsed_seconds": elapsed,
        "poll_seconds": arguments.poll,
        "sample_count": samples,
        "acceptance_marker": accepted_line,
        "processes": processes,
        "aggregate_by_role": aggregate,
        "architecture_summary": {
            "aarch64_payloads": sum(item["payload_machine"] == "aarch64" for item in processes),
            "x86_64_payloads": sum(item["payload_machine"] == "x86_64" for item in processes),
            "translated_pids": translated,
            "steam_acceptance_emulation_observed": bool(translated),
        },
        "claim_boundary": "Low-overhead proc sampling of the Steam process tree through the first new AppID-added log marker; no ptrace, per-frame instrumentation, or game FPS claim.",
    }
    atomic_json(arguments.output, report)
    print(arguments.output)
    return 0 if accepted_line is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())
