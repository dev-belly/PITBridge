"""Strict data contracts, a SQLite temporal join, and a separate replay oracle."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import sqlite3
from typing import Iterable


def utc(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("timestamps must be timezone-aware ISO-8601 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("naive timestamps are forbidden; include Z or an offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonempty, trimmed string")


@dataclass(frozen=True)
class Observation:
    record_id: str
    entity_id: str
    source: str
    feature: str
    event_at: str
    published_at: str
    ingested_at: str
    revision: int
    value: float | None
    deleted: bool = False

    def __post_init__(self):
        for name in ("record_id", "entity_id", "source", "feature"):
            _identifier(getattr(self, name), name)
        for name in ("event_at", "published_at", "ingested_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if type(self.revision) is not int or not 1 <= self.revision <= 2**63-1:
            raise ValueError("revision must be a positive int64 integer")
        if type(self.deleted) is not bool:
            raise ValueError("deleted must be a boolean")
        if self.deleted:
            if self.value is not None:
                raise ValueError("a tombstone must have value=null")
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError("active observations require a finite numeric value")
            try:
                finite = math.isfinite(float(self.value))
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("active observations require a finite binary64 numeric value")
        if self.published_at < self.event_at or self.ingested_at < self.event_at:
            raise ValueError("publication and ingestion cannot precede the observation event")

    @property
    def available_at(self) -> str:
        return max(self.published_at, self.ingested_at)


@dataclass(frozen=True)
class Decision:
    decision_id: str
    entity_id: str
    decision_at: str

    def __post_init__(self):
        for name in ("decision_id", "entity_id"):
            _identifier(getattr(self, name), name)
        object.__setattr__(self, "decision_at", utc(self.decision_at))


@dataclass(frozen=True)
class FeatureSpec:
    source: str
    feature: str
    max_age_days: float | None = None

    def __post_init__(self):
        for name in ("source", "feature"):
            _identifier(getattr(self, name), name)
        # Bound integer inputs before isfinite attempts a binary64 conversion.
        if self.max_age_days is not None and (isinstance(self.max_age_days, bool) or not isinstance(self.max_age_days, (int, float)) or not 0 <= self.max_age_days <= 3652500 or not math.isfinite(self.max_age_days)):
            raise ValueError("max_age_days must be within [0, 3652500], or null")


@dataclass(frozen=True)
class Snapshot:
    decision_id: str
    entity_id: str
    decision_at: str
    source: str
    feature: str
    value: float | None
    status: str
    record_id: str | None = None
    revision: int | None = None
    event_at: str | None = None
    published_at: str | None = None
    ingested_at: str | None = None
    available_at: str | None = None


def validate(observations: Iterable[Observation], decisions: Iterable[Decision], specs: Iterable[FeatureSpec]):
    obs, dec, features = list(observations), list(decisions), list(specs)
    for rows, cls in ((obs, Observation), (dec, Decision), (features, FeatureSpec)):
        if any(not isinstance(row, cls) for row in rows):
            raise ValueError(f"expected {cls.__name__} instances")
    if not dec or not features:
        raise ValueError("at least one decision and one feature spec are required")
    for keys, name in (([r.record_id for r in obs], "record_id"), ([r.decision_id for r in dec], "decision_id"), ([(r.source, r.feature) for r in features], "feature spec"), ([(r.entity_id, r.source, r.feature, r.event_at, r.revision) for r in obs], "logical revision")):
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate {name}")
    allowed = {(r.source, r.feature) for r in features}
    if any((r.source, r.feature) not in allowed for r in obs):
        raise ValueError("every observation must have an explicit feature spec")
    return sorted(obs, key=lambda r: r.record_id), sorted(dec, key=lambda r: r.decision_id), sorted(features, key=lambda r: (r.source, r.feature))


def _instant(value: str) -> int:
    delta = datetime.fromisoformat(value) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _sql_observation(row: Observation) -> tuple:
    fields = asdict(row)
    # Python integers bind as SQLite INTEGER even when the column is REAL.
    # Match the reference engine's binary64 value contract explicitly.
    fields["value"] = None if row.deleted else float(row.value)
    return tuple(fields.values()) + (row.available_at, _instant(row.event_at), _instant(row.available_at))


SQL = """
WITH eligible AS (
  SELECT d.decision_id, o.*,
         ROW_NUMBER() OVER (
           PARTITION BY d.decision_id, o.source, o.feature, o.event_at
           ORDER BY o.revision DESC
         ) AS version_rank
  FROM decisions d JOIN observations o ON d.entity_id = o.entity_id
  WHERE o.event_us <= d.decision_us AND o.available_us <= d.decision_us
), current_versions AS (
  SELECT * FROM eligible WHERE version_rank = 1
), fresh AS (
  SELECT c.*, ROW_NUMBER() OVER (
    PARTITION BY c.decision_id, c.source, c.feature ORDER BY c.event_us DESC
  ) AS event_rank
  FROM current_versions c
  JOIN decisions d USING (decision_id)
  JOIN specs s USING (source, feature)
  WHERE c.deleted = 0 AND
        (s.max_age_us IS NULL OR d.decision_us - c.event_us <= s.max_age_us)
)
SELECT d.decision_id, d.entity_id, d.decision_at, s.source, s.feature,
       f.value,
       CASE WHEN f.record_id IS NOT NULL THEN 'selected'
         WHEN NOT EXISTS (
           SELECT 1 FROM observations o WHERE o.entity_id=d.entity_id
             AND o.source=s.source AND o.feature=s.feature AND o.event_us<=d.decision_us
         ) THEN 'no_history'
         WHEN NOT EXISTS (
           SELECT 1 FROM current_versions c WHERE c.decision_id=d.decision_id
             AND c.source=s.source AND c.feature=s.feature
         ) THEN 'not_available'
         WHEN NOT EXISTS (
           SELECT 1 FROM current_versions c WHERE c.decision_id=d.decision_id
             AND c.source=s.source AND c.feature=s.feature AND c.deleted=0
         ) THEN 'deleted'
         ELSE 'stale' END AS status,
       f.record_id, f.revision, f.event_at, f.published_at, f.ingested_at, f.available_at
FROM decisions d CROSS JOIN specs s
LEFT JOIN fresh f ON f.decision_id=d.decision_id AND f.source=s.source
  AND f.feature=s.feature AND f.event_rank=1
ORDER BY d.decision_id, s.source, s.feature
"""


def build_snapshot(observations, decisions, specs) -> list[Snapshot]:
    """Use both event time and knowledge time, then resolve revisions and TTL."""
    obs, dec, features = validate(observations, decisions, specs)
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
        CREATE TABLE observations(record_id TEXT,entity_id TEXT,source TEXT,feature TEXT,
          event_at TEXT,published_at TEXT,ingested_at TEXT,revision INTEGER,value REAL,
          deleted INTEGER,available_at TEXT,event_us INTEGER,available_us INTEGER);
        CREATE TABLE decisions(decision_id TEXT,entity_id TEXT,decision_at TEXT,decision_us INTEGER);
        CREATE TABLE specs(source TEXT,feature TEXT,max_age_us INTEGER);
        CREATE INDEX temporal_lookup ON observations(entity_id,source,feature,event_us,available_us);
        """)
        db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [_sql_observation(r) for r in obs])
        db.executemany("INSERT INTO decisions VALUES (?,?,?,?)", [(r.decision_id, r.entity_id, r.decision_at, _instant(r.decision_at)) for r in dec])
        db.executemany("INSERT INTO specs VALUES (?,?,?)", [(r.source, r.feature, None if r.max_age_days is None else round(r.max_age_days * 86400 * 1e6)) for r in features])
        return [Snapshot(*row) for row in db.execute(SQL)]


def reference_snapshot(observations, decisions, specs) -> list[Snapshot]:
    """Independent Python enumeration; intentionally does not call the SQL engine."""
    obs, dec, features = validate(observations, decisions, specs)
    results = []
    for d in dec:
        for s in features:
            history = [o for o in obs if (o.entity_id, o.source, o.feature) == (d.entity_id, s.source, s.feature) and o.event_at <= d.decision_at]
            known = [o for o in history if o.available_at <= d.decision_at]
            versions = {}
            for o in known:
                if o.event_at not in versions or o.revision > versions[o.event_at].revision:
                    versions[o.event_at] = o
            active = [o for o in versions.values() if not o.deleted]
            age_limit = None if s.max_age_days is None else round(s.max_age_days * 86400 * 1e6)
            fresh = [o for o in active if age_limit is None or _instant(d.decision_at) - _instant(o.event_at) <= age_limit]
            status = "selected" if fresh else ("no_history" if not history else "not_available" if not known else "deleted" if not active else "stale")
            row = Snapshot(d.decision_id, d.entity_id, d.decision_at, s.source, s.feature, None, status)
            if fresh:
                chosen = max(fresh, key=lambda o: o.event_at)
                row = Snapshot(d.decision_id, d.entity_id, d.decision_at, s.source, s.feature, float(chosen.value), status, chosen.record_id, chosen.revision, chosen.event_at, chosen.published_at, chosen.ingested_at, chosen.available_at)
            results.append(row)
    return results
