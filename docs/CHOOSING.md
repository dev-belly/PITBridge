# Choosing a tool and reusing PITBridge

Choose by the time contract and deployment task. These are documented use cases;
no cross-tool performance or correctness benchmark is implied.

| Your task | A useful starting point | Check before using it |
| :--- | :--- | :--- |
| Inspect local financial observations with publication/ingestion times, revisions, missingness and source-record lineage | **PITBridge** and the [invoice notebook](../examples/decision_time.ipynb) | Upstream timestamps/version IDs must be trustworthy; use the [input contract](DATA_CONTRACT.md). For capacity, consult the [measured workloads](SCALING.md). |
| Keep historical selection in an existing database and own its business rules | **SQL** with explicit filters and ranking; see [SQLite window functions](https://www.sqlite.org/windowfunctions.html) and [this implementation](../src/pitbridge/core.py) | Define availability, revision ordering, deletion, freshness and ties, then test those rules against small expected cases. |
| Match sorted tables by the nearest prior value of a chosen key | **pandas `merge_asof`**, with `direction="backward"`; see the [official API](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html) | Sort by the merge key; choose grouping, tolerance and exact-match policy. Define how your publication, ingestion and revision rules map to the tables before joining. |
| Manage feature definitions, historical training retrieval and online serving across infrastructure | **Feast**; start with its [local quickstart](https://docs.feast.dev/getting-started/quickstart) | Choose the source/store and its time semantics. Its [PIT guide](https://docs.feast.dev/getting-started/concepts/point-in-time-joins) also documents `filter_by_created_timestamp=True`; check the behavior for your version/store and the meaning of the created timestamp. |

PITBridge's scope is scalar financial observations and explicit rolling aggregates.
Streaming ingestion, access control and label generation belong to the surrounding
system. The table makes no claim about features absent from other tools.

## Reuse the existing public API

These signatures describe pre-1.0 source `6d6524b`, checked on 2026-10-19.
Pin the tag or source commit used by your example and retain its inputs and report
bundle. The documented input rules and verifiers describe that snapshot; they do
not establish cross-version API or bundle compatibility. Before adopting another
snapshot, review its contract changes and rerun the existing invoice and replay
checks. Public imports are listed in [the package](../src/pitbridge/__init__.py)
and implemented in [core.py](../src/pitbridge/core.py).

```text
Observation(record_id: str, entity_id: str, source: str, feature: str,
            event_at: str, published_at: str, ingested_at: str,
            revision: int, value: float | None, deleted: bool = False)
Decision(decision_id: str, entity_id: str, decision_at: str)
FeatureSpec(source: str, feature: str, max_age_days: float | None = None)
build_snapshot(observations, decisions, specs) -> list[Snapshot]
reference_snapshot(observations, decisions, specs) -> list[Snapshot]
```

Pass iterables of `Observation`, `Decision` and `FeatureSpec` respectively.
A generator is exhausted after one call; use lists when comparing SQL selection
with the independent Python reference. The [runnable invoice example](../examples/decision_time.py)
constructs those lists and checks both the full rows and three expected selections.

The return is a list of `Snapshot` dataclasses, one per decision/spec pair,
ordered by `decision_id`, `source`, `feature`. Each row contains the decision,
value/status and selected source record's ID, revision and timestamps.
Missing selections keep `value=None` and a reason: `no_history`, `not_available`,
`deleted` or `stale`; they are not filled with zero. Use `dataclasses.asdict(row)`
for a dictionary. Feature values follow the finite binary64 contract; integer
conversion can round above `2^53`.

Invalid timestamps, revisions, freshness limits, duplicate identities or missing
specs raise `ValueError` through the constructors/validation. Wrong Python call
shapes can still raise `TypeError`. Python calls raise exceptions; the CLI reports
handled contract errors on stderr with exit code 2. Full field/error rules remain
in the [input contract](DATA_CONTRACT.md); [the method](METHODOLOGY.md) explains
selection, and [rolling features](ROLLING.md) have their own contract and entry points.

## Continue with your input

Use the installed [CSV importer](CSV_INPUTS.md) for three table inputs without
pandas, the [optional pandas example](../examples/README.md#optional-pandascsv-input)
for DataFrame exploration, or the `build --inputs` JSON route. For a mismatch,
keep a minimal synthetic input, the expected
record and the actual status, then [share trial feedback](https://github.com/dev-belly/PITBridge/issues/new?template=trial_feedback.md).

External references above were checked on 2026-10-19. They describe those tools'
contracts, not an implemented adapter or compatibility promise from PITBridge.
