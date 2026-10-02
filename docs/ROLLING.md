# Decision-time rolling financial features

[Online case](https://dev-belly.github.io/PITBridge/rolling/) ·
[Feature rows](../demo/rolling/features.csv) · [Contributing records](../demo/rolling/members.csv)

Rolling features answer: what was the sum, mean or observation count in a
recent event-time window, using only information available at the decision?

## Run and replay

```bash
pitbridge rolling-demo --out outputs/rolling
pitbridge verify-rolling --out outputs/rolling
pitbridge aggregate --inputs demo/rolling/inputs.json --out outputs/custom
```

Open `outputs/rolling/report.html`. Select a decision to inspect values and
every contributing record. Original scalar-snapshot commands remain supported.

## Contract and selection order

Inputs contain `observations`, `decisions`, `rolling_specs` and optional
`data_kind`. Observations and decisions retain their original strict contracts.

```json
{"name":"net_inflow_30d","source":"bank","feature":"net_inflow",
 "window_days":30,"aggregation":"sum"}
```

Output names are unique. Aggregation is `sum`, `mean` or `count`. Positive
window durations are rounded to microseconds. Both boundaries are inclusive:
`decision_at - window <= event_at <= decision_at`.

1. Require event time and `max(published_at, ingested_at)` not later than the decision.
2. For each entity/source/feature/event-time key, retain the highest known revision.
3. Remove known tombstones after resolving revisions.
4. Aggregate active observations in the window, exporting their identities,
   revisions and availability timestamps in `members.csv`.

The SQLite temporal join uses custom compensated sum and mean aggregates. A separate
Python enumerator independently selects contributors. These paths share
compensated binary64 arithmetic, not their temporal selection logic.
This reduces cancellation error but is not exact decimal accounting;
non-finite outputs are rejected. If `math.fsum` overflows while accumulating,
an exact rational sum of the already-converted binary64 inputs checks the final
sum or mean. Thus two `1e308` observations have a valid mean of `1e308`,
although their sum is rejected. This fallback also preserves finite sums after
large cancellation. Ordinary floating-point summation can
lose small terms when large values cancel; see the
[SQLite aggregate documentation](https://www.sqlite.org/lang_aggfunc.html).

## Hand-auditable synthetic example

Ten source revisions, four decisions and three specifications produce
12 feature rows and 28 contributing-record links.

| Decision, 18:00 UTC | 30-day sum | Active observations | 7-day observation mean |
| --- | ---: | ---: | ---: |
| SME-A, February 10 | 1,500 | 4 | 150 |
| SME-A, February 11 | 4,300 | 3 | 150 |
| SME-A, February 12 | 6,300 | 4 | 1,250 |
| SME-B, February 12 | missing | 0 | missing |

February 10 includes a 200-unit record exactly on the lower boundary,
excluding a record one second earlier, an unavailable 2,000-unit record
and a canceled 800-unit event. A 1,000-unit record is corrected to 4,000
only on February 11, when the boundary record has already left the window.
The late 2,000-unit record first contributes on February 12.

`no_history` means no events in this window; `not_available` means events
were not known; `deleted` means all known versions were canceled. These
keep `value=null` and `observation_count=0`. A selected sum of zero keeps
its real contributing records. Missing counts do not establish zero activity.

## Evidence and boundaries

The five-artifact bundle has a separate `pitbridge/rolling/1` manifest.
Verification checks hashes, then reruns SQL and Python for both values and
membership. Rehashed fabricated outputs are rejected. Hashes cannot
authenticate upstream records.

The logical observation key is entity/source/feature/event timestamp.
Distinct transactions with the same key cannot be modeled independently.
Sources must supply comparable, nonoverlapping amounts for a meaningful sum.
Mean is an unweighted observation mean, not a complete daily/time-weighted
mean; count measures observations, not borrowers, invoices or days.
Complete source coverage, unit/currency conversion, streaming ingestion,
distributed throughput and CreditVintage integration remain outside scope.

## 面试追问

**为什么不能先加总最近 30 天，再检查发布时间？** 未来修订已经改变了结果。必须先决定当时能看到哪个版本，再对合法成员聚合。

**为什么不能直接从原始表删掉撤销行？** 旧版本会重新被选中；这里先取最高已知修订，再处理撤销。

**没有记录为什么不是 0？** 没有历史、没收到数据和真实零经营额不同，必须保留缺失原因。

**怎么核验一笔加总？** 每个输出特征都有一组源修订成员，SQL 与 Python 从规范化输入分别重放，对数值和成员一起比较。
