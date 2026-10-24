# Import CSV tables without pandas

PITBridge v0.2.0 reads UTF-8 CSV tables using Python's standard library.
Use the README's [checked release installation](../README.md#install-the-checked-release)
or its source instructions. The v0.1.0 tag does not have `--csv-dir`.

## Scalar snapshots

Put these three files in one directory. Every listed column is required;
column order is free. Duplicate, missing and extra header names fail.

| File | Exact columns |
| --- | --- |
| `observations.csv` | `record_id,entity_id,source,feature,event_at,published_at,ingested_at,revision,value,deleted` |
| `decisions.csv` | `decision_id,entity_id,decision_at` |
| `specs.csv` | `source,feature,max_age_days` |

The repository's [invoice tables](../examples/csv) are a runnable example:

```bash
python -m pitbridge build --csv-dir examples/csv --out outputs/csv
python -m pitbridge verify --out outputs/csv
```

For Windows, use `.\.venv\Scripts\python.exe -m pitbridge` in the README's
environment. The same tables yield an unavailable invoice on February 1, the
100,000 original on February 15 and the 135,000 correction on April 15.
The importer labels tables `user_supplied`, including copies of these synthetic
fixtures: it does not infer or authenticate a source's provenance.

## Rolling features

Use the same observation and decision files, replacing `specs.csv` with
`rolling_specs.csv`:

```csv
name,source,feature,window_days,aggregation
invoice_sum_90d,tax,invoice_revenue,90,sum
invoice_mean_90d,tax,invoice_revenue,90,mean
invoice_observations_90d,tax,invoice_revenue,90,count
```

```bash
python -m pitbridge aggregate --csv-dir my-tables --out outputs/rolling-csv
python -m pitbridge verify-rolling --out outputs/rolling-csv
```

Read [the rolling contract](ROLLING.md) before interpreting a sum or count.
Observation counts do not establish complete business activity. An unrelated
`specs.csv` or `rolling_specs.csv` in the directory is ignored: each command
reads only its three named files.

## Parsing rules

| Input | Meaning |
| --- | --- |
| Identifiers such as `0001`, `NA`, `NULL` | Literal strings, preserved without type inference or trimming |
| Empty `max_age_days` | No freshness limit |
| Empty observation `value` | Null; valid only when `deleted=true` |
| `deleted` | Exactly `true` or `false`, lowercase |
| `revision` | Decimal digits for an integer in `[1, 2^63-1]`; never parsed through float |
| Numeric cells | Decimal or scientific notation; no surrounding whitespace, underscores, thousands separators, `NaN` or infinity |
| All timestamps | Timezone-aware ISO-8601; normalized to UTC; naive dates/times fail |
| En…419 tokens truncated…ndle.write_rolling_bundle(data, output).
```

Both report formats retain the existing normalized JSON inputs and independent
SQL/Python semantic replay. CSV exports neutralize spreadsheet formulas in
identifiers; normalized JSON retains the original identifiers. Parsing does
not establish completeness, authenticity or trustworthy availability times.
