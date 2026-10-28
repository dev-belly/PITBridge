# Small, runnable examples

Want to edit a timestamp without an account or installation? Start with the
[live invoice lesson](https://dev-belly.github.io/PITBridge/try/). It keeps one
fixed, synthetic two-revision case in your browser, supports exact microsecond
cutoffs and copies shareable scenario links. CI checks 71 scenarios against
both Python engines and exercises the visible desktop/mobile controls. This is
a small teaching mirror; the package remains the full importer and verifier.

To run the actual Python API without setting up a local checkout,
[Open the invoice notebook in Colab](https://colab.research.google.com/github/dev-belly/PITBridge/blob/main/examples/decision_time.ipynb)
or [inspect its source](decision_time.ipynb). It installs dev-belly/PITBridge from
a full source URL pinned to one commit, checks the three fixed decisions, and
then lets you change decision and correction-ingestion times. Only the standard
library is used at runtime; installation needs network access. The separate
editable scenario does not reuse the fixed fixture's expected results.

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
CSV text is parsed once and checked for exact headers, record widths and malformed
quoting before creating a string DataFrame; errors name the file and physical end
line of the CSV record. UTF-8 BOMs, quoted commas and multi-line fields remain
supported; unquoted blank or whitespace-only records are ignored. Text cells preserve
identifiers such as `NA` and exact integer revisions, including values above `2^53`.
Conversion validates the CSV representation before constructing the public dataclasses:

| Column | Accepted CSV cells | Rejected examples |
| :--- | :--- | :--- |
| `revision` | Decimal digits in `[1, 2^63-1]`, with optional leading zeroes; never passed through float | Empty, `1.0`, `1.5`, `1e3`, `true`, out-of-range integers |
| `deleted` | Exactly lowercase `true` or `false` | Empty, `yes`, `1`, `0`; Python truthiness is never used |
| `value` | Finite ASCII decimal/scientific numbers; an empty cell only for a tombstone | `1_000`, `1,000`, surrounding whitespace, non-ASCII digits, `NA`, `NaN`, infinity |
| `max_age_days` | The same numeric syntax within `[0, 3652500]`; an empty cell means no freshness limit | Negative/nonfinite values or malformed numeric text |

These numeric text rules match the [native CSV importer](../docs/CSV_INPUTS.md#parsing-rules).
The optional example converts feature values directly to binary64; the native importer
also retains integer source values in its normalized JSON. Missing features retain their
status and null value; they are never filled with zero. The tests compare full snapshots
with the Python example and reference engine, exercise malformed cells, and check accepted
decimal/scientific values against native CSV intake.

Timezone-aware strings go directly to the public dataclasses for validation
and UTC normalization. A naive timestamp raises `naive timestamps are forbidden;
include Z or an offset`; malformed revisions raise `revision must be a positive
int64 integer`, with the CSV filename and row number. This is a small adapter
example, not a general CSV ingestion service; temporal selection rules and
binary64 feature-value semantics remain those of the [data contract](../docs/DATA_CONTRACT.md).
