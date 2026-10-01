# Methodology

## Two clocks and a source revision

An observation has event time `e`, publication time `p`, ingestion time `i`, and availability `a = max(p, i)`. This assumes both public release and ingestion are necessary for the decision system to use the record. It also supports pre-ingested embargoed records: ingestion alone does not make them eligible.

For decision time `t`, the eligible set requires `e <= t` and `a <= t`. All instants are normalized to UTC at microsecond precision. Equality is inclusive. The contract rejects naive timestamps and publication/ingestion preceding the represented observation event.

The logical observation key is `(entity_id, source, feature, event_at)`. Within the eligible set, choose the largest positive source `revision`. A higher version remains authoritative even if a lower version was delivered later. Duplicate logical key/revision pairs are rejected rather than resolved by incidental row order.

A tombstone is a revision with `deleted=true` and `value=null`. Version resolution happens **before** removing tombstones, so a revoked observation cannot fall back to its older revision. It does not revoke the entire feature series: an earlier, separate active observation may still be selected.

For an optional freshness limit `w`, use `0 <= t-e <= w` after resolving versions. The latest active event within the window is selected. Days mean exactly 86,400 seconds, rounded to microseconds; there is no business-calendar adjustment.

## Missingness precedence

| Status | Meaning |
| :--- | :--- |
| `no_history` | No observation for this entity/source/feature has event time at or before the decision. |
| `not_available` | Historical events exist, but none were available by the decision. |
| `deleted` | Known observations exist; their highest known versions are all tombstones. |
| `stale` | Known active versions exist, but none pass the freshness window. |
| `selected` | A valid record and its lineage were selected. |

If known tombstones coexist with old active observations, and those active observations are stale, the status is `stale`. Missingness is not imputed here.

## An auditable counterexample

`tax-a-v1` represents 100,000 CNY of January invoice revenue and is available February 6. Revision 2 changes the value to 180,000 CNY but is not available until March 11. The February 15 decision must keep version 1. The fixture separately tests March's late ingestion, a revoked bank cash observation, UTC offset equivalence, and delayed delivery of an older revision.

The unsafe baseline only constrains event time, choosing the newest event/highest revision. It intentionally ignores availability, deletion and freshness. `future_knowledge_rows` counts unavailable baseline records; `different_selections` also counts non-leakage contract differences. The fixture is constructed to expose these failures and is not a representative sample of bank data.

## Verification boundaries

SQLite resolves eligible versions and event ranks using SQL window functions. The independent Python oracle enumerates histories and versions without calling SQL. Tests compare both on randomized data, shuffled input order and appended future revisions.

`verify` first checks artifact hashes, then derives all outputs again from the normalized input snapshot and compares them byte-for-byte. A changed metric plus an updated hash fails replay. An attacker who rewrites the source inputs and regenerates the whole bundle can produce a consistent new bundle: this workflow is not authentication or immutable source storage.

## Sources and design context

- [Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins): historical feature retrieval and freshness windows. PITBridge explicitly uses the maximum of publication and ingestion time in addition to event time.
- [SQLite window functions](https://www.sqlite.org/windowfunctions.html): ranking for observation revisions and event selection.

No Feast code was copied and PITBridge is not a Feast adapter. There are no performance or production-readiness claims.
