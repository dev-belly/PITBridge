"""Never move a source instant earlier by silently dropping fractional digits."""

import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from pitbridge import Decision, build_snapshot, load_csv_inputs
from pitbridge.bundle import decode_inputs
from pitbridge.cli import main
from pitbridge.core import utc
from pitbridge.rolling import RollingSpec, build_rolling


AT = "2026-01-01T00:00:00Z"
LATE = "2026-01-01T00:00:00.0000009Z"


def inputs(*, rolling=False):
    return {
        "observations": [{
            "record_id": "r", "entity_id": "e", "source": "s", "feature": "f",
            "event_at": AT, "published_at": AT, "ingested_at": AT,
            "revision": 1, "value": 10, "deleted": False,
        }],
        "decisions": [{"decision_id": "d", "entity_id": "e", "decision_at": AT}],
        ("rolling_specs" if rolling else "specs"):
            ([{"name": "total", "source": "s", "feature": "f", "window_days": 1}]
             if rolling else [{"source": "s", "feature": "f", "max_age_days": 1}]),
    }


def write_csvs(directory, data):
    for name, rows in data.items():
        with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({key: str(value).lower() if type(value) is bool else value
                              for key, value in row.items()} for row in rows)


class TimestampPrecisionTests(unittest.TestCase):
    def test_excess_fractional_digits_are_rejected_instead_of_truncated(self):
        for value in (LATE, "2026-01-01T00:00:00,0000009+00:00",
                      "20260101T000000.1234567+0800", "2026-01-01T00:00:00.1234560Z"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "microsecond precision"):
                utc(value)

    def test_fractional_timezone_offsets_are_rejected_including_zero_offset(self):
        # datetime.fromisoformat ignores the fraction for a zero-second offset.
        # Reject these offsets consistently rather than guessing their instant.
        for offset in ("+00:00:00.5", "-00:00:00.5", "+08:00:00.5", "-050000,5"):
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "whole seconds"):
                utc("2026-01-01T00:00:00" + offset)

    def test_fractions_require_an_explicit_seconds_field(self):
        for clock in ("00.5", "00:00.5", "0000,5"):
            with self.subTest(clock=clock), self.assertRaisesRegex(ValueError, "hours, minutes and seconds"):
                utc("2026-01-01T" + clock + "Z")

    def test_supported_precision_and_offsets_preserve_exact_instants(self):
        for value, expected in (
            (AT, "2026-01-01T00:00:00.000000+00:00"),
            ("2026-01-01T08:00:00.123456+08:00", "2026-01-01T00:00:00.123456+00:00"),
            ("2026-01-01T00:00:00,1Z", "2026-01-01T00:00:00.100000+00:00"),
            ("2026-01-01T00:00:01+00:00:01", "2026-01-01T00:00:00.000000+00:00"),
        ):
            with self.subTest(value=value):
                self.assertEqual(utc(value), expected)

    def test_every_observation_time_and_decision_time_use_the_contract(self):
        for name in ("event_at", "published_at", "ingested_at"):
            with self.subTest(field=name):
                data = inputs()
                data["observations"][0][name] = LATE
                with self.assertRaisesRegex(ValueError, "microsecond precision"):
                    decode_inputs(data)
        with self.assertRaisesRegex(ValueError, "microsecond precision"):
            Decision("d", "e", LATE)

    def test_one_supported_microsecond_after_cutoff_stays_unavailable(self):
        data = inputs()
        data["observations"][0]["ingested_at"] = "2026-01-01T00:00:00.000001Z"
        observations, decisions, specs = decode_inputs(data)
        self.assertEqual(build_snapshot(observations, decisions, specs)[0].status, "not_available")
        rows, members = build_rolling(observations, decisions, [RollingSpec("total", "s", "f", 1)])
        self.assertEqual(rows[0].status, "not_available")
        self.assertEqual(members, [])

    def test_json_and_native_csv_commands_reject_before_writing_reports(self):
        for command in ("build", "aggregate"):
            for route in ("json", "csv"):
                for section, field in (("observations", "ingested_at"), ("decisions", "decision_at")):
                    with self.subTest(command=command, route=route, field=field), tempfile.TemporaryDirectory() as tmp:
                        directory = Path(tmp)
                        data = inputs(rolling=command == "aggregate")
                        data[section][0][field] = LATE
                        if route == "json":
                            path = directory / "inputs.json"
                            path.write_text(json.dumps(data), encoding="utf-8")
                            arguments = ["--inputs", str(path)]
                        else:
                            write_csvs(directory, data)
                            arguments = ["--csv-dir", str(directory)]
                        before = {path.name: path.read_bytes() for path in directory.iterdir()}
                        out = directory / "report"
                        stdout, stderr = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                            result = main([command, *arguments, "--out", str(out)])
                        self.assertEqual(result, 2)
                        self.assertIn("microsecond precision", stderr.getvalue())
                        if route == "csv":
                            self.assertIn(f"{section}.csv row 2:", stderr.getvalue())
                        self.assertNotIn("Traceback", stderr.getvalue())
                        self.assertEqual(stdout.getvalue(), "")
                        self.assertFalse(out.exists())
                        self.assertEqual(before, {path.name: path.read_bytes() for path in directory.iterdir()})

    @unittest.skipUnless(importlib.util.find_spec("pandas"), "optional pandas is not installed")
    def test_optional_pandas_adapter_matches_native_timestamp_rejection(self):
        adapter = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/pandas_csv.py"))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            data = inputs()
            data["observations"][0]["ingested_at"] = LATE
            write_csvs(directory, data)
            for loader in (load_csv_inputs, adapter["load_inputs"]):
                with self.subTest(loader=loader), self.assertRaisesRegex(
                        ValueError, "observations.csv row 2: .*microsecond precision"):
                    loader(directory)
