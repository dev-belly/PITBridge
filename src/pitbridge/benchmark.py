"""Isolated-process SQLite scale measurements with a small independent oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot


def workload(rows: int, seed: int = 42):
    """20 observations and 4 decisions per entity; fixed shape at every size."""
    if type(rows) is not int or rows < 20 or rows % 20:
        raise ValueError("observation count must be a positive multiple of 20")
    origin = datetime(2020, 1, 1, tzinfo=timezone.utc)
    instant = lambda day: (origin + timedelta(days=day)).isoformat()
    observations, decisions = [], []
    for entity in range(rows // 20):
        entity_id = f"E{entity:07d}"
        for day in range(18):
            observations.append(
                Observation(
                    f"O{entity:07d}-{day:02d}-1",
                    entity_id,
                    "filing",
                    "debt",
                    instant(day),
                    instant(day + 1),
                    instant(day + 2),
                    1,
                    float((seed + entity * 13 + day) % 997),
                )
            )
        observations.append(
            Observation(
                f"O{entity:07d}-17-2",
                entity_id,
                "filing",
                "debt",
                instant(17),
                instant(30),
                instant(31),
                2,
                float(seed + entity + 1000),
            )
        )
        observations.append(
            Observation(
                f"O{entity:07d}-17-3",
                entity_id,
                "filing",
                "debt",
                instant(17),
                instant(45),
                instant(46),
                3,
                None,
                True,
            )
        )
        for day in (20, 35, 60, 160):
            decisions.append(
                Decision(f"D{entity:07d}-{day:03d}", entity_id, instant(day))
            )
    return observations, decisions, [FeatureSpec("filing", "debt", 80)]


def _peak_rss_bytes():
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def measure(rows: int, seed: int = 42):
    # A tiny warm-up does not reuse the measured database or its input objects.
    build_snapshot(*workload(20, seed))
    started = time.perf_counter()
    observations, decisions, specs = workload(rows, seed)
    generation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    snapshots = build_snapshot(observations, decisions, specs)
    snapshot_seconds = time.perf_counter() - started
    statuses = dict(sorted(Counter(row.status for row in snapshots).items()))
    expected = {"selected": rows // 20 * 3, "stale": rows // 20}
    if statuses != expected or len(snapshots) != rows // 20 * 4:
        raise ValueError("scale workload status/count invariants failed")

    # Each entity is independent. Restrict inputs to the sampled entities, rather
    # than running the quadratic enumeration oracle on one million records.
    sample_entities = {f"E{i:07d}" for i in range(min(8, rows // 20))}
    expected_sample = reference_snapshot(
        [row for row in observations if row.entity_id in sample_entities],
        [row for row in decisions if row.entity_id in sample_entities],
        specs,
    )
    actual_sample = [row for row in snapshots if row.entity_id in sample_entities]
    if actual_sample != expected_sample:
        raise ValueError("scale workload disagrees with the independent Python oracle")
    digest = hashlib.sha256()
    for row in snapshots:
        digest.update(
            (
                json.dumps(
                    asdict(row), sort_keys=True, separators=(",", ":"), allow_nan=False
                )
                + "\n"
            ).encode()
        )
    return {
        "observations": rows,
        "entities": rows // 20,
        "decisions": len(decisions),
        "lookups": len(snapshots),
        "generation_seconds": generation_seconds,
        "snapshot_seconds": snapshot_seconds,
        "lookups_per_second": len(snapshots) / snapshot_seconds,
        "peak_process_rss_bytes": _peak_rss_bytes(),
        "statuses": statuses,
        "oracle_lookups": len(expected_sample),
        "output_sha256": digest.hexdigest(),
        "correctness": "verified",
    }


def run_scaling(
    rows=(100_000, 1_000_000), repeats=3, seed=42, destination="outputs/scaling"
):
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if not rows or len(set(rows)) != len(rows):
        raise ValueError("choose distinct observation counts")
    trials = []
    for count in rows:
        if type(count) is not int or count < 20 or count % 20:
            raise ValueError("observation count must be a positive multiple of 20")
        runs = []
        for _ in range(repeats):
            worker = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pitbridge.benchmark",
                    "--worker",
                    "--rows",
                    str(count),
                    "--seed",
                    str(seed),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if worker.returncode:
                raise ValueError(
                    f"scale worker failed ({worker.returncode}): {worker.stderr.strip()}"
                )
            runs.append(json.loads(worker.stdout))
        if len({run["output_sha256"] for run in runs}) != 1:
            raise ValueError("repeated scale trials produced different snapshots")
        seconds = [run["snapshot_seconds"] for run in runs]
        rss = [
            run["peak_process_rss_bytes"]
            for run in runs
            if run["peak_process_rss_bytes"] is not None
        ]
        trials.append(
            {
                "observations": count,
                "repeats": repeats,
                "runs": runs,
                "median_snapshot_seconds": statistics.median(seconds),
                "min_snapshot_seconds": min(seconds),
                "max_snapshot_seconds": max(seconds),
                "max_peak_process_rss_bytes": max(rss) if rss else None,
            }
        )
    package = Path(__file__).parent
    payload = {
        "project": "PITBridge scale benchmark",
        "seed": seed,
        "workload": "20 observations/entity: 18 events, late revision, later tombstone; 4 decisions; 80-day TTL",
        "measurement": "fresh child process per trial; in-memory SQLite; validation + load + query + Snapshot objects",
        "memory_scope": "whole child-process high-water RSS including generation, SQLite and oracle; null if unavailable",
        "oracle_scope": "all 4 decisions for the first 8 entities, independent Python enumeration",
        "limitations": [
            "Synthetic scalar workload; not rolling aggregation or online serving.",
            "Local machine measurements; no portable latency or throughput guarantee.",
            "Whole-process peak RSS is not incremental SQLite memory.",
            "One-repeat runs do not establish timing variability.",
        ],
        "environment": {
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "source_sha256": {
            name: hashlib.sha256((package / name).read_bytes()).hexdigest()
            for name in ("benchmark.py", "core.py")
        },
        "trials": trials,
    }
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    (output / "scaling.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rows", nargs="+", type=int, default=[100_000, 1_000_000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", default="outputs/scaling")
    args = parser.parse_args(argv)
    try:
        result = (
            measure(args.rows[0], args.seed)
            if args.worker
            else run_scaling(tuple(args.rows), args.repeats, args.seed, args.out)
        )
    except (ValueError, OSError) as exc:
        print(f"pitbridge benchmark: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
