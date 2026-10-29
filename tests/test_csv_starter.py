"""A wheel user can create, edit and replay tables without repository examples."""

import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from pitbridge.bundle import decode_inputs, verify_bundle
from pitbridge.cli import main
from pitbridge.core import build_snapshot
from pitbridge.csv_inputs import load_csv_inputs
from pitbridge.csv_starter import write_csv_starter
from pitbridge.rolling import build_rolling
from pitbridge.rolling_bundle import decode_rolling, verify_rolling_bundle


class CSVStarterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_scalar_case_has_hand_checked_selection_and_full_replay(self):
        inputs = self.root / "editable inputs"
        code, stdout, stderr = self.run_cli("init-csv", "--out", str(inputs))
        self.assertEqual((code, stderr), (0, ""))
        metadata = json.loads(stdout)
        self.assertEqual((metadata["data_kind"], metadata["observations"], metadata["decisions"]),
                         ("synthetic", 11, 15))
        self.assertEqual(set(metadata["files"]),
                         {"observations.csv", "decisions.csv", "specs.csv", "README.md"})
        rows = build_snapshot(*decode_inputs(load_csv_inputs(inputs)))
        self.assertEqual(len(rows), 45)
        self.assertEqual(sum(row.status == "selected" for row in rows), 16)
        selected = {(row.decision_id, row.source): row for row in rows}
        self.assertEqual(selected["SME-A-2", "tax"].record_id, "tax-a-v1")
        self.assertEqual(selected["SME-A-2", "tax"].value, 100000)
        self.assertEqual(selected["SME-B-3", "bank"].record_id, "cash-b-v2")
        self.assertEqual(selected["SME-A-3", "bank"].status, "deleted")
        before = {path.name: path.read_bytes() for path in inputs.iterdir()}
        report = self.root / "scalar report"
        self.assertEqual(self.run_cli("build", "--csv-dir", str(inputs), "--out", str(report))[0], 0)
        self.assertTrue(verify_bundle(report)["independent_replay"])
        self.assertEqual({path.name: path.read_bytes() for path in inputs.iterdir()}, before)

    def test_editing_an_arrival_changes_only_the_eligible_revision(self):
        inputs = self.root / "inputs"
        write_csv_starter(inputs)
        before = build_snapshot(*decode_inputs(load_csv_inputs(inputs)))
        path = inputs / "observations.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns, records = reader.fieldnames, list(reader)
        for row in records:
            if row["record_id"] == "tax-a-v2":
                row["ingested_at"] = "2026-04-03T00:00:00Z"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        after = build_snapshot(*decode_inputs(load_csv_inputs(inputs)))
        def values(rows):
            return {row.decision_id: row.value for row in rows if row.source == "tax"}
        self.assertEqual((values(before)["SME-A-4"], values(after)["SME-A-4"]), (180000, 100000))
        self.assertEqual(values(after)["SME-A-5"], 220000)

    def test_rolling_case_retains_hand_computed_sums_and_members(self):
        inputs = self.root / "rolling inputs"
        result = write_csv_starter(inputs, rolling=True)
        self.assertEqual((result["observations"], result["decisions"], result["specifications"]), (10, 4, 3))
        self.assertTrue((inputs / "rolling_specs.csv").is_file())
        self.assertFalse((inputs / "specs.csv").exists())
        rows, members = build_rolling(*decode_rolling(load_csv_inputs(inputs, rolling=True)))
        sums = [row.value for row in rows if row.name == "net_inflow_30d" and row.entity_id == "SME-A"]
        self.assertEqual(sums, [1500, 4300, 6300])
        selected = {row.record_id for row in members if row.decision_id == "SME-A-10"}
        self.assertIn("boundary", selected)
        self.assertNotIn("cancel-v1", selected)
        self.assertNotIn("cash-v2", selected)
        self.assertNotIn("late", selected)
        report = self.root / "rolling report"
        self.assertEqual(self.run_cli("aggregate", "--csv-dir", str(inputs), "--out", str(report))[0], 0)
        self.assertTrue(verify_rolling_bundle(report)["independent_temporal_replay"])

    def test_existing_paths_are_refused_without_changing_any_bytes(self):
        for kind in ("directory", "file"):
            with self.subTest(kind=kind):
                target = self.root / kind
                if kind == "directory":
                    target.mkdir()
                    sentinel = target / "observations.csv"
                else:
                    sentinel = target
                sentinel.write_bytes(b"keep my edited inputs")
                code, stdout, stderr = self.run_cli("init-csv", "--out", str(target))
                self.assertEqual((code, stdout), (2, ""))
                self.assertIn("existing paths are never overwritten", stderr)
                self.assertEqual(sentinel.read_bytes(), b"keep my edited inputs")

    def test_unicode_paths_write_utf8_tables_and_ascii_console_json(self):
        path = self.root / "输入 inputs"
        buffer = io.BytesIO()
        stdout = io.TextIOWrapper(buffer, encoding="ascii", write_through=True)
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["init-csv", "--out", str(path)]), 0)
        self.assertEqual(json.loads(buffer.getvalue())["mode"], "scalar")
        for table in path.glob("*.csv"):
            self.assertNotIn(b"\r\n", table.read_bytes())
            table.read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC", (path / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
