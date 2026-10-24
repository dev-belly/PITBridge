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
            "scalar": scalar,
            "rolling": rolling,
            "csv": csv_results,
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
