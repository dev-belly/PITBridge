# Small, runnable examples

Install the repository in a Python 3.11+ virtual environment using the
[quick start](../README.md#run-in-one-minute), then run:

```bash
.venv/bin/python examples/decision_time.py
```

On Windows:

```powershell
.\.venv\Scripts\python.exe examples/decision_time.py
```

## A correction that arrives later

The example uses two synthetic versions of one invoice-revenue observation.
Both refer to January 31. Version 1 becomes available on February 6; version 2
becomes available on April 3. All decisions use a 90-day freshness limit.

| Decision (UTC) | Value (synthetic CNY) | Status | Selected record |
| :--- | ---: | :--- | :--- |
| February 1 | missing | `not_available` | none |
| February 15 | 100,000 | `selected` | `invoice-v1` |
| April 15 | 135,000 | `selected` | `invoice-v2` |

The script prints the full snapshot rows, including the selected revision,
publication, ingestion and availability times. It also checks SQL results
against the independent Python enumerator. Joining only on the January event
date could put the April correction into the February decision.

To reuse the API, replace the `Observation`, `Decision` and `FeatureSpec`
lists in [decision_time.py](decision_time.py). To start from JSON instead, use
the [`build` command and input contract](../docs/DATA_CONTRACT.md).
Rolling source membership has a separate [worked example](../docs/ROLLING.md).

## Optional pandas/CSV input

Install pandas separately in the same environment, then run:

```bash
.venv/bin/python -m pip install pandas
.venv/bin/python examples/pandas_csv.py
```

On Windows use `.\.venv\Scripts\python.exe` for both commands. Pandas is not
a PITBridge runtime dependency. The three synthetic files in [csv/](csv/)
contain the same observations, decisions and freshness limit as
`decision_time.py`. Expected output is the same three full JSON snapshot rows
shown above: `not_available`, `invoice-v1` (100,000), `invoice-v2` (135,000).
The script checks these selections and compares every field with the independent
`reference_snapshot` result. Run optional adapter tests after installing pandas:

```bash
.venv/bin/python -m unittest discover -s tests -p test_pandas_csv.py -v
```

To use your own tables, call `load_inputs(directory)` with `observations.csv`,
`decisions.csv` and `specs.csv`, keeping the exact headers in the fixtures.
Cells are read as strings with `keep_default_na=False`, preserving identifiers
such as `NA` and exact integer revisions, including values above `2^53`.
Revisions require decimal digits in `[1, 2^63-1]`; fractional, scientific and
boolean representations are rejected. `deleted` requires literal `true` or
`false`. An empty `value` cell means null and is valid only for a tombstone;
an empty `max_age_days` means no freshness limit. Missing features retain their
status and null value; they are never filled with zero.

Timezone-aware strings go directly to the public dataclasses for validation
and UTC normalization. A naive timestamp raises `naive timestamps are forbidden;
include Z or an offset`; malformed revisions raise `revision must be a positive
int64 integer`, with the CSV filename and row number. This is a small adapter
example, not a general CSV ingestion service; temporal selection rules and
binary64 feature-value semantics remain those of the [data contract](../docs/DATA_CONTRACT.md).
