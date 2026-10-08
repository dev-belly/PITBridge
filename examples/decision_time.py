"""A late correction changes a later decision, never an earlier one.

Run from the repository root after installing PITBridge:
    python examples/decision_time.py
All values are synthetic CNY amounts.
"""

from dataclasses import asdict
import json

from pitbridge import (
    Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot,
)


def main():
    observations = [
        Observation(
            record_id="invoice-v1", entity_id="SME-001", source="tax",
            feature="invoice_revenue", event_at="2026-01-31T00:00:00Z",
            published_at="2026-02-05T00:00:00Z",
            ingested_at="2026-02-06T00:00:00Z", revision=1, value=100000,
        ),
        Observation(
            record_id="invoice-v2", entity_id="SME-001", source="tax",
            feature="invoice_revenue", event_at="2026-01-31T00:00:00Z",
            published_at="2026-04-01T00:00:00Z",
            ingested_at="2026-04-03T00:00:00Z", revision=2, value=135000,
        ),
    ]
    decisions = [
        Decision("01-before-arrival", "SME-001", "2026-02-01T00:00:00Z"),
        Decision("02-original-known", "SME-001", "2026-02-15T00:00:00Z"),
        Decision("03-correction-known", "SME-001", "2026-04-15T00:00:00Z"),
    ]
    specs = [FeatureSpec("tax", "invoice_revenue", max_age_days=90)]
    snapshots = build_snapshot(observations, decisions, specs)
    if snapshots != reference_snapshot(observations, decisions, specs):
        raise RuntimeError("SQL and independent temporal replay disagree")
    print(json.dumps([asdict(row) for row in snapshots], indent=2))


if __name__ == "__main__":
    main()
