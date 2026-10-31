"""Compare the shipped browser lesson with both temporal Python implementations."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import subprocess
import tempfile

from pitbridge import Decision, FeatureSpec, Observation, build_snapshot, load_csv_inputs, reference_snapshot
from pitbridge.bundle import decode_inputs, verify_bundle, write_bundle

ROOT = Path(__file__).resolve().parents[1]


class FixtureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.inside = tag == "script" and dict(attrs).get("id") == "invoice-fixture"

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def main():
    parser = FixtureParser()
    parser.feed((ROOT / "site/try/index.html").read_text(encoding="utf-8"))
    fixture = json.loads("".join(parser.parts))
    observations = [Observation(**row) for row in fixture["observations"]]
    csv_observations, _, csv_specs = decode_inputs(load_csv_inputs(ROOT / "examples/csv"))
    if observations != csv_observations or csv_specs != [FeatureSpec("tax", "invoice_revenue", fixture["max_age_days"])]:
        raise AssertionError("Browser fixture differs from the existing CSV/Python lesson")
    ingestion = "2026-04-03T00:00:00Z"
    cases = [{"decision": at, "ingested": ingestion} for at in (
        "2026-01-30T00:00:00Z", "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z",
        "2026-04-15T00:00:00Z", "2026-05-01T00:00:00Z", "2026-05-01T00:00:00.000001Z",
    )]
    for at in ("2026-04-03T00:00:00Z", "2026-04-03T00:00:00.000001Z"):
        cases.append({"decision": at, "ingested": "2026-04-03T00:00:00.000001Z"})
    rng = random.Random(20261028)
    origin = datetime(2026, 1, 31, tzinfo=timezone.utc)
    for _ in range(60):
        cases.append({
            "decision": (origin + timedelta(days=rng.randrange(-5, 105), microseconds=rng.randrange(3))).isoformat().replace("+00:00", "Z"),
            "ingested": (origin + timedelta(days=rng.randrange(0, 110), microseconds=rng.randrange(3))).isoformat().replace("+00:00", "Z"),
        })
    for field, value in (("decision", "2026-02-30T00:00:00Z"),
                         ("ingested", "2026-04-03T00:00:00.0000009Z"),
                         ("ingested", "2026-01-30T00:00:00Z")):
        cases.append({"decision": "2026-04-03T00:00:00Z", "ingested": ingestion} | {field: value})
    result = subprocess.run(["node", str(ROOT / "scripts/check_trial.mjs"), "--cases"], input=json.dumps(cases), text=True, capture_output=True, check=True)
    actual = json.loads(result.stdout)
    expected = []
    exported = 0
    for case, browser in zip(cases, actual, strict=True):
        try:
            rows = [Observation(**(row | ({"ingested_at": case["ingested"]} if row["revision"] == 2 else {}))) for row in fixture["observations"]]
            decisions = [Decision("trial", "SME-001", case["decision"])]
            specs = [FeatureSpec("tax", "invoice_revenue", fixture["max_age_days"])]
            snapshots = build_snapshot(rows, decisions, specs)
            if snapshots != reference_snapshot(rows, decisions, specs):
                raise AssertionError("SQLite/reference mismatch")
        except ValueError:
            expected.append({"ok": False})
            continue
        selected = snapshots[0]
        portable = browser.pop("inputs")
        expected_inputs = {
            "data_kind": "synthetic",
            "observations": [row | ({"ingested_at": case["ingested"]} if row["revision"] == 2 else {})
                             for row in fixture["observations"]],
            "decisions": [{"decision_id": "trial", "entity_id": "SME-001", "decision_at": case["decision"]}],
            "specs": [{"source": "tax", "feature": "invoice_revenue", "max_age_days": 90}],
        }
        if portable != expected_inputs or build_snapshot(*decode_inputs(portable)) != snapshots:
            raise AssertionError("Exported inputs lose the browser scenario or source records")
        with tempfile.TemporaryDirectory() as directory:
            write_bundle(portable, directory)
            if verify_bundle(directory).get("verified") is not True:
                raise AssertionError("Exported input report did not independently replay")
        exported += 1
        baseline = max((row for row in rows if row.event_at <= decisions[0].decision_at), key=lambda row: row.revision, default=None)
        expected.append({"ok": True, **{key: asdict(selected)[key] for key in ("record_id", "value", "status")},
                         "unsafe_record_id": baseline.record_id if baseline else None,
                         "unsafe_value": baseline.value if baseline else None,
                         "unsafe_future": bool(baseline and baseline.available_at > decisions[0].decision_at)})
    if actual != expected:
        raise AssertionError("Browser/SQL/reference selection mismatch")
    print(json.dumps({"status": "passed", "scenarios": len(cases), "exported_cases_replayed": exported,
                      "engines": ["shipped browser core", "SQLite", "independent Python"]}))


if __name__ == "__main__":
    main()
