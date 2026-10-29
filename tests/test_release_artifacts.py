"""A release must retain the distributions and all installed replay evidence."""

import copy
import io
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import release_artifacts as release


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        self.destination = self.root / "release"
        self.check = self.root / "check.json"
        self.commit = "a" * 40
        self.version = release.source_version()
        self.write_distributions()
        scalar = {"verified": True, "independent_replay": True}
        rolling = {"verified": True, "independent_temporal_replay": True}
        self.result = {
            "status": "verified",
            "version": self.version,
            "timestamp_precision": {
                "cutoff_and_late_microsecond": True,
                "json_and_csv_rejections": 4,
                "no_reports_on_rejection": True,
            },
            "scalar": scalar,
            "rolling": rolling,
            "csv": {"scalar": scalar, "rolling": rolling},
            "csv_starters": {
                mode: {
                    "created": {
                        "status": "created",
                        "mode": mode,
                        "data_kind": "synthetic",
                        "observations": observations,
                        "decisions": decisions,
                        "specifications": 3,
                    },
                    "replay": replay,
                    "demo_result_files_match": True,
                    "existing_inputs_preserved": True,
                    **({"edited_arrival_replayed": True} if mode == "scalar" else {}),
                }
                for mode, observations, decisions, replay in (
                    ("scalar", 11, 15, scalar),
                    ("rolling", 10, 4, rolling),
                )
            },
            "benchmark": {
                "trials": [
                    {
                        "observations": 2000,
                        "repeats": 2,
                        "runs": [
                            {"correctness": "verified", "output_sha256": "b" * 64},
                            {"correctness": "verified", "output_sha256": "b" * 64},
                        ],
                    }
                ]
            },
        }
        self.write_check()

    def write_distributions(
        self, wheel_version=None, source_version=None, name="pitbridge"
    ):
        wheel = self.dist / f"pitbridge-{self.version}-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                f"pitbridge-{self.version}.dist-info/METADATA",
                f"Metadata-Version: 2.4\nName: {name}\nVersion: {wheel_version or self.version}\n",
            )
        source = f'[project]\nname = "{name}"\nversion = "{source_version or self.version}"\n'.encode()
        with tarfile.open(
            self.dist / f"pitbridge-{self.version}.tar.gz", "w:gz"
        ) as archive:
            info = tarfile.TarInfo(f"pitbridge-{self.version}/pyproject.toml")
            info.size = len(source)
            archive.addfile(info, io.BytesIO(source))

    def write_check(self):
        self.check.write_text(json.dumps(self.result), encoding="utf-8")

    def prepare(self):
        return release.prepare(self.dist, self.check, self.destination, self.commit)

    def test_valid_release_is_bound_to_commit_version_and_five_assets(self):
        result = self.prepare()
        self.assertEqual(
            result,
            {
                "status": "verified",
                "version": self.version,
                "commit": self.commit,
                "assets": 5,
            },
        )
        self.assertEqual(release.verify(self.destination, self.commit), result)
        for path in self.dist.iterdir():
            self.assertEqual(
                path.read_bytes(), (self.destination / path.name).read_bytes()
            )

    def test_wrong_or_symbolic_commit_fails(self):
        self.prepare()
        for commit in ("main", "A" * 40, "b" * 40):
            with (
                self.subTest(commit=commit),
                self.assertRaisesRegex(ValueError, "commit"),
            ):
                release.verify(self.destination, commit)

    def test_missing_any_installed_input_route_prevents_publication(self):
        original = copy.deepcopy(self.result)
        for group, section in (
            (None, "scalar"),
            (None, "rolling"),
            ("csv", "scalar"),
            ("csv", "rolling"),
        ):
            self.result = copy.deepcopy(original)
            target = self.result if group is None else self.result[group]
            target.pop(section)
            self.write_check()
            with (
                self.subTest(group=group, section=section),
                self.assertRaisesRegex(ValueError, "replay"),
            ):
                self.prepare()
            self.assertFalse(self.destination.exists())

    def test_benchmark_disagreement_prevents_publication(self):
        self.result["benchmark"]["trials"][0]["runs"][1]["output_sha256"] = "c" * 64
        self.write_check()
        with self.assertRaisesRegex(ValueError, "digests differ"):
            self.prepare()
        self.assertFalse(self.destination.exists())

    def test_missing_or_incomplete_editable_starter_evidence_prevents_publication(self):
        original = copy.deepcopy(self.result)
        for mode, field in (
            (None, None),
            ("scalar", None),
            ("rolling", None),
            ("scalar", "existing_inputs_preserved"),
            ("rolling", "demo_result_files_match"),
            ("scalar", "edited_arrival_replayed"),
        ):
            self.result = copy.deepcopy(original)
            if mode is None:
                self.result.pop("csv_starters")
            elif field is None:
                self.result["csv_starters"].pop(mode)
            else:
                self.result["csv_starters"][mode][field] = False
            self.write_check()
            with self.subTest(mode=mode, field=field):
                with self.assertRaisesRegex(ValueError, "editable CSV starter"):
                    self.prepare()
                self.assertFalse(self.destination.exists())

    def test_missing_or_false_installed_precision_evidence_prevents_publication(self):
        original = copy.deepcopy(self.result)
        for field, value in (
            (None, None),
            ("cutoff_and_late_microsecond", False),
            ("json_and_csv_rejections", 3),
            ("json_and_csv_rejections", True),
            ("no_reports_on_rejection", False),
        ):
            self.result = copy.deepcopy(original)
            if field is None:
                self.result.pop("timestamp_precision")
            else:
                self.result["timestamp_precision"][field] = value
            self.write_check()
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, "timestamp-precision"):
                    self.prepare()
                self.assertFalse(self.destination.exists())

    def test_wrong_distribution_metadata_prevents_publication(self):
        for kwargs in (
            {"wheel_version": "9.0.0"},
            {"source_version": "9.0.0"},
            {"name": "another-package"},
        ):
            self.write_distributions(**kwargs)
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ValueError, "name/version"),
            ):
                self.prepare()
            self.assertFalse(self.destination.exists())

    def test_stale_extra_distribution_prevents_publication(self):
        (self.dist / "pitbridge-old.whl").write_bytes(b"stale")
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.prepare()

    def test_modified_asset_or_checksum_is_rejected(self):
        self.prepare()
        path = self.destination / "installed-check.json"
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "digest"):
            release.verify(self.destination, self.commit)
        path.write_bytes(original)
        (self.destination / "CHECKSUMS.sha256").write_text("edited\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            release.verify(self.destination, self.commit)

    def test_extra_release_asset_and_replacement_directory_are_rejected(self):
        self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()
        (self.destination / "unreviewed.whl").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "file set"):
            release.verify(self.destination, self.commit)
