"""Availability-aware rolling aggregates with every contributing revision retained."""

from dataclasses import asdict, dataclass
from fractions import Fraction
import math
import sqlite3

from .core import Decision, FeatureSpec, Observation, _identifier, _instant, _sql_observation, validate


@dataclass(frozen=True)
class RollingSpec:
    name: str
    source: str
    feature: str
    window_days: float
    aggregation: str = "sum"

    def __post_init__(self):
        for field in ("name", "source", "feature"):
            _identifier(getattr(self, field), field)
        if (isinstance(self.window_days, bool) or not isinstance(self.window_days, (int, float))
                or not math.isfinite(self.window_days) or not 0 < self.window_days <= 3652500
                or self.window_us < 1):
            raise ValueError("window_days must be positive and resolve to at least one microsecond")
        if self.aggregation not in ("sum", "mean", "count"):
            raise ValueError("aggregation must be sum, mean or count")

    @property
    def window_us(self):
        return round(self.window_days * 86400 * 1_000_000)


@dataclass(frozen=True)
class RollingFeature:
    decision_id: str
    entity_id: str
    decision_at: str
    name: str
    source: str
    feature: str
    window_days: float
    aggregation: str
    value: float | int | None
    observation_count: int
    status: str


@dataclass(frozen=True)
class RollingMember:
    decision_id: str
    name: str
    record_id: str
    revision: int
    event_at: str
    published_at: str
    ingested_at: str
    available_at: str
    value: float


def validate_rolling(observations, decisions, specs):
    specs = list(specs)
    if not specs or any(not isinstance(spec, RollingSpec) for spec in specs):
        raise ValueError("at least one RollingSpec is required")
    if len({spec.name for spec in specs}) != len(specs):
        raise ValueError("rolling output names must be unique")
    sources = sorted({(spec.source, spec.feature) for spec in specs})
    observations, decisions, _ = validate(
        observations, decisions, [FeatureSpec(*source) for source in sources]
    )
    return observations, decisions, sorted(specs, key=lambda spec: spec.name)


def _aggregate(values, *, mean=False):
    try:
        value = math.fsum(values)
    except OverflowError:
        # The partial sum can overflow even when the final sum or mean fits.
        # Exact ratios of the binary64 inputs are a rare, bounded fallback;
        # this does not turn upstream decimal amounts into exact accounting.
        exact = sum((Fraction.from_float(value) for value in values), Fraction())
        if mean:
            exact /= len(values)
        try:
            return float(exact)
        except OverflowError as error:
            raise ValueError("rolling aggregate is outside the finite binary64 range") from error
    return value / len(values) if mean else value


class _PreciseSum:
    """Compensated binary64 summation; this is not exact decimal accounting."""
    mean = False
    def __init__(self):
        self.values = []

    def step(self, value):
        if value is not None:
            self.values.append(float(value))

    def finalize(self):
        try:
            return _aggregate(self.values, mean=self.mean) if self.values else None
        except ValueError:
            return math.inf  # Rejected by the finite-output check below.


class _PreciseMean(_PreciseSum):
    mean = True


CTE = """
WITH eligible AS (
 SELECT d.decision_id, o.*,
   ROW_NUMBER() OVER (
     PARTITION BY d.decision_id, o.source, o.feature, o.event_us
     ORDER BY o.revision DESC
   ) AS version_rank
 FROM decisions d JOIN observations o ON d.entity_id = o.entity_id
 WHERE o.event_us <= d.decision_us AND o.available_us <= d.decision_us
), active AS (
 SELECT e.*, s.name
 FROM eligible e JOIN decisions d USING (decision_id)
 JOIN specs s USING (source, feature)
 WHERE e.version_rank = 1 AND e.deleted = 0
   AND d.decision_us - e.event_us <= s.window_us
)
"""


def build_rolling(observations, decisions, specs):
    """Resolve known revisions before aggregating the inclusive event-time window."""
    observations, decisions, specs = validate_rolling(observations, decisions, specs)
    with sqlite3.connect(":memory:") as db:
        db.create_aggregate("precise_sum", 1, _PreciseSum)
        db.create_aggregate("precise_mean", 1, _PreciseMean)
        db.executescript("""
        CREATE TABLE observations(record_id TEXT,entity_id TEXT,source TEXT,feature TEXT,
          event_at TEXT,published_at TEXT,ingested_at TEXT,revision INTEGER,value REAL,
          deleted INTEGER,available_at TEXT,event_us INTEGER,available_us INTEGER);
        CREATE TABLE decisions(decision_id TEXT,entity_id TEXT,decision_at TEXT,decision_us INTEGER);
        CREATE TABLE specs(name TEXT,source TEXT,feature TEXT,window_days REAL,
          aggregation TEXT,window_us INTEGER);
        CREATE INDEX temporal_lookup ON observations(entity_id,source,feature,event_us,available_us);
        """)
        db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            _sql_observation(row)
            for row in observations
        ])
        db.executemany("INSERT INTO decisions VALUES (?,?,?,?)", [
            (row.decision_id, row.entity_id, row.decision_at, _instant(row.decision_at))
            for row in decisions
        ])
        db.executemany("INSERT INTO specs VALUES (?,?,?,?,?,?)", [
            tuple(asdict(spec).values()) + (spec.window_us,) for spec in specs
        ])
        query = CTE + """
        SELECT d.decision_id,d.entity_id,d.decision_at,s.name,s.source,s.feature,
          s.window_days,s.aggregation,
          CASE WHEN count(a.record_id)=0 THEN NULL
            WHEN s.aggregation='count' THEN count(a.record_id)
            WHEN s.aggregation='sum' THEN precise_sum(CASE WHEN s.aggregation='sum' THEN a.value END)
            ELSE precise_mean(CASE WHEN s.aggregation='mean' THEN a.value END) END,
          count(a.record_id),
          CASE WHEN count(a.record_id)>0 THEN 'selected'
            WHEN NOT EXISTS (SELECT 1 FROM observations o
              WHERE o.entity_id=d.entity_id AND o.source=s.source AND o.feature=s.feature
                AND o.event_us<=d.decision_us AND d.decision_us-o.event_us<=s.window_us)
              THEN 'no_history'
            WHEN NOT EXISTS (SELECT 1 FROM eligible e WHERE e.decision_id=d.decision_id
              AND e.source=s.source AND e.feature=s.feature AND e.version_rank=1
              AND d.decision_us-e.event_us<=s.window_us) THEN 'not_available'
            ELSE 'deleted' END
        FROM decisions d CROSS JOIN specs s
        LEFT JOIN active a ON a.decision_id=d.decision_id AND a.name=s.name
        GROUP BY d.decision_id,s.name ORDER BY d.decision_id,s.name
        """
        try:
            features = [RollingFeature(*row) for row in db.execute(query)]
            members = [RollingMember(*row) for row in db.execute(CTE + """
              SELECT decision_id,name,record_id,revision,event_at,published_at,
                ingested_at,available_at,value FROM active
              ORDER BY decision_id,name,event_us,record_id
            """)]
        except sqlite3.DataError as error:
            raise ValueError("rolling aggregate is outside the finite binary64 range") from error
    if any(row.value is not None and not math.isfinite(row.value) for row in features):
        raise ValueError("rolling aggregate is outside the finite binary64 range")
    return features, members


def reference_rolling(observations, decisions, specs):
    """Independent temporal enumeration, sharing only the declared arithmetic primitive."""
    observations, decisions, specs = validate_rolling(observations, decisions, specs)
    features, members = [], []
    for decision in decisions:
        for spec in specs:
            history = [row for row in observations
                if (row.entity_id, row.source, row.feature) == (decision.entity_id, spec.source, spec.feature)
                and 0 <= _instant(decision.decision_at) - _instant(row.event_at) <= spec.window_us]
            known = [row for row in history if row.available_at <= decision.decision_at]
            versions = {}
            for row in known:
                if row.event_at not in versions or versions[row.event_at].revision < row.revision:
                    versions[row.event_at] = row
            active = sorted((row for row in versions.values() if not row.deleted),
                            key=lambda row: (row.event_at, row.record_id))
            status = "selected" if active else "no_history" if not history else "not_available" if not known else "deleted"
            value = None
            if active:
                if spec.aggregation == "count":
                    value = len(active)
                else:
                    value = _aggregate([float(row.value) for row in active], mean=spec.aggregation == "mean")
            features.append(RollingFeature(decision.decision_id, decision.entity_id,
                decision.decision_at, spec.name, spec.source, spec.feature, spec.window_days,
                spec.aggregation, value, len(active), status))
            members.extend(RollingMember(decision.decision_id, spec.name, row.record_id,
                row.revision, row.event_at, row.published_at, row.ingested_at,
                row.available_at, float(row.value)) for row in active)
    return features, members
