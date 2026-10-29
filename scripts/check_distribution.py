"""Verify JSON and CSV installed-wheel paths without source-tree imports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path
from textwrap import dedent


def check(directory: Path) -> dict:
    wheels = list(directory.resolve().glob("pitbridge-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one PITBridge wheel; found {len(wheels)}")
    expected_version = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )["project"]["version"]
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
        environment.pop(key, None)
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="pitbridge-wheel-") as temporary:
        root = Path(temporary).resolve()
        installed, work = root / "environment", root / "work"
        work.mkdir()
        venv.EnvBuilder(with_pip=True).create(installed)
        executables = installed / ("Scripts" if os.name == "nt" else "bin")
        python = executables / ("python.exe" if os.name == "nt" else "python")
        cli = executables / ("pitbridge.exe" if os.name == "nt" else "pitbridge")

        def run(*arguments: str) -> str:
            result = subprocess.run(
                arguments,
                cwd=work,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    f"Command failed: {arguments}\n{result.stdout}\n{result.stderr}"
                )
            return result.stdout

        run(str(python), "-m", "pip", "install", "--no-index", str(wheels[0]))
        origin = run(
            str(python), "-I", "-c", "import pitbridge; print(pitbridge.__file__)"
        )
        if not Path(origin.strip()).resolve().is_relative_to(installed):
            raise ValueError("Imported PITBridge from outside its isolated environment")
        version = json.loads(
            run(
                str(python),
                "-I",
                "-c",
                "import json, pitbridge; from importlib.metadata import version; "
                "print(json.dumps([version('pitbridge'), pitbridge.__version__]))",
            )
        )
        if version != [expected_version, expected_version]:
            raise ValueError(
                "Installed distribution/runtime version differs from the source version"
            )
        run(str(python), "-I", "-m", "pitbridge", "--help")

        # An arrival just after a decision must never be rounded into visibility.
        # Exercise the actual installed package, not the source checkout.
        boundary = json.loads(
            run(
                str(python),
                "-I",
                "-c",
                dedent("""
                    import json
                    from pitbridge import Decision, FeatureSpec, Observation, build_snapshot
                    from pitbridge.rolling import RollingSpec, build_rolling

                    cutoff = "2026-01-01T00:00:00Z"
                    decision = [Decision("d", "e", cutoff)]
                    scalar_spec = [FeatureSpec("s", "f", 1)]
                    rolling_spec = [RollingSpec("total", "s", "f", 1)]
                    for ingestion, available in (
                        (cutoff, True), ("2026-01-01T00:00:00.000001Z", False)
                    ):
                        obs = [Observation("r", "e", "s", "f", cutoff, cutoff,
                                           ingestion, 1, 10)]
                        scalar = build_snapshot(obs, decision, scalar_spec)[0]
                        rolling, members = build_rolling(obs, decision, rolling_spec)
                        if ((scalar.record_id == "r") != available
                            or (len(members) == 1) != available
                            or (rolling[0].status != "not_available") != available):
                            raise ValueError("Incorrect installed cutoff selection")
                    print(json.dumps({"cutoff_and_late_microsecond": True}))
                """),
            )
        )

        cutoff = "2026-01-01T00:00:00Z"
        late = "2026-01-01T00:00:00.0000009Z"
        for command, spec in (("build", "specs"), ("aggregate", "rolling_specs")):
            case = {
                "observations": [
                    {
                        "record_id": "r",
                        "entity_id": "e",
                        "source": "s",
                        "feature": "f",
                        "event_at": cutoff,
                        "published_at": cutoff,
                        "ingested_at": late,
                        "revision": 1,
                        "value": 10,
                        "deleted": False,
                    }
                ],
                "decisions": [
                    {"decision_id": "d", "entity_id": "e", "decision_at": cutoff}
                ],
                spec: (
                    [{"source": "s", "feature": "f", "max_age_days": 1}]
                    if command == "build"
                    else [
                        {
                            "name": "total",
                            "source": "s",
                            "feature": "f",
                            "window_days": 1,
                            "aggregation": "sum",
                        }
                    ]
                ),
            }
            inputs = work / f"precision-{command}.json"
            inputs.write_text(json.dumps(case), encoding="utf-8")
            tables = work / f"precision-{command}-tables"
            tables.mkdir()
            for section, rows in case.items():
                with (tables / f"{section}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(
                        {
                            key: str(value).lower()
                            if isinstance(value, bool)
                            else value
                            for key, value in row.items()
                        }
                        for row in rows
                    )
            for route, source in (("--inputs", inputs), ("--csv-dir", tables)):
                output = work / f"precision-{command}-{route[2:]}-output"
                result = subprocess.run(
                    (str(cli), command, route, str(source), "--out", str(output)),
                    cwd=work,
                    env=environment,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    check=False,
                )
                if (
                    result.returncode != 2
                    or result.stdout
                    or output.exists()
                    or "microsecond precision" not in result.stderr
                    or "Traceback" in result.stderr
                ):
                    raise ValueError(
                        f"Installed {command} {route} did not reject excess precision"
                    )
        if boundary != {"cutoff_and_late_microsecond": True}:
            raise ValueError("Installed package changed supported cutoff semantics")

        run(str(cli), "demo", "--out", "scalar")
        scalar = json.loads(run(str(cli), "verify", "--out", "scalar"))
        run(str(cli), "rolling-demo", "--out", "rolling")
        rolling = json.loads(run(str(cli), "verify-rolling", "--out", "rolling"))
        csv_results = {}
        for name, command, check_command, spec, comparison_files in (
            ("scalar", "build", "verify", "specs", ("snapshots.csv", "comparison.csv")),
            (
                "rolling",
                "aggregate",
                "verify-rolling",
                "rolling_specs",
                ("features.csv", "members.csv"),
            ),
        ):
            source = work / name
            tables = work / f"{name}-tables"
            tables.mkdir()
            data = json.loads((source / "inputs.json").read_text(encoding="utf-8"))
            for section in ("observations", "decisions", spec):
                with (tables / f"{section}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(data[section][0]))
                    writer.writeheader()
                    writer.writerows(
                        {
                            key: str(value).lower()
                            if isinstance(value, bool)
                            else value
                            for key, value in row.items()
                        }
                        for row in data[section]
                    )
            output = f"{name}-csv"
            run(str(cli), command, "--csv-dir", str(tables), "--out", output)
            csv_results[name] = json.loads(
                run(str(cli), check_command, "--out", output)
            )
            for filename in comparison_files:
                if (source / filename).read_bytes() != (
                    work / output / filename
                ).read_bytes():
                    raise ValueError(
                        f"JSON/CSV installed-package evidence differs: {name}/{filename}"
                    )
        starter_results = {}
        for name, command, check_command, comparison_files in (
            ("scalar", "build", "verify", ("snapshots.csv", "comparison.csv")),
            ("rolling", "aggregate", "verify-rolling", ("features.csv", "members.csv")),
        ):
            tables = work / f"editable {name} inputs"
            arguments = ("--rolling",) if name == "rolling" else ()
            created = json.loads(
                run(str(cli), "init-csv", "--out", str(tables), *arguments)
            )
            before = {path.name: path.read_bytes() for path in tables.iterdir()}
            if set(created.get("files", [])) != set(before) or len(before) != 4:
                raise ValueError(
                    "Starter file inventory differs from its creation result"
                )
            output = work / f"starter-{name}-report"
            run(str(cli), command, "--csv-dir", str(tables), "--out", str(output))
            replay = json.loads(run(str(cli), check_command, "--out", str(output)))
            for filename in comparison_files:
                if (work / name / filename).read_bytes() != (
                    output / filename
                ).read_bytes():
                    raise ValueError(
                        f"Starter differs from the installed demo: {name}/{filename}"
                    )
            duplicate = subprocess.run(
                (str(cli), "init-csv", "--out", str(tables), *arguments),
                cwd=work,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            if (
                duplicate.returncode != 2
                or duplicate.stdout
                or "Traceback" in duplicate.stderr
                or before != {path.name: path.read_bytes() for path in tables.iterdir()}
            ):
                raise ValueError(
                    "Starter replaced edited inputs or failed its error contract"
                )
            starter_results[name] = {
                "created": created,
                "replay": replay,
                "demo_result_files_match": True,
                "existing_inputs_preserved": True,
            }
            if name == "scalar":
                source = tables / "observations.csv"
                with source.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    columns, records = reader.fieldnames, list(reader)
                for record in records:
                    if record["record_id"] == "tax-a-v2":
                        record["ingested_at"] = "2026-04-03T00:00:00Z"
                with source.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle, fieldnames=columns, lineterminator="\n"
                    )
                    writer.writeheader()
                    writer.writerows(records)
                edited = work / "starter-edited-report"
                run(str(cli), "build", "--csv-dir", str(tables), "--out", str(edited))
                run(str(cli), "verify", "--out", str(edited))
                with (edited / "snapshots.csv").open(
                    encoding="utf-8", newline=""
                ) as handle:
                    row = next(
                        row
                        for row in csv.DictReader(handle)
                        if row["decision_id"] == "SME-A-4" and row["source"] == "tax"
                    )
                if row["record_id"] != "tax-a-v1" or float(row["value"]) != 100000:
                    raise ValueError(
                        "An edited starter arrival did not change the selected revision"
                    )
                starter_results[name]["edited_arrival_replayed"] = True
        benchmark = json.loads(
            run(
                str(cli),
                "benchmark",
                "--rows",
                "2000",
                "--repeats",
                "2",
                "--out",
                "benchmark",
            )
        )
        run(str(python), "-m", "pip", "check")
        return {
            "status": "verified",
            "version": expected_version,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "installation": "non-editable wheel; clean venv; cwd outside the source tree",
            "timestamp_precision": {
                "cutoff_and_late_microsecond": True,
                "json_and_csv_rejections": 4,
                "no_reports_on_rejection": True,
            },
            "scalar": scalar,
            "rolling": rolling,
            "csv": csv_results,
            "csv_starters": starter_results,
            "benchmark": benchmark,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="Directory with one built PITBridge wheel"
    )
    parser.add_argument(
        "--output", type=Path, help="Save the UTF-8 installed-check evidence"
    )
    args = parser.parse_args()
    result = json.dumps(check(args.directory), indent=2) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8", newline="")
    print(result, end="")
