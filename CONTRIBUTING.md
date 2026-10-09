# Contributing to PITBridge

Small temporal counterexamples, clearer examples and reproducible bug reports
are welcome. Start with the [late-correction example](examples/README.md),
[data contract](docs/DATA_CONTRACT.md) and [selection method](docs/METHODOLOGY.md).

## Set up and check a change

Fork and clone the repository. Python 3.11+ is required; the runtime has no
third-party dependencies. On Linux or macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python examples/decision_time.py
.venv/bin/python -m pitbridge verify --out demo
.venv/bin/python -m pitbridge verify-rolling --out demo/rolling
```

On Windows, create the environment with `python -m venv .venv` and replace
`.venv/bin/python` with `.\.venv\Scripts\python.exe`. Activation is optional.

If changing reports or exports, regenerate and verify both bundles:

```bash
.venv/bin/python -m pitbridge demo --out outputs
.venv/bin/python -m pitbridge verify --out outputs
.venv/bin/python -m pitbridge rolling-demo --out outputs/rolling
.venv/bin/python -m pitbridge verify-rolling --out outputs/rolling
```

The core CI jobs use the package's default installation without pandas. Optional
CSV-adapter tests skip in that environment. To run those tests when the example
is present, install pandas separately and rerun the suite:

```bash
.venv/bin/python -m pip install "pandas>=2,<4"
.venv/bin/python -m unittest discover -s tests -v
```

Dedicated CI jobs install pandas 2 on Linux and pandas 3 on Linux and Windows.
They run the full suite and the CSV example when present; pandas remains outside
the package's runtime dependencies.

## Where to work

| Area | Implementation | Regression cases |
| :--- | :--- | :--- |
| Scalar availability, revisions and freshness | `src/pitbridge/core.py` | `tests/test_temporal.py` |
| Rolling aggregation and contributor selection | `src/pitbridge/rolling.py` | `tests/test_rolling.py` |
| Reports, CSV exports and semantic verification | `src/pitbridge/bundle.py`, `src/pitbridge/rolling_bundle.py` | `tests/test_bundle.py`, `tests/test_spreadsheet_export.py` |
| Input errors from the CLI | `core.py`, `rolling.py`, `cli.py` | `tests/test_window_contracts.py` |

For a bug, provide the smallest synthetic input, the command, the expected
selection and the actual result. An example with two revisions and one
decision is often enough. Use [the issue templates](https://github.com/dev-belly/PITBridge/issues/new/choose).

For a pull request, explain the behavior before and after the change and list
the checks you ran. Keep unrelated edits separate. Add a regression when a
change fixes temporal selection or validation. Preserve the independent
enumerator; changing both engines to agree is not evidence that a new rule is
correct. Explain any intentional contract change before changing saved data.

## Useful small contributions

- A synthetic counterexample for a rule that is not yet covered.
- A runnable optional pandas/CSV adapter example, keeping pandas out of the
  package's runtime dependencies and preserving timezone-aware values.
- A clearer worked example or a correction to the English/Chinese docs.

The project is a reference implementation, not a full feature-store service.
Use synthetic or appropriately licensed public records in examples and issues;
do not upload private borrower or bank records. Proposed benchmarks must
include reproducible commands, data size and hardware details. Contributions
are covered by the repository's [MIT license](LICENSE).
