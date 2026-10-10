import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from pitbridge import build_snapshot, reference_snapshot


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
adapter = runpy.run_path(str(EXAMPLES / "pandas_csv.py"))


class RevisionTests(unittest.TestCase):
    def test_revisions_are_exact_and_strict(self):
        convert = adapter["revision_value"]
        for value in (1, 2**53 + 1, 2**63 - 1):
            self.assertEqual(convert(str(value)), value)
        for value in ("", "1.0", "1.5", "1e3", "NaN", "inf", "true",
                      "-1", "0", " 1", str(2**63), True, 1, 1.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "revision"):
                convert(value)


@unittest.skipUnless(importlib.util.find_spec("pandas"), "optional pandas is not installed")
class PandasCSVTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.tables = {}
        for path in (EXAMPLES / "csv").glob("*.csv"):
            with path.open(encoding="utf-8", newline="") as stream:
                self.tables[path.stem] = list(csv.DictReader(stream))

    def load(self):
        for name, rows in self.tables.items():
            with (self.directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        return adapter["load_inputs"](self.directory)

    def snapshots(self):
        inputs = self.load()
        actual = build_snapshot(*inputs)
        self.assertEqual(actual, reference_snapshot(*inputs))
        return actual

    def test_full_output_matches_existing_example(self):
        canonical = io.StringIO()
        with contextlib.redirect_stdout(canonical):
            runpy.run_path(str(EXAMPLES / "decision_time.py"), run_name="__main__")
        actual = io.StringIO()
        with contextlib.redirect_stdout(actual):
            adapter["main"]()
        self.assertEqual(json.loads(actual.getvalue()), json.loads(canonical.getvalue()))
        self.snapshots()

    def test_timezone_offsets_preserve_instants(self):
        self.tables["observations"][0]["ingested_at"] = "2026-02-06T08:00:00+08:00"
        self.tables["decisions"][1]["decision_at"] = "2026-02-14T19:00:00-05:00"
        self.assertEqual(self.snapshots(), build_snapshot(*adapter["load_inputs"]()))

    def test_int64_revision_survives_csv_and_sql(self):
        self.tables["observations"][1]["revision"] = str(2**63 - 1)
        self.assertEqual(self.snapshots()[-1].revision, 2**63 - 1)

    def test_tombstone_does_not_restore_previous_revision(self):
        self.tables["observations"][1].update(deleted="true", value="")
        rows = self.snapshots()
        self.assertEqual(rows[1].record_id, "invoice-v1")
        self.assertEqual(rows[2].status, "deleted")
        self.assertIsNone(rows[2].value)
        self.assertIsNone(rows[2].record_id)

    def test_missing_feature_and_na_identifier_are_preserved(self):
        self.tables["specs"].append(dict(source="bank", feature="cash", max_age_days=""))
        for name in ("observations", "decisions"):
            for row in self.tables[name]:
                row["entity_id"] = "NA"
        rows = self.snapshots()
        missing = [r for r in rows if r.source == "bank"]
        self.assertEqual(len(missing), 3)
        self.assertTrue(all(r.status == "no_history" and r.value is None for r in missing))
        self.assertTrue(all(r.entity_id == "NA" for r in rows))

    def test_errors_name_file_row_and_contract(self):
        original = self.tables["observations"][0].copy()
        for fields, error in (({"revision": "1.5"}, "revision"),
                              ({"revision": ""}, "revision"),
                              ({"deleted": "yes"}, "deleted"),
                              ({"value": ""}, "active observations"),
                              ({"value": "NA"}, "convert string"),
                              ({"value": "nan"}, "finite"),
                              ({"deleted": "true"}, "tombstone"),
                              ({"event_at": "2026-01-31"}, "naive timestamps")):
            self.tables["observations"][0] = original | fields
            with self.subTest(fields=fields), self.assertRaisesRegex(
                    ValueError, f"observations.csv row 2: .*{error}"):
                self.load()

    def test_naive_decision_is_rejected(self):
        self.tables["decisions"][0]["decision_at"] = "2026-02-01"
        with self.assertRaisesRegex(ValueError, "decisions.csv row 2: .*naive timestamps"):
            self.load()

    def test_wrong_headers_are_rejected(self):
        for row in self.tables["observations"]:
            row["unexpected"] = "0"
        with self.assertRaisesRegex(ValueError, "observations.csv: expected columns"):
            self.load()


if __name__ == "__main__":
    unittest.main()
