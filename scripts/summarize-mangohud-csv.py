#!/usr/bin/env python3
"""Summarize a bounded MangoHud CSV interval without claiming frame-level lows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import stat
import statistics


MAX_CSV_BYTES = 64 * 1024 * 1024


class SummaryError(RuntimeError):
    pass


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def read_samples(path: Path) -> tuple[str, list[tuple[float, float, float]]]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SummaryError("CSV must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > MAX_CSV_BYTES:
        raise SummaryError(f"CSV size is invalid: {metadata.st_size}")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    lines = payload.decode("utf-8-sig").splitlines()
    header_index = next(
        (index for index, line in enumerate(lines[:64]) if line.startswith("fps,")),
        None,
    )
    if header_index is None:
        raise SummaryError("MangoHud frame-metrics header is missing")
    reader = csv.DictReader(lines[header_index:])
    required = {"fps", "frametime", "elapsed"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise SummaryError("required MangoHud columns are missing")

    samples: list[tuple[float, float, float]] = []
    previous_elapsed = -1.0
    for row_number, row in enumerate(reader, start=header_index + 2):
        try:
            fps = float(row["fps"])
            frametime = float(row["frametime"])
            elapsed = float(row["elapsed"]) / 1_000_000_000.0
        except (KeyError, TypeError, ValueError) as error:
            raise SummaryError(f"invalid numeric row: {row_number}") from error
        if not all(math.isfinite(value) for value in (fps, frametime, elapsed)):
            raise SummaryError(f"non-finite numeric row: {row_number}")
        if fps <= 0 or frametime <= 0 or elapsed < 0:
            raise SummaryError(f"non-positive metric row: {row_number}")
        if elapsed < previous_elapsed:
            raise SummaryError(f"elapsed time moved backward: {row_number}")
        previous_elapsed = elapsed
        samples.append((elapsed, fps, frametime))
    if not samples:
        raise SummaryError("CSV has no metric samples")
    return digest, samples


def summarize(
    path: Path, start_seconds: float, duration_seconds: float | None
) -> dict[str, object]:
    digest, samples = read_samples(path)
    end_seconds = (
        start_seconds + duration_seconds if duration_seconds is not None else None
    )
    selected = [
        sample
        for sample in samples
        if sample[0] >= start_seconds
        and (end_seconds is None or sample[0] < end_seconds)
    ]
    if len(selected) < 2:
        raise SummaryError("selected interval has fewer than two samples")
    fps = [sample[1] for sample in selected]
    frametime = [sample[2] for sample in selected]

    def rounded(value: float) -> float:
        return round(value, 6)

    return {
        "schema_version": 1,
        "source": str(path),
        "source_sha256": digest,
        "csv_duration_seconds": rounded(samples[-1][0] - samples[0][0]),
        "selection": {
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
            "first_sample_seconds": rounded(selected[0][0]),
            "last_sample_seconds": rounded(selected[-1][0]),
            "samples": len(selected),
        },
        "sampled_fps": {
            "mean": rounded(statistics.fmean(fps)),
            "median": rounded(statistics.median(fps)),
            "p01": rounded(percentile(fps, 0.01)),
            "p001": rounded(percentile(fps, 0.001)),
            "minimum": rounded(min(fps)),
            "maximum": rounded(max(fps)),
        },
        "sampled_frametime_ms": {
            "median": rounded(statistics.median(frametime)),
            "p95": rounded(percentile(frametime, 0.95)),
            "p99": rounded(percentile(frametime, 0.99)),
            "maximum": rounded(max(frametime)),
        },
        "claim_boundary": (
            "Metrics are periodic MangoHud samples, not per-frame data. "
            "p01 and p001 are sample percentiles, not conventional 1%/0.1% frame lows."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float)
    arguments = parser.parse_args()
    if not math.isfinite(arguments.start_seconds) or arguments.start_seconds < 0:
        parser.error("--start-seconds must be finite and non-negative")
    if arguments.duration_seconds is not None and (
        not math.isfinite(arguments.duration_seconds)
        or arguments.duration_seconds <= 0
    ):
        parser.error("--duration-seconds must be finite and positive")
    try:
        result = summarize(
            arguments.csv, arguments.start_seconds, arguments.duration_seconds
        )
    except (OSError, UnicodeDecodeError, SummaryError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
