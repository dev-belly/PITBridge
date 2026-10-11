import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pitbridge.cli import main
from pitbridge.core import utc


class TimestampBoundsTests(unittest.TestCase):
    def test_offsets_outside_utc_datetime_range_are_contract_errors(self):
        for value in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "UTC datetime range"):
                utc(value)

    def test_offsets_at_supported_utc_boundaries_remain_valid(self):
        for value, expected in (
            ("0001-01-01T14:00:00+14:00", "0001-01-01T00:00:00.000000+00:00"),
            ("9999-12-31T11:59:59-12:00", "9999-12-31T23:59:59.000000+00:00"),
        ):
            with self.subTest(value=value):
                self.assertEqual(utc(value), expected)

    def test_build_and_aggregate_report_invalid_utc_range_before_writing(self):
        for command in ("build", "aggregate"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                source = directory / "inputs.json"
                source.write_text(json.dumps({
                    "observations": [],
                    "decisions": [{"decision_id": "d", "entity_id": "e", "decision_at": "0001-01-01T00:00:00+14:00"}],
                    ("specs" if command == "build" else "rolling_specs"):
                        ([{"source": "s", "feature": "f"}] if command == "build" else
                         [{"name": "f", "source": "s", "feature": "f", "window_days": 1}]),
                }), encoding="utf-8")
                output = directory / "output"
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = main([command, "--inputs", str(source), "--out", str(output)])
                self.assertEqual(result, 2)
                self.assertIn("UTC datetime range", stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")
                self.assertFalse(output.exists())
