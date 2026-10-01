"""Compact, hand-auditable counterexamples across three financial sources."""


def demo_inputs():
    records = []
    def add(rid, entity, source, feature, event, published, ingested, revision, value, deleted=False):
        records.append(dict(record_id=rid, entity_id=entity, source=source, feature=feature, event_at=event+"T00:00:00Z", published_at=published+"T00:00:00Z", ingested_at=ingested+"T00:00:00Z", revision=revision, value=value, deleted=deleted))
    add("tax-a-v1", "SME-A", "tax", "invoice_revenue", "2026-01-31", "2026-02-05", "2026-02-06", 1, 100000)
    add("tax-a-v2", "SME-A", "tax", "invoice_revenue", "2026-01-31", "2026-03-10", "2026-03-11", 2, 180000)
    add("tax-a-feb", "SME-A", "tax", "invoice_revenue", "2026-02-28", "2026-03-05", "2026-03-20", 1, 220000)
    add("power-a", "SME-A", "utility", "kwh", "2026-02-01", "2026-02-02", "2026-02-03", 1, 1800)
    add("cash-a", "SME-A", "bank", "net_inflow", "2026-02-10", "2026-02-10", "2026-02-11", 1, 50000)
    add("cash-a-delete", "SME-A", "bank", "net_inflow", "2026-02-10", "2026-02-18", "2026-02-18", 2, None, True)
    add("tax-b", "SME-B", "tax", "invoice_revenue", "2026-01-31", "2026-02-05", "2026-03-01", 1, 90000)
    add("power-b-old", "SME-B", "utility", "kwh", "2025-11-01", "2025-11-02", "2025-11-02", 1, 700)
    add("power-b", "SME-B", "utility", "kwh", "2026-02-01", "2026-02-03", "2026-03-02", 1, 1300)
    add("cash-b-v2", "SME-B", "bank", "net_inflow", "2026-02-10", "2026-02-12", "2026-02-13", 2, 30000)
    # A delayed delivery of revision 1 must not replace already-known revision 2.
    add("cash-b-v1-delayed", "SME-B", "bank", "net_inflow", "2026-02-10", "2026-02-11", "2026-02-19", 1, 80000)
    decisions = []
    for entity in ("SME-A", "SME-B", "SME-C"):
        for i, day in enumerate(("2026-02-04", "2026-02-15", "2026-02-20", "2026-03-15", "2026-03-25"), 1):
            decisions.append(dict(decision_id=f"{entity}-{i}", entity_id=entity, decision_at=day+"T00:00:00Z"))
    return {"data_kind": "synthetic", "observations": records, "decisions": decisions, "specs": [dict(source="tax", feature="invoice_revenue", max_age_days=90), dict(source="utility", feature="kwh", max_age_days=45), dict(source="bank", feature="net_inflow", max_age_days=60)]}
