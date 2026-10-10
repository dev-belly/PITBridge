<img src="assets/hero.svg" width="100%" alt="PITBridge · data, method and replayable evidence" />

# PITBridge

**Financial features as they were known when a decision was made.**

[![CI](https://github.com/dev-belly/PITBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/dev-belly/PITBridge/actions/workflows/ci.yml)
[Try one invoice](examples/README.md#a-correction-that-arrives-later) · [Bring CSV tables](examples/README.md#optional-pandascsv-input) · [Open the online report](https://dev-belly.github.io/PITBridge/) · [中文说明](README.zh-CN.md)

[Methodology](docs/METHODOLOGY.md) · [Data contract](docs/DATA_CONTRACT.md) · [Interview notes](docs/INTERVIEW.md)

An invoice dated January can be published in February, arrive in March, and be corrected later. Joining on January's date alone can put future knowledge into an earlier credit decision. PITBridge resolves **event time, publication time, ingestion time and observation revisions** before exporting a feature snapshot.

![Decision-time leakage counterexample](docs/evidence.png)

## Run in one minute

Python 3.11+ and Git are required. There are **no third-party runtime
dependencies**. The commands use a virtual environment without requiring
activation.

**Linux / macOS**

```bash
git clone https://github.com/dev-belly/PITBridge.git
cd PITBridge
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pitbridge demo --out outputs
.venv/bin/python -m pitbridge verify --out outputs
.venv/bin/python examples/decision_time.py
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/dev-belly/PITBridge.git
cd PITBridge
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pitbridge demo --out outputs
.\.venv\Scripts\python.exe -m pitbridge verify --out outputs
.\.venv\Scripts\python.exe examples/decision_time.py
```

Open `outputs/report.html` in a browser. The report is self-contained, works
offline and includes a filter for changed selections. Later command snippets
use `.venv/bin/python`; on Windows substitute `.\.venv\Scripts\python.exe`.
Saved report files also keep LF endings when Git uses `core.autocrlf=true`, so
the committed `demo` and `demo/rolling` bundles retain their hashes on Windows.

```bash
# Bring your own observations, decisions and feature specs:
.venv/bin/python -m pitbridge build --inputs demo/inputs.json --out outputs
```

## Use the Python API

The [runnable example](examples/decision_time.py) calls `build_snapshot` with
your observations, decisions and feature specs and checks the result against
`reference_snapshot`. It contains two versions of a synthetic invoice: the
original is available on February 6, while its correction arrives on April 3.

| Decision (UTC) | Synthetic invoice revenue (CNY) | Selected record |
| :--- | ---: | :--- |
| February 1 | missing (`not_available`) | none |
| February 15 | 100,000 | `invoice-v1` |
| April 15 | 135,000 | `invoice-v2` |

The January event date is the same for both versions. The April correction
cannot become a February feature. [See the input lists and full output](examples/README.md)
to adapt the example to your own data.

Starting from tables? The [optional pandas/CSV example](examples/README.md#optional-pandascsv-input)
reads three small CSVs and produces the same three selections. Install pandas
separately; the core package remains dependency-free. Tried either path?
[Share what worked or blocked you](https://github.com/dev-belly/PITBridge/issues/new?template=trial_feedback.md).

## What the saved example proves

The deliberately small synthetic fixture is hand-auditable: **11 observations, 15 decisions, 45 feature lookups** across tax, bank and utility sources.

| Saved result | Count | Interpretation |
| :--- | ---: | :--- |
| Unsafe selections using future knowledge | 11 | The event-only baseline selected a record unavailable at decision time. |
| Selections changed by the full contract | 16 | Includes freshness and tombstone effects as well as future knowledge. |
| Selected / missing feature rows | 16 / 29 | Missingness is preserved with a reason, never silently replaced by zero. |

Inspect [the comparison](demo/comparison.csv), [record-level lineage](demo/snapshots.csv), [normalized inputs](demo/inputs.json), and [summary](demo/summary.json). These counts demonstrate the fixture; they are not a population leakage rate.

## Selection contract

1. Require `event_at <= decision_at` and `max(published_at, ingested_at) <= decision_at`.
2. For each entity/source/feature/event, select the **highest known revision**, even if a lower revision arrives later.
3. Apply known tombstones to that event. Do not resurrect its earlier revision.
4. Select the latest remaining event within the feature's inclusive freshness window.
5. Preserve a row for every decision/spec pair, including `no_history`, `not_available`, `deleted` and `stale`.

The production path is a SQLite window-function join. A separate Python enumerator checks its results, including randomized histories and append-future invariance. [Read the implementation](src/pitbridge/core.py).

## Evidence you can replay

| Artifact | Purpose |
| :--- | :--- |
| `inputs.json` | Canonical, normalized source records, decisions and feature contracts. |
| `snapshots.csv` | Values, missingness, selected record IDs, revisions and timestamps. |
| `comparison.csv` | Explicitly unsafe event-only baseline; never used as training features. |
| `summary.json`, `report.html` | Derived counts and an offline inspection report. |
| `manifest.json` | SHA-256 hashes of all five artifacts. |

Verification checks hashes **and** reruns both algorithms, rejecting a fabricated summary even if its hash was updated. Hashes are not signatures and cannot establish that an external source is truthful.

## Availability-aware rolling features

Rolling sums, observation means and counts resolve availability, revisions
and tombstones before aggregating an inclusive event-time window. Every result
retains all contributing records; a separate Python temporal enumerator checks
membership and values.

```bash
.venv/bin/python -m pitbridge rolling-demo --out outputs/rolling
.venv/bin/python -m pitbridge verify-rolling --out outputs/rolling
.venv/bin/python -m pitbridge aggregate --inputs demo/rolling/inputs.json --out outputs/custom
```

[Online rolling case](https://dev-belly.github.io/PITBridge/rolling/) ·
[Contract and worked example](docs/ROLLING.md) ·
[Feature rows](demo/rolling/features.csv) · [Membership](demo/rolling/members.csv)

## Verified downstream integration

PITBridge is also exercised by a real downstream adapter in
[CreditVintage](https://github.com/dev-belly/CreditVintage). The published
[PITBridge × CreditVintage explorer](https://dev-belly.github.io/CreditVintage/lineage/)
traces each held-out model feature back to the selected PITBridge source record,
revision, publication time, ingestion time and decision cutoff. The downloadable
[evidence bundle](https://dev-belly.github.io/CreditVintage/lineage/evidence.zip)
contains the source events, exported model inputs, predictions and manifests.

The default synthetic integration contains **480 applications, 1,440 selected
features and 120 held-out predictions**. Its source fixture includes **192
observations that were not yet available at their decision time**, so the
adapter has to preserve PITBridge's availability contract instead of performing
a plain event-date join. CreditVintage currently pins PITBridge commit
`ed19dc698534f45a2b646fb4976ff6b01966b0cc`; its CI verifies the PITBridge
bundle with both the SQL engine and independent Python oracle before rebuilding
the downstream model evidence.

This is a downstream integration, not a claim that the two repositories form a
production banking platform. The full adapter contract, units, UTC convention
and replay boundaries live in
[CreditVintage's lineage documentation](https://github.com/dev-belly/CreditVintage/blob/main/docs/LINEAGE.md).

## Scope

This is a reference implementation for scalar financial observations and explicit rolling aggregates. It does not provide streaming ingestion, access control or label generation. Version numbers and trustworthy availability timestamps must come from the upstream source contract. SQLite is intentionally inspectable; distributed-scale performance has not been benchmarked. Rolling means are observation means, and counts do not establish complete business activity.

PITBridge remains independently usable, while CreditVintage provides a
published, CI-verified downstream source-to-prediction integration. MIT license.

## Feedback and contributions

Tried the invoice or CSV example?
[Share trial feedback](https://github.com/dev-belly/PITBridge/issues/new?template=trial_feedback.md)
with your command, environment and expected selection.

Found an unexpected selection or an installation problem?
[Open an issue with a small reproduction](https://github.com/dev-belly/PITBridge/issues/new/choose).
The [contribution guide](CONTRIBUTING.md) maps the code and regression cases and
explains how to replay evidence. Small counterexamples, optional adapter
examples and documentation improvements are welcome.

If this workflow is useful to you, a star is a simple way to keep the repository handy.
