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
