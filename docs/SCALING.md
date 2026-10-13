# Scalar join scale evidence

The [saved measurements](benchmarks/scaling.json) use 100,000 and 1,000,000
observations, each run three times in a fresh Python process. Each entity has
the same 20-record history and four decisions; increasing size adds entities.

| Observations | Decisions / lookups | Median snapshot time | Whole-process peak RSS |
| --- | --- | --- | --- |
| 100,000 | 20,000 | 2.875 s | 135.1 MiB |
| 1,000,000 | 200,000 | 31.130 s | 1.064 GiB |

These are local measurements on the recorded Linux / Python 3.12 / SQLite
environment. Snapshot time includes validation, SQLite loading, the temporal
query and constructing outputs. Input generation is timed separately. Peak RSS
covers the whole process, including input generation, SQLite and the small
oracle; it is not incremental database memory. CI imposes no timing threshold.

```bash
pitbridge benchmark --rows 100000 1000000 --repeats 3 --out outputs/scaling
```

Each entity has 18 original events, a correction published after the first
decision, and a later tombstone. Four decision times must select the original,
select the correction, fall back to the prior event after deletion, and finally
report stale under an 80-day TTL. Every run checks all status counts and compares
the first eight entities' full outputs with the independent enumeration oracle.
All three trials at each size produce the same complete snapshot digest.

The saved JSON records raw timings, median/range, memory scope, environment,
source-file hashes and output digest. The workload covers synthetic scalar
joins; rolling aggregation, hot-entity histories, streaming ingestion, online
feature serving and production availability need separate evaluation.
