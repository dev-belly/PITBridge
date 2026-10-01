# Input and output contract

The JSON root requires `observations`, `decisions` and `specs` arrays. Optional `data_kind` is `synthetic` or `user_supplied` (default). Extra fields, duplicate JSON keys and non-finite JSON constants are rejected. The provenance label is supplied by the caller; it is not externally authenticated.

## Observations

| Field | Type / rule |
| :--- | :--- |
| `record_id` | Unique, nonempty trimmed string. |
| `entity_id`, `source`, `feature` | Nonempty trimmed strings; each source/feature must have a spec. |
| `event_at` | Timezone-aware ISO-8601 event instant. |
| `published_at` | Timezone-aware instant, no earlier than event time. |
| `ingested_at` | Timezone-aware instant, no earlier than event time. |
| `revision` | Integer in `[1, 2^63-1]`; booleans are rejected. |
| `value` | Finite number for an active record; null for a tombstone. |
| `deleted` | Boolean, default false. |

The logical version key `(entity_id, source, feature, event_at, revision)` must also be unique. Value units are governed upstream: the demo uses CNY for invoice revenue and bank net inflow, kWh for utility consumption. Unit conversion and numeric aggregation are outside this implementation.

## Decisions and specs

| Section | Fields |
| :--- | :--- |
| `decisions` | Unique `decision_id`, `entity_id`, timezone-aware `decision_at`. |
| `specs` | Unique pair `source`, `feature`; optional `max_age_days`, null or within `[0,3652500]`. |

At least one decision and one spec are required; observations may be empty. The snapshot has exactly `len(decisions) * len(specs)` rows and a stable decision/source/feature order.

## Example

```json
{
  "data_kind": "synthetic",
  "observations": [{
    "record_id": "tax-001-v1", "entity_id": "SME-001", "source": "tax",
    "feature": "invoice_revenue", "event_at": "2026-01-31T00:00:00Z",
    "published_at": "2026-02-05T00:00:00Z", "ingested_at": "2026-02-06T00:00:00Z",
    "revision": 1, "value": 100000, "deleted": false
  }],
  "decisions": [{"decision_id": "app-001", "entity_id": "SME-001", "decision_at": "2026-02-15T00:00:00Z"}],
  "specs": [{"source": "tax", "feature": "invoice_revenue", "max_age_days": 90}]
}
```

`snapshots.csv` exports the decision identity/time, source, feature, value, status, record ID, revision, event/publication/ingestion/availability times. Missing lineage fields are empty CSV cells. `inputs.json` retains the full normalized history, including revisions not chosen for a decision.
