from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import contextlib
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from pitbridge.bundle import canonical, read_json
from pitbridge.cli import main
from pitbridge.core import Decision, Observation
from pitbridge.rolling import RollingSpec, build_rolling, reference_rolling
from pitbridge.rolling_bundle import decode_rolling, rolling_artifacts, rolling_demo_inputs, verify_rolling_bundle, write_rolling_bundle


def observation(record_id, event, value, revision=1, published=None, ingested=None, deleted=False):
    return Observation(record_id, "A", "bank", "cash", event, published or event,
                       ingested or published or event, revision, value, deleted)


def spec(name="cash_30d", days=30, aggregation="sum"):
    return RollingSpec(name, "bank", "cash", days, aggregation)


class RollingTests(unittest.TestCase):
    def test_hand_auditable_demo_sums_and_members(self):
        data = decode_rolling(rolling_demo_inputs())
        features, members = build_rolling(*data)
        sums = {row.decision_id: row.value for row in features if row.name == "net_inflow_30d"}
        self.assertEqual(sums, {"SME-A-10": 1500, "SME-A-11": 4300, "SME-A-12": 6300, "SME-B-12": None})
        first = {row.record_id for row in members if row.decision_id == "SME-A-10" and row.name == "net_inflow_30d"}
        self.assertEqual(first, {"boundary", "cash-v1", "refund", "recent"})
        self.assertEqual((features, members), reference_rolling(*data))

    def test_both_window_boundaries_are_inclusive_to_microseconds(self):
        rows = [observation("lower", "2026-01-01T00:00:00Z", 10),
                observation("too-old", "2025-12-31T23:59:59.999999Z", 100),
                observation("upper", "2026-01-02T00:00:00Z", 2),
                observation("future", "2026-01-02T00:00:00.000001Z", 1000)]
        result, members = build_rolling(rows, [Decision("D", "A", "2026-01-02T00:00:00Z")], [spec(days=1)])
        self.assertEqual(result[0].value, 12)
        self.assertEqual({row.record_id for row in members}, {"lower", "upper"})

    def test_later_ingestion_controls_availability(self):
        row = observation("late", "2026-01-01T00:00:00Z", 10,
                          published="2026-01-02T00:00:00Z", ingested="2026-01-04T00:00:00Z")
        result, members = build_rolling([row], [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec()])
        self.assertEqual(result[0].status, "not_available")
        self.assertIsNone(result[0].value)
        self.assertEqual(members, [])

    def test_later_publication_also_controls_availability(self):
        row = observation("late", "2026-01-01T00:00:00Z", 10,
                          published="2026-01-04T00:00:00Z", ingested="2026-01-02T00:00:00Z")
        result, _ = build_rolling([row], [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec()])
        self.assertEqual(result[0].status, "not_available")

    def test_highest_known_revision_wins_over_last_arrival(self):
        rows = [observation("v2", "2026-01-01T00:00:00Z", 20, 2, "2026-01-02T00:00:00Z"),
                observation("v1-late", "2026-01-01T00:00:00Z", 10, 1, "2026-01-03T00:00:00Z")]
        result, members = build_rolling(rows, [Decision("D", "A", "2026-01-04T00:00:00Z")], [spec()])
        self.assertEqual(result[0].value, 20)
        self.assertEqual([row.record_id for row in members], ["v2"])

    def test_tombstone_removes_one_event_without_resurrecting_its_revision(self):
        rows = [observation("older-event", "2026-01-01T00:00:00Z", 10),
                observation("v1", "2026-01-02T00:00:00Z", 20),
                observation("v2", "2026-01-02T00:00:00Z", None, 2, "2026-01-03T00:00:00Z", deleted=True)]
        result, members = build_rolling(rows, [Decision("D", "A", "2026-01-04T00:00:00Z")], [spec()])
        self.assertEqual(result[0].value, 10)
        self.assertEqual([row.record_id for row in members], ["older-event"])

    def test_future_historical_correction_does_not_change_earlier_features(self):
        rows = [observation("v1", "2026-01-01T00:00:00Z", 10)]
        decision = [Decision("D", "A", "2026-01-03T00:00:00Z")]
        before = build_rolling(rows, decision, [spec()])
        rows.append(observation("v2", "2026-01-01T00:00:00Z", 200, 2, "2026-02-01T00:00:00Z"))
        self.assertEqual(before, build_rolling(rows, decision, [spec()]))

    def test_real_zero_and_negative_values_remain_selected(self):
        rows = [observation("income", "2026-01-01T00:00:00Z", 100),
                observation("refund", "2026-01-02T00:00:00Z", -100)]
        result, _ = build_rolling(rows, [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec()])
        self.assertEqual((result[0].value, result[0].status, result[0].observation_count), (0, "selected", 2))

    def test_empty_count_is_missing_not_an_imputed_business_zero(self):
        result, members = build_rolling([], [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec(aggregation="count")])
        self.assertEqual((result[0].value, result[0].observation_count, result[0].status), (None, 0, "no_history"))
        self.assertEqual(members, [])

    def test_fully_deleted_window_has_an_explicit_reason(self):
        rows = [observation("v1", "2026-01-01T00:00:00Z", 10),
                observation("v2", "2026-01-01T00:00:00Z", None, 2, "2026-01-02T00:00:00Z", deleted=True)]
        result, _ = build_rolling(rows, [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec()])
        self.assertEqual((result[0].value, result[0].status), (None, "deleted"))

    def test_multiple_windows_have_distinct_membership_and_means(self):
        rows = [observation("old", "2026-01-01T00:00:00Z", 100),
                observation("new", "2026-01-09T00:00:00Z", 10)]
        specs = [spec("sum", 30), spec("mean", 30, "mean"), spec("count", 1, "count")]
        features, members = build_rolling(rows, [Decision("D", "A", "2026-01-10T00:00:00Z")], specs)
        self.assertEqual({row.name: row.value for row in features}, {"sum": 110, "mean": 55, "count": 1})
        self.assertEqual([row.record_id for row in members if row.name == "count"], ["new"])

    def test_invalid_window_contracts_are_rejected(self):
        for days in (0, -1, True, float("nan"), float("inf"), 1e-20, 3652501):
            with self.subTest(days=days), self.assertRaises(ValueError):
                spec(days=days)
        with self.assertRaises(ValueError):
            spec(aggregation="median")

    def test_duplicate_output_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            build_rolling([], [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec(), spec(days=7)])

    def test_duplicate_source_revision_is_rejected(self):
        row = observation("v1", "2026-01-01T00:00:00Z", 10)
        with self.assertRaisesRegex(ValueError, "logical revision"):
            build_rolling([row, replace(row, record_id="duplicate")], [Decision("D", "A", "2026-01-03T00:00:00Z")], [spec()])

    def test_compensated_sum_survives_large_cancellation(self):
        rows = [observation(str(i), f"2026-01-0{i+1}T00:00:00Z", value)
                for i, value in enumerate((1e16, 1, -1e16))]
        data = (rows, [Decision("D", "A", "2026-01-04T00:00:00Z")], [spec()])
        self.assertEqual(build_rolling(*data)[0][0].value, 1)
        self.assertEqual(build_rolling(*data), reference_rolling(*data))

    def test_sum_overflow_is_rejected_but_count_is_valid(self):
        rows = [observation(str(i), f"2026-01-0{i+1}T00:00:00Z", 1e308) for i in range(2)]
        decisions = [Decision("D", "A", "2026-01-04T00:00:00Z")]
        with self.assertRaisesRegex(ValueError, "binary64"):
            build_rolling(rows, decisions, [spec()])
        with self.assertRaisesRegex(ValueError, "binary64"):
            reference_rolling(rows, decisions, [spec()])
        self.assertEqual(build_rolling(rows, decisions, [spec(aggregation="count")])[0][0].value, 2)

    def test_randomized_revision_histories_match_independent_temporal_oracle(self):
        rng = random.Random(20261002)
        anchor = datetime(2026, 2, 1, tzinfo=timezone.utc)
        for trial in range(60):
            rows = []
            for entity in ("A", "B"):
                for event in range(8):
                    time = anchor + timedelta(days=rng.randint(-35, 10), seconds=event)
                    for revision in range(1, rng.randint(1, 3)+1):
                        deleted = rng.random() < 0.2
                        rows.append(Observation(f"{entity}-{event}-{revision}", entity, "bank", "cash",
                            time.isoformat(), (time+timedelta(days=rng.randint(0, 12))).isoformat(),
                            (time+timedelta(days=rng.randint(0, 15))).isoformat(), revision,
                            None if deleted else rng.randint(-100, 200)/2, deleted))
            decisions = [Decision(f"{entity}-{day}", entity, (anchor+timedelta(days=day)).isoformat())
                         for entity in ("A", "B") for day in (0, 5, 10)]
            specs = [spec("sum", 30), spec("mean", 7, "mean"), spec("count", 1, "count")]
            with self.subTest(trial=trial):
                self.assertEqual(build_rolling(rows, decisions, specs), reference_rolling(rows, decisions, specs))

    def test_input_order_does_not_change_features_or_lineage(self):
        rows, decisions, specs = decode_rolling(rolling_demo_inputs())
        self.assertEqual(build_rolling(rows, decisions, specs), build_rolling(rows[::-1], decisions[::-1], specs[::-1]))


class RollingBundleTests(unittest.TestCase):
    def rehash(self, root, filename):
        manifest = read_json(root/"manifest.json")
        manifest["files"][filename] = sha256((root/filename).read_bytes()).hexdigest()
        (root/"manifest.json").write_text(canonical(manifest))

    def test_full_bundle_replays_and_is_deterministic(self):
        self.assertEqual(rolling_artifacts(rolling_demo_inputs()), rolling_artifacts(rolling_demo_inputs()))
        with tempfile.TemporaryDirectory() as directory:
            write_rolling_bundle(rolling_demo_inputs(), directory)
            self.assertTrue(verify_rolling_bundle(directory)["verified"])

    def test_rehashed_feature_fabrication_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_rolling_bundle(rolling_demo_inputs(), root)
            content = (root/"features.csv").read_text()
            self.assertIn("1500.0", content)
            (root/"features.csv").write_text(content.replace("1500.0", "1501.0", 1))
            self.rehash(root, "features.csv")
            with self.assertRaisesRegex(ValueError, "semantic replay"):
                verify_rolling_bundle(root)

    def test_rehashed_member_fabrication_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_rolling_bundle(rolling_demo_inputs(), root)
            content = (root/"members.csv").read_text()
            (root/"members.csv").write_text(content.replace("cash-v1", "cash-v2", 1))
            self.rehash(root, "members.csv")
            with self.assertRaisesRegex(ValueError, "semantic replay"):
                verify_rolling_bundle(root)

    def test_rehashed_summary_fabrication_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_rolling_bundle(rolling_demo_inputs(), root)
            summary = read_json(root/"summary.json")
            summary["member_rows"] += 1
            (root/"summary.json").write_text(canonical(summary))
            self.rehash(root, "summary.json")
            with self.assertRaisesRegex(ValueError, "semantic replay"):
                verify_rolling_bundle(root)

    def test_empty_membership_still_exports_and_replays(self):
        data = rolling_demo_inputs()
        data["observations"] = []
        with tempfile.TemporaryDirectory() as directory:
            write_rolling_bundle(data, directory)
            self.assertEqual(len((Path(directory)/"members.csv").read_text().splitlines()), 1)
            self.assertTrue(verify_rolling_bundle(directory)["verified"])

    def test_identifiers_are_spreadsheet_safe_and_html_escaped(self):
        data = rolling_demo_inputs()
        malicious = '=SUM(1)</script><script>alert("x")</script>'
        data["decisions"][0]["decision_id"] = malicious
        artifacts = rolling_artifacts(data)
        self.assertIn("'=SUM", artifacts["features.csv"])
        self.assertNotIn('<script>alert("x")</script>', artifacts["report.html"])
        self.assertIn("&lt;/script&gt;", artifacts["report.html"])

    def test_cli_demo_custom_input_and_verifier(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            self.assertEqual(main(["rolling-demo", "--out", str(root/"a")]), 0)
            self.assertEqual(main(["aggregate", "--inputs", str(root/"a/inputs.json"), "--out", str(root/"b")]), 0)
            self.assertEqual(main(["verify-rolling", "--out", str(root/"b")]), 0)

    def test_strict_input_schema_rejects_unknown_fields(self):
        data = rolling_demo_inputs()
        data["specs"] = []
        with self.assertRaises(ValueError):
            decode_rolling(data)
