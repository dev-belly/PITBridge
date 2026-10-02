"""A separately versioned rolling-feature bundle; scalar bundles remain unchanged."""

from collections import Counter
from dataclasses import asdict, fields
from hashlib import sha256
from html import escape
from pathlib import Path

from .bundle import canonical, csv_text, read_json
from .core import Decision, Observation
from .rolling import RollingFeature, RollingMember, RollingSpec, build_rolling, reference_rolling, validate_rolling

FILES = ("inputs.json", "features.csv", "members.csv", "summary.json", "report.html")
ENGINE = "pitbridge/rolling/1"


def decode_rolling(data):
    required = {"observations", "decisions", "rolling_specs"}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {"data_kind"}:
        raise ValueError("rolling inputs require observations, decisions, rolling_specs; only data_kind is optional")
    if data.get("data_kind", "user_supplied") not in ("synthetic", "user_supplied"):
        raise ValueError("invalid data_kind")
    if any(not isinstance(data[key], list) for key in required):
        raise ValueError("rolling input sections must be arrays")
    try:
        return validate_rolling([Observation(**row) for row in data["observations"]],
            [Decision(**row) for row in data["decisions"]],
            [RollingSpec(**row) for row in data["rolling_specs"]])
    except TypeError as error:
        raise ValueError(f"rolling input schema mismatch: {error}") from error


def rolling_demo_inputs():
    def observation(record_id, event_at, value, revision=1, available_at=None, deleted=False):
        available_at = available_at or event_at
        return dict(record_id=record_id, entity_id="SME-A", source="bank", feature="net_inflow",
            event_at=event_at, published_at=available_at, ingested_at=available_at,
            revision=revision, value=value, deleted=deleted)
    return {"data_kind": "synthetic", "observations": [
        observation("boundary", "2026-01-11T18:00:00Z", 200),
        observation("outside", "2026-01-11T17:59:59Z", 10000),
        observation("cash-v1", "2026-02-01T00:00:00Z", 1000),
        observation("cash-v2", "2026-02-01T00:00:00Z", 4000, 2, "2026-02-11T00:00:00Z"),
        observation("refund", "2026-02-05T00:00:00Z", -200),
        observation("recent", "2026-02-08T00:00:00Z", 500, available_at="2026-02-09T00:00:00Z"),
        observation("cancel-v1", "2026-02-07T00:00:00Z", 800),
        observation("cancel-v2", "2026-02-07T00:00:00Z", None, 2, "2026-02-09T00:00:00Z", True),
        observation("late", "2026-02-09T00:00:00Z", 2000, available_at="2026-02-12T00:00:00Z"),
        observation("future-event", "2026-02-14T00:00:00Z", 300),
    ], "decisions": [
        dict(decision_id=f"SME-A-{day}", entity_id="SME-A", decision_at=f"2026-02-{day}T18:00:00Z")
        for day in (10, 11, 12)
    ] + [dict(decision_id="SME-B-12", entity_id="SME-B", decision_at="2026-02-12T18:00:00Z")],
    "rolling_specs": [
        dict(name="net_inflow_30d", source="bank", feature="net_inflow", window_days=30, aggregation="sum"),
        dict(name="mean_inflow_7d", source="bank", feature="net_inflow", window_days=7, aggregation="mean"),
        dict(name="observations_30d", source="bank", feature="net_inflow", window_days=30, aggregation="count"),
    ]}


def render_rolling(summary, features, members):
    label = "SYNTHETIC DATA" if summary["data_kind"] == "synthetic" else "USER-SUPPLIED DATA"
    def table_rows(rows, columns):
        return "".join(f'<tr data-decision="{escape(row.decision_id, quote=True)}">' +
            "".join(f"<td>{escape(str(getattr(row, key) if getattr(row, key) is not None else '—'))}</td>"
                    for key in columns) + "</tr>" for row in rows)
    feature_rows = table_rows(features, ("decision_id", "name", "value", "observation_count", "status"))
    member_rows = table_rows(members, ("decision_id", "name", "record_id", "revision", "event_at", "available_at", "value"))
    options = "".join(f'<option>{escape(name)}</option>' for name in sorted({row.decision_id for row in features}))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PITBridge · Rolling financial features</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#0c1422;color:#e6edf7;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:48px 24px}}h1{{font-size:clamp(34px,6vw,60px);line-height:1.1}}h2{{margin-top:40px}}p{{color:#a9b9cf}}.tag,a,code{{color:#64e5c4}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}.card{{padding:20px;background:#111e31;border:1px solid #293952;border-radius:12px}}.value{{display:block;font-size:34px;font-weight:700}}.scroll{{overflow:auto;border:1px solid #293952;border-radius:12px}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #293952;white-space:nowrap}}th{{color:#9fefd9;background:#17263b}}select{{font:inherit;color:#e6edf7;background:#17263b;padding:8px;border:1px solid #3c566f;border-radius:6px}}label{{display:block;margin:20px 0}}.hidden{{display:none}}footer{{margin-top:40px;color:#8ca1bc}}
</style><main><div class="tag">PITBRIDGE / ROLLING FEATURES / {label}</div>
<h1>What did the last 30 days<br>look like at decision time?</h1>
<p>Sum, mean and count use the latest revision actually available for each event. Future corrections and known cancellations cannot inflate an earlier feature.</p>
<div class="cards"><div class="card"><span class="value">{summary['decisions']}</span>Decisions</div><div class="card"><span class="value">{summary['feature_rows']}</span>Rolling lookups</div><div class="card"><span class="value">{summary['member_rows']}</span>Contributing-record links</div><div class="card"><span class="value">SQL = Python</span>Independent temporal replay</div></div>
<h2>Inspect the features</h2><p>The window includes both boundaries. An empty or unavailable window keeps a missing value; its observation count is metadata, not an assumed business zero.</p>
<label>Decision <select id="decision"><option value="">All decisions</option>{options}</select></label>
<div class="scroll"><table><thead><tr><th>Decision</th><th>Feature</th><th>Value</th><th>Observations</th><th>Status</th></tr></thead><tbody>{feature_rows}</tbody></table></div>
<h2>Trace every contribution</h2><p>Each row identifies the selected source revision. One record can contribute to several declared windows. Counts refer to observations, not borrowers or days.</p>
<div class="scroll"><table><thead><tr><th>Decision</th><th>Feature</th><th>Record</th><th>Revision</th><th>Event</th><th>Available</th><th>Value</th></tr></thead><tbody>{member_rows}</tbody></table></div>
<h2>Reproduce the result</h2><p><code>pitbridge verify-rolling --out demo/rolling</code> checks hashes and reruns SQL and the Python enumerator for both features and membership. Binary64 values are not exact monetary accounting, and observed events do not establish complete source coverage.</p>
<p><a href="features.csv">Feature rows</a> · <a href="members.csv">Source membership</a> · <a href="inputs.json">Inputs</a> · <a href="summary.json">Summary</a></p>
<footer>{label} · <a href="https://github.com/dev-belly/PITBridge/blob/main/docs/ROLLING.md">Method and case study</a></footer></main>
<script>const select=document.getElementById('decision');select.addEventListener('change',()=>document.querySelectorAll('tr[data-decision]').forEach(row=>row.classList.toggle('hidden',select.value!==''&&row.dataset.decision!==select.value)));</script></html>\n"""


def rolling_artifacts(data):
    observations, decisions, specs = decode_rolling(data)
    features, members = build_rolling(observations, decisions, specs)
    if (features, members) != reference_rolling(observations, decisions, specs):
        raise ValueError("rolling SQL/reference mismatch")
    normalized = {"data_kind": data.get("data_kind", "user_supplied"),
        "observations": [asdict(row) for row in observations],
        "decisions": [asdict(row) for row in decisions], "rolling_specs": [asdict(spec) for spec in specs]}
    summary = {"schema_version": 1, "data_kind": normalized["data_kind"], "observations": len(observations),
        "decisions": len(decisions), "feature_rows": len(features), "member_rows": len(members),
        "status_counts": dict(sorted(Counter(row.status for row in features).items())),
        "window_boundaries": "inclusive", "independent_temporal_replay": True}
    return {"inputs.json": canonical(normalized), "summary.json": canonical(summary),
        "features.csv": csv_text([asdict(row) for row in features], [field.name for field in fields(RollingFeature)]),
        "members.csv": csv_text([asdict(row) for row in members], [field.name for field in fields(RollingMember)]),
        "report.html": render_rolling(summary, features, members)}


def write_rolling_bundle(data, out):
    artifacts = rolling_artifacts(data)
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (target/name).write_text(content, encoding="utf-8", newline="")
    manifest = {"schema_version": 1, "engine": ENGINE,
        "files": {name: sha256(content.encode()).hexdigest() for name, content in sorted(artifacts.items())}}
    (target/"manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return read_json(target/"summary.json")


def verify_rolling_bundle(out):
    target = Path(out)
    manifest = read_json(target/"manifest.json")
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or manifest.get("engine") != ENGINE
            or not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != set(FILES)):
        raise ValueError("unsupported rolling manifest or unexpected artifact paths")
    for name in FILES:
        if sha256((target/name).read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError(f"hash mismatch: {name}")
    for name, content in rolling_artifacts(read_json(target/"inputs.json")).items():
        if (target/name).read_bytes() != content.encode():
            raise ValueError(f"rolling semantic replay mismatch: {name}")
    return {"verified": True, "files": len(FILES), "independent_temporal_replay": True}
