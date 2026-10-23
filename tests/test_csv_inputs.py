"""Installed CSV intake must preserve the temporal and source-data contracts."""

import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from pitbridge import load_csv_inputs
from pitbridge.bundle import artifacts, decode_inputs, verify_bundle
from pitbridge.cli import main
from pitbridge.core import build_snapshot, reference_snapshot
from pitbridge.rolling_bundle import rolling_artifacts, rolling_demo_inputs, verify_rolling_bundle


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "csv"


class CSVInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "csv"
        self.directory.mkdir()
        self.tables = {}
        for path in EXAMPLES.glob("*.csv"):
            with path.open(encoding="utf-8", newline="") as handle:
                self.tables[path.stem] = list(csv.reader(handle))
        self.write_tables()

    def write_tables(self):
        for name, rows in self.tables.items():
            with (self.directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)

    def load(self, *, rolling=False):
        self.write_tables()
        return load_csv_inputs(self.directory, rolling=rolling)

    def change(self, table, field, value, row=1):
        self.tables[table][row][self.tables[table][0].index(field)] = value

    def rolling_tables(self):
        data = rolling_demo_inputs()
        for section in ("observations", "decisions", "rolling_specs"):
            headers = list(data[section][0])
            self.tables[section] = [headers] + [
                ["" if row[key] is None else str(row[key]).lower() if isinstance(row[key], bool)
                 else str(row[key]) for key in headers] for row in data[section]
            ]
        return data

    def test_scalar_selections_and_full_evidence_match_json(self):
        data = self.load()
        inputs = decode_inputs(data)
        rows = build_snapshot(*inputs)
        self.assertEqual(rows, reference_snapshot(*inputs))
        self.assertEqual([(r.record_id, r.value, r.status) for r in rows], [
            (None, None, "not_available"), ("invoice-v1", 100000.0, "selected"),
            ("invoice-v2", 135000.0, "selected")])
        self.assertEqual(artifacts(data), artifacts(json.loads(json.dumps(data))))
        self.assertEqual(data["data_kind"], "user_supplied")

    def test_int64_revision_never_rounds_through_float(self):
        for revision in (2**53 + 1, 2**63 - 1):
            self.change("observations", "revision", str(revision), row=2)
            rows = build_snapshot(*decode_inputs(self.load()))
            self.assertEqual(rows[-1].revision, revision)

    def test_numeric_identifiers_and_na_text_are_preserved(self):
        for table in ("observations", "decisions"):
            for row in range(1, len(self.tables[table])):
                self.change(table, "entity_id", "0001", row)
        self.change("observations", "record_id", "NA")
        self.change("decisions", "decision_id", "NULL")
        data = self.load()
        self.assertTrue(all(row["entity_id"] == "0001" for row in data["observations"] + data["decisions"]))
        self.assertIn("NA", [row["record_id"] for row in data["observations"]])
        self.assertIn("NULL", [row["decision_id"] for row in data["decisions"]])

    def test_timezone_offsets_preserve_instants(self):
        expected = artifacts(self.load())
        self.change("observations", "ingested_at", "2026-02-06T08:00:00+08:00")
        self.change("decisions", "decision_at", "2026-02-14T19:00:00-05:00", row=2)
        self.assertEqual(artifacts(self.load()), expected)

    def test_empty_numeric_cells_and_tombstones(self):
        self.change("specs", "max_age_days", "")
        self.change("observations", "deleted", "true", row=2)
        self.change("observations", "value", "", row=2)
        data = self.load()
        self.assertIsNone(data["specs"][0]["max_age_days"])
        rows = build_snapshot(*decode_inputs(data))
        self.assertEqual(rows[-1].status, "deleted")
        self.assertIsNone(rows[-1].value)

    def test_header_only_observations_preserve_missingness(self):
        self.tables["observations"] = self.tables["observations"][:1]
        rows = build_snapshot(*decode_inputs(self.load()))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.status == "no_history" and row.value is None for row in rows))

    def test_reordered_columns_and_rows_produce_identical_evidence(self):
        expected = artifacts(self.load())
        for table in self.tables:
            header, *rows = self.tables[table]
            self.tables[table] = [header[::-1], *[row[::-1] for row in rows[::-1]]]
        self.assertEqual(artifacts(self.load()), expected)

    def test_bom_blank_records_and_multiline_identifiers(self):
        self.change("observations", "record_id", "invoice,\n\nv1")
        expected = artifacts(self.load())
        for name in self.tables:
            path = self.directory / f"{name}.csv"
            path.write_bytes(b"\xef\xbb\xbf\r\n \t\r\n" + path.read_bytes() + b"\r\n\t \r\n")
        self.assertEqual(artifacts(load_csv_inputs(self.directory)), expected)

    def test_invalid_revision_and_booleans_name_the_physical_row(self):
        original = copy.deepcopy(self.tables)
        for field, values in (("revision", ("1.0", "1e3", "-1", "0", " 1", "true", str(2**63), "9" * 5000)),
                              ("deleted", ("True", "False", "1", "0", "", "yes"))):
            for value in values:
                self.tables = copy.deepcopy(original)
                self.change("observations", field, value)
                with self.subTest(field=field, value=value[:30]), self.assertRaisesRegex(
                        ValueError, f"observations.csv row 2: .*{field}"):
                    self.load()

    def test_invalid_numbers_never_become_missing_or_nonfinite_features(self):
        for table, field in (("observations", "value"), ("specs", "max_age_days")):
            for value in ("NA", "NULL", "NaN", "nan", "inf", "Infinity", "1_000", "1,000", "0x10", "true", "1e1000"):
                original = copy.deepcopy(self.tables)
                self.change(table, field, value)
                with self.subTest(table=table, value=value), self.assertRaises(ValueError):
                    self.load()
                self.tables = original

    def test_temporal_and_tombstone_errors_are_not_repaired(self):
        for field, value in (("event_at", "2026-01-31"), ("ingested_at", "2026-01-01T00:00:00Z"),
                             ("value", ""), ("deleted", "true")):
            original = copy.deepcopy(self.tables)
            self.change("observations", field, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "observations.csv row 2"):
                self.load()
            self.tables = original

    def test_duplicate_and_mismatched_identities_fail(self):
        original = copy.deepcopy(self.tables)
        for table in ("observations", "decisions", "specs"):
            self.tables = copy.deepcopy(original)
            self.tables[table].append(self.tables[table][1][:])
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, "duplicate"):
                self.load()
        self.tables = original
        self.change("specs", "source", "other")
        with self.assertRaisesRegex(ValueError, "explicit feature spec"):
            self.load()

    def test_wrong_headers_and_record_width_in_every_table(self):
        original = copy.deepcopy(self.tables)
        for table in original:
            for mutation in ("header_duplicate", "header_extra", "header_missing", "row_extra", "row_missing"):
                self.tables = copy.deepcopy(original)
                rows = self.tables[table]
                if mutation == "header_duplicate":
                    rows[0][-1] = rows[0][0]
                elif mutation == "header_extra":
                    rows[0].append("unexpected")
                elif mutation == "header_missing":
                    rows[0].pop()
                elif mutation == "row_extra":
                    rows[1].append("undeclared")
                else:
                    rows[1].pop()
                with self.subTest(table=table, mutation=mutation), self.assertRaisesRegex(ValueError, f"{table}.csv"):
                    self.load()

    def test_malformed_quoting_and_encoding(self):
        for name in self.tables:
            path = self.directory / f"{name}.csv"
            for suffix, message in ((b'"unclosed\ncontinued\n', "malformed CSV quoting"),
                                    (b"\xff\n", "UTF-8")):
                self.write_tables()
                header = path.read_bytes().splitlines()[0] + b"\n"
                path.write_bytes(header + suffix)
                with self.subTest(table=name, message=message), self.assertRaisesRegex(ValueError, message):
                    load_csv_inputs(self.directory)

    def test_multiline_error_names_physical_end_line(self):
        self.change("observations", "record_id", "invoice\nv1")
        self.change("observations", "revision", "1.5")
        with self.assertRaisesRegex(ValueError, "observations.csv row 3: .*revision"):
            self.load()

    def test_missing_or_empty_file_is_rejected(self):
        for name in self.tables:
            path = self.directory / f"{name}.csv"
            self.write_tables()
            path.unlink()
            with self.subTest(table=name), self.assertRaises(OSError):
                load_csv_inputs(self.directory)
            self.write_tables()
            path.write_text(" \n\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no header"):
                load_csv_inputs(self.directory)

    def test_rolling_values_and_membership_match_json(self):
        original = self.rolling_tables()
        original["data_kind"] = "user_supplied"
        self.assertEqual(rolling_artifacts(self.load(rolling=True)), rolling_artifacts(original))

    def test_large_integer_source_value_is_retained_before_binary64_conversion(self):
        self.change("observations", "value", str(2**53 + 1))
        data = self.load()
        self.assertEqual(data["observations"][0]["value"], 2**53 + 1)
        self.assertEqual(build_snapshot(*decode_inputs(data))[1].value, float(2**53 + 1))

    def test_rolling_invalid_contracts_fail_before_writing(self):
        self.rolling_tables()
        for field, value in (("window_days", ""), ("window_days", "NA"), ("window_days", "0"),
                             ("window_days", "1e1000"), ("aggregation", "median")):
            original = copy.deepcopy(self.tables)
            self.change("rolling_specs", field, value)
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "rolling_specs.csv row 2"):
                self.load(rolling=True)
            self.tables = original

    def call(self, args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(args)
        return status, output.getvalue(), error.getvalue()

    def test_cli_scalar_and_rolling_generate_replayable_reports(self):
        scalar = self.root / "scalar"
        status, output, error = self.call(["build", "--csv-dir", str(self.directory), "--out", str(scalar)])
        self.assertEqual((status, error), (0, ""))
        self.assertEqual(json.loads(output)["data_kind"], "user_supplied")
        self.assertTrue(verify_bundle(scalar)["verified"])
        self.rolling_tables()
        self.write_tables()
        rolling = self.root / "rolling"
        status, _, error = self.call(["aggregate", "--csv-dir", str(self.directory), "--out", str(rolling)])
        self.assertEqual((status, error), (0, ""))
        self.assertTrue(verify_rolling_bundle(rolling)["verified"])

    def test_cli_failure_never_creates_or_changes_output(self):
        for command in ("build", "aggregate"):
            if command == "aggregate":
                self.rolling_tables()
            self.change("observations", "revision", "1.5")
            self.write_tables()
            target = self.root / command
            args = [command, "--csv-dir", str(self.directory), "--out", str(target)]
            status, output, error = self.call(args)
            self.assertEqual((status, output), (2, ""))
            self.assertIn("observations.csv row 2", error)
            self.assertFalse(target.exists())
            target.mkdir()
            sentinel = target / "manifest.json"
            sentinel.write_bytes(b"retained evidence\n")
            self.assertEqual(self.call(args)[0], 2)
            self.assertEqual(sentinel.read_bytes(), b"retained evidence\n")
            self.assertEqual(list(target.iterdir()), [sentinel])

    def test_cli_requires_exactly_one_input_route(self):
        for command in ("build", "aggregate"):
            for args in ([command], [command, "--inputs", "unused.json", "--csv-dir", str(self.directory)]):
                with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                    main(args)
                self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
