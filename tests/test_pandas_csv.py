import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from pitbridge import build_snapshot, load_csv_inputs, reference_snapshot
from pitbridge.bundle import decode_inputs


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

    def test_long_revisions_keep_the_int64_contract(self):
        convert = adapter["revision_value"]
        for value in (1, 2**53 + 1, 2**63 - 1):
            with self.subTest(value=value):
                self.assertEqual(convert("0" * 5000 + str(value)), value)
        for value in ("0" * 5000, "9" * 5000, "0" * 5000 + str(2**63)):
            with self.subTest(value=value[-20:]), self.assertRaisesRegex(
                    ValueError, "revision must be a positive int64 integer"):
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

    def test_numeric_text_is_validated_before_conversion(self):
        for table, column in (("observations", "value"), ("specs", "max_age_days")):
            original = self.tables[table][0][column]
            for value in ("1_0", " 10", "10 ", "\t10", "\uff11\uff10", "\u0661\u0660",
                          "1,000", "0x10", "true", "NA", "NULL", "NaN", "inf", "1e1000"):
                self.tables[table][0][column] = value
                with self.subTest(table=table, value=value):
                    with self.assertRaisesRegex(
                            ValueError, rf"{table}\.csv row 2: .*{column}"):
                        self.load()
                    with self.assertRaises(ValueError):
                        load_csv_inputs(self.directory)
            self.tables[table][0][column] = original

    def test_decimal_and_scientific_values_match_native_csv(self):
        self.tables["specs"][0]["max_age_days"] = "9e1"
        for text, expected in (("0", 0.0), ("-0", -0.0), ("+0012", 12.0),
                               ("-12.5", -12.5), (".5", 0.5), ("1.", 1.0),
                               ("1e3", 1000.0), ("2.5E+2", 250.0), ("1e-3", 0.001)):
            self.tables["observations"][0]["value"] = text
            with self.subTest(value=text):
                rows = self.snapshots()
                self.assertEqual(rows[1].value, expected)
                self.assertEqual(rows, build_snapshot(*decode_inputs(load_csv_inputs(self.directory))))

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
                              ({"value": "NA"}, "decimal number"),
                              ({"value": "nan"}, "decimal number"),
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

    def test_wrong_record_width_is_rejected_in_every_table(self):
        for name in self.tables:
            for shape in ("extra_first", "extra_last", "missing"):
                for multiline in (False, True):
                    with self.subTest(table=name, shape=shape, multiline=multiline):
                        self.load()
                        path = self.directory / f"{name}.csv"
                        with path.open(encoding="utf-8", newline="") as handle:
                            header, *rows = csv.reader(handle)
                        if multiline:
                            rows[0][0] += "\ncontinued"
                        if shape == "extra_first":
                            rows = [["UNDECLARED-FIELD", *row] for row in rows]
                        elif shape == "extra_last":
                            rows = [[*row, "UNDECLARED-FIELD"] for row in rows]
                        else:
                            rows = [row[:-1] for row in rows]
                        with path.open("w", encoding="utf-8", newline="") as handle:
                            csv.writer(handle).writerows([header, *rows])
                        end_line = 3 if multiline else 2
                        actual_width = len(header) - 1 if shape == "missing" else len(header) + 1
                        with self.assertRaisesRegex(
                                ValueError,
                                rf"{name}\.csv row {end_line}: expected {len(header)} fields, "
                                rf"got {actual_width}"):
                            adapter["load_inputs"](self.directory)

    def test_malformed_quoting_names_file_and_physical_end_line(self):
        for name in self.tables:
            for location in ("header", "record"):
                with self.subTest(table=name, location=location):
                    self.load()
                    path = self.directory / f"{name}.csv"
                    header = path.read_text(encoding="utf-8").splitlines()[0]
                    prefix = "" if location == "header" else header + "\n"
                    path.write_text(prefix + '"unclosed\ncontinued\n', encoding="utf-8")
                    end_line = 2 if location == "header" else 3
                    with self.assertRaisesRegex(
                            ValueError,
                            rf"{name}\.csv row {end_line}: malformed CSV quoting"):
                        adapter["load_inputs"](self.directory)

    def test_quoted_commas_and_multiline_fields_are_preserved(self):
        entity, source, record = "SME,\n001", "tax,\nfeed", "invoice,\n\nv1"
        for name in ("observations", "decisions"):
            for row in self.tables[name]:
                row["entity_id"] = entity
        for row in self.tables["observations"]:
            row.update(source=source, feature="revenue,net")
        self.tables["observations"][0]["record_id"] = record
        self.tables["specs"][0].update(source=source, feature="revenue,net")
        rows = self.snapshots()
        self.assertEqual(rows[1].record_id, record)
        self.assertTrue(all(row.entity_id == entity and row.source == source for row in rows))

    def test_bom_and_unquoted_blank_records_remain_supported(self):
        expected = self.snapshots()
        for name in self.tables:
            path = self.directory / f"{name}.csv"
            original = path.read_bytes()
            path.write_bytes(b"\xef\xbb\xbf\r\n \t\r\n" + original + b"\r\n\t \r\n")
        self.assertEqual(build_snapshot(*adapter["load_inputs"](self.directory)), expected)

    def test_multiline_conversion_error_uses_physical_end_line(self):
        self.tables["observations"][0].update(record_id="invoice\nv1", revision="1.5")
        with self.assertRaisesRegex(ValueError, "observations.csv row 3: .*revision"):
            self.load()


if __name__ == "__main__":
    unittest.main()
