# Input and output contract

The JSON root requires `observations`, `decisions` and `specs` arrays. Optional `data_kind` is `synthetic` or `user_supplied` (default). Extra fields, duplicate JSON keys and non-finite JSON constants are rejected. The provenance label is supplied by the caller; it is not externally authenticated.

For table inputs, `build --csv-dir DIRECTORY` and `aggregate --csv-dir DIRECTORY`
apply the same temporal and identity contracts without pandas. The
[CSV intake contract](CSV_INPUTS.md) defines exact headers, null/boolean parsing
and file/physical-line errors. JSON and CSV are mutually exclusive input routes.

## Observations

All observation and decision timestamps support at most six fractional-second
digits, attached to an explicit seconds field (`HH:MM:SS` or `HHMMSS`). Fractions
on shortened hour/minute forms are rejected. Excess digits are rejected, including trailing zeros; they are never
truncated or rounded into an earlier decision. UTC offsets must use whole
seconds (ordinary `Z`, `+08:00` and `-05:00` offsets remain supported).
Fractional-second offsets are rejected because the underlying datetime parser
can discard their fraction when the whole-second offset is zero. JSON, native
CSV and the optional pandas example use this same validation before selection
or report creation. A source with finer timestamps must choose and document an
upstream conversion policy; this engine does not infer one.

These stricter checks are on `main` after the v0.2.0 release. Existing release
assets are unchanged; use the source installation for this validation. Bundles
with timestamps already in the supported form retain their original bytes.

| Field | Type / rule |
| :--- | :--- |
| `record_id` | Unique, nonempty trimmed string. |
| `entity_id`, `source`, `feature` | Nonempty trimmed strings; each source/feature must have a spec. |
| `event_at` | Timezone-aware ISO-8601 event instant. |
| `published_at` | Timezone-aware instant, no earlier than event time. |
| `ingested_at` | Timezone-aware instant, no earlier than event time. |
| `revision` | Integer in `[1, 2^63-1]`; booleans are rejected. |
| `value` | Number representable as finite binary64 for an active record; null for a tombstone. Integers are converted to binary64 for computation, including values outside SQLite's signed-int64 range. |
| `deleted` | Boolean, default false. |

The logical version key `(entity_id, source, feature, event_at, revision)` must also be unique. Value units are governed upstream: the demo uses CNY for invoice revenue and bank net inflow, kWh for utility consumption. Binary64 conversion can round integers above `2^53`; original input values remain in `inputs.json`. This is a feature engine, not an exact monetary ledger. Unit conversion is outside scope; [rolling aggregates](ROLLING.md) have a separate contract.

## Decisions and specs

| Section | Fields |
| :--- | :--- |
| `decisions` | Unique `decision_id`, `entity_id`, timezone-aware `decision_at`. |
| `specs` | Unique pair `source`, `feature`; optional `max_age_days`, null or within `[0,3652500]`. |

At least one decision and one spec are required; observations may be empty. The snapshot has exactly `len(decisions) * len(specs)` rows and a stable decision/source/feature order.

Day limits must be numbers, with booleans rejected. Out-of-range limits, including arbitrarily large positive or negative integers, raise a validation error. The `build` and `aggregate` commands return status 2 with the invalid parameter named, without publishing an evidence manifest.

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

## Spreadsheet-compatible exports

Formula-shaped text fields and headers beginning with ASCII or full-width
`=`, `+`, `-`, `@` operators, including operators behind ASCII whitespace, and
leading control/BOM prefixes receive a visible `text: ` marker in CSV exports.
Text already starting with that marker receives one more marker, avoiding
identity collisions. Numeric losses and negative numeric features keep their
values. Original identifiers remain in `inputs.json`, the authoritative replay
source. The visible marker avoids relying on apostrophes that spreadsheet
editors can remove on save/reopen; see [OWASP guidance](https://owasp.org/www-community/attacks/CSV_Injection).

Embedded CR, LF and CRLF are quoted as cell content; CSV records retain LF
endings. Original labels remain in JSON. HTML selectors use explicit ASCII JSON
identity keys, so repeated whitespace, CR/LF, NUL or Unicode names cannot become
the same option through browser preprocessing. Visible labels remain readable.
Regenerate earlier rolling reports and scalar reports with marked identifiers
from their saved JSON inputs before using the updated verifier. Saved report HTML and its hash were refreshed; financial
values and source inputs are unchanged.
