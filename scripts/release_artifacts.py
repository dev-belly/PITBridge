"""Bind checked distributions to one source version and exact CI commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pitbridge-checked-release-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_version() -> str:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Expected a stable three-part project version")
    return version


def validate_commit(commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Release requires an exact lowercase 40-character commit SHA")


def expected_files(version: str) -> set[str]:
    return {
        f"pitbridge-{version}-py3-none-any.whl",
        f"pitbridge-{version}.tar.gz",
        "installed-check.json",
    }


def validate_check(path: Path, version: str) -> None:
    check = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(check, dict)
        or check.get("status") != "verified"
        or check.get("version") != version
    ):
        raise ValueError("Installed check must pass for the source version")
    precision = check.get("timestamp_precision")
    if (
        not isinstance(precision, dict)
        or precision.get("cutoff_and_late_microsecond") is not True
        or type(precision.get("json_and_csv_rejections")) is not int
        or precision["json_and_csv_rejections"] != 4
        or precision.get("no_reports_on_rejection") is not True
    ):
        raise ValueError("Installed timestamp-precision boundary evidence is required")
    for section, key in (
        ("scalar", "independent_replay"),
        ("rolling", "independent_temporal_replay"),
    ):
        for result in (check.get(section), check.get("csv", {}).get(section)):
            if (
                not isinstance(result, dict)
                or result.get("verified") is not True
                or result.get(key) is not True
            ):
                raise ValueError(
                    "Installed JSON and CSV scalar/rolling replay evidence is required"
                )
    trials = check.get("benchmark", {}).get("trials", [])
    if (
        len(trials) != 1
        or trials[0].get("observations") != 2000
        or trials[0].get("repeats") != 2
    ):
        raise ValueError(
            "Installed benchmark must contain two 2,000-observation trials"
        )
    runs = trials[0].get("runs", [])
    if len(runs) != 2 or any(run.get("correctness") != "verified" for run in runs):
        raise ValueError("Installed benchmark lacks independent-oracle evidence")
    if (
        any(
            not re.fullmatch(r"[0-9a-f]{64}", run.get("output_sha256", ""))
            for run in runs
        )
        or len({run["output_sha256"] for run in runs}) != 1
    ):
        raise ValueError("Installed benchmark snapshot digests differ")


def validate_distributions(directory: Path, version: str) -> None:
    wheel = directory / f"pitbridge-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        metadata = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            raise ValueError("Expected one wheel metadata record")
        record = BytesParser().parsebytes(archive.read(metadata[0]))
        if record["Name"] != "pitbridge" or record["Version"] != version:
            raise ValueError("Wheel package name/version differs from source")
    with tarfile.open(directory / f"pitbridge-{version}.tar.gz") as archive:
        member = archive.extractfile(f"pitbridge-{version}/pyproject.toml")
        if member is None:
            raise ValueError("Source distribution lacks pyproject.toml")
        project = tomllib.loads(member.read().decode("utf-8"))["project"]
        if project.get("name") != "pitbridge" or project.get("version") != version:
            raise ValueError(
                "Source-distribution package name/version differs from source"
            )


def checksum_text(directory: Path, names: set[str]) -> str:
    return "".join(f"{digest(directory / name)}  {name}\n" for name in sorted(names))


def prepare(
    distributions: Path, check_result: Path, destination: Path, commit: str
) -> dict:
    validate_commit(commit)
    version = source_version()
    distribution_names = expected_files(version) - {"installed-check.json"}
    if {path.name for path in distributions.iterdir()} != distribution_names:
        raise ValueError(
            "Expected exactly the current-version wheel and source distribution"
        )
    validate_distributions(distributions, version)
    validate_check(check_result, version)
    if destination.exists():
        raise FileExistsError(f"Choose a new release directory: {destination}")
    destination.mkdir(parents=True)
    for name in distribution_names:
        shutil.copyfile(distributions / name, destination / name)
    shutil.copyfile(check_result, destination / "installed-check.json")
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "commit": commit,
        "files_sha256": {
            name: digest(destination / name) for name in sorted(expected_files(version))
        },
    }
    (destination / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    (destination / "CHECKSUMS.sha256").write_text(
        checksum_text(destination, expected_files(version) | {"release-manifest.json"}),
        encoding="utf-8",
        newline="",
    )
    return verify(destination, commit)


def verify(directory: Path, commit: str) -> dict:
    validate_commit(commit)
    version = source_version()
    expected = expected_files(version)
    if {path.name for path in directory.iterdir()} != expected | {
        "release-manifest.json",
        "CHECKSUMS.sha256",
    }:
        raise ValueError("Unexpected release file set")
    if any(not path.is_file() or path.is_symlink() for path in directory.iterdir()):
        raise ValueError("Release assets must be regular files")
    manifest = json.loads(
        (directory / "release-manifest.json").read_text(encoding="utf-8")
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != SCHEMA
        or manifest.get("commit") != commit
        or manifest.get("version") != version
        or not isinstance(manifest.get("files_sha256"), dict)
        or set(manifest["files_sha256"]) != expected
    ):
        raise ValueError("Release commit, version or distribution set differs")
    if manifest["files_sha256"] != {
        name: digest(directory / name) for name in expected
    }:
        raise ValueError("Release file digest differs")
    wanted = checksum_text(directory, expected | {"release-manifest.json"})
    if (directory / "CHECKSUMS.sha256").read_bytes() != wanted.encode("utf-8"):
        raise ValueError("Release checksum list differs")
    validate_distributions(directory, version)
    validate_check(directory / "installed-check.json", version)
    return {"status": "verified", "version": version, "commit": commit, "assets": 5}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("distributions", type=Path)
    build.add_argument("check_result", type=Path)
    build.add_argument("destination", type=Path)
    build.add_argument("--commit", required=True)
    check = commands.add_parser("verify")
    check.add_argument("directory", type=Path)
    check.add_argument("--commit", required=True)
    args = parser.parse_args()
    result = (
        prepare(args.distributions, args.check_result, args.destination, args.commit)
        if args.command == "prepare"
        else verify(args.directory, args.commit)
    )
    print(json.dumps(result, indent=2))
