"""Replayable JSON/CSV evidence and a standalone browser report."""

from collections import Counter
import csv
from dataclasses import asdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path

from .core import Decision, FeatureSpec, Observation, build_snapshot, reference_snapshot, validate


FILES = ("inputs.json", "snapshots.csv", "comparison.csv", "summary.json", "report.html")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def read_json(path):
    def bad(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=bad, object_pairs_hook=pairs)


def decode_inputs(data):
    if not isinstance(data, dict) or not {"observations", "decisions", "specs"} <= set(data) or set(data) - {"observations", "decisions", "specs", "data_kind"}:
        raise ValueError("input object requires observations, decisions, specs; only data_kind is optional")
    if data.get("data_kind", "user_supplied") not in ("synthetic", "user_supplied"):
        raise ValueError("data_kind must be synthetic or user_supplied")
    if any(not isinstance(data[key], list) for key in ("observations", "decisions", "specs")):
        raise ValueError("all input sections must be arrays")
    try:
        return validate([Observation(**row) for row in data["observations"]], [Decision(**row) for row in data["decisions"]], [FeatureSpec(**row) for row in data["specs"]])
    except TypeError as exc:
        raise ValueError(f"input schema mismatch: {exc}") from exc


def spreadsheet_cell(value):
    """Neutralize formula-shaped strings; leave numeric financial values untouched."""
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n"))
        or value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


def csv_text(rows, fields):
    import io
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writerow({field: spreadsheet_cell(field) for field in fields})
    writer.writerows({field: spreadsheet_cell(value) for field, value in row.items()}
                    for row in rows)
    return stream.getvalue()


def compare_unsafe(obs, rows):
    """A deliberately unsafe event-only baseline, clearly isolated from features."""
    comparison = []
    for row in rows:
        candidates = [o for o in obs if (o.entity_id, o.source, o.feature) == (row.entity_id, row.source, row.feature) and o.event_at <= row.decision_at]
        baseline = max(candidates, key=lambda o: (o.event_at, o.revision)) if candidates else None
        comparison.append({
            "decision_id": row.decision_id, "source": row.source, "feature": row.feature,
            "safe_record_id": row.record_id, "safe_value": row.value, "safe_status": row.status,
            "unsafe_record_id": baseline.record_id if baseline else None,
            "unsafe_value": baseline.value if baseline else None,
            "unsafe_uses_future_knowledge": bool(baseline and baseline.available_at > row.decision_at),
            "different_selection": row.record_id != (baseline.record_id if baseline else None),
        })
    return comparison


def render_report(summary, comparison, snapshots):
    kind = "SYNTHETIC FINANCIAL DATA" if summary["data_kind"] == "synthetic" else "USER-SUPPLIED DATA"
    provenance = "Synthetic demonstration · No real borrower data" if summary["data_kind"] == "synthetic" else "User-supplied inputs · Source authenticity has not been independently audited"
    counts = " · ".join(f"{escape(k)}: {v}" for k, v in summary["status_counts"].items())
    comparison_rows = "".join(
        '<tr data-different="' + str(r["different_selection"]).lower() + '">' +
        "".join(f"<td>{escape(str(r[k] if r[k] is not None else '—'))}</td>" for k in ("decision_id", "source", "feature", "safe_value", "safe_status", "unsafe_value", "unsafe_uses_future_knowledge")) + "</tr>"
        for r in comparison
    )
    lineage_rows = "".join("<tr>" + "".join(f"<td>{escape(str(getattr(r,k) if getattr(r,k) is not None else '—'))}</td>" for k in ("decision_id", "source", "feature", "record_id", "revision", "event_at", "available_at")) + "</tr>" for r in snapshots if r.status == "selected")
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PITBridge · Decision-time evidence</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0c1422;color:#e6edf7;font:16px/1.6 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:48px 24px}}h1{{font-size:clamp(32px,6vw,64px);line-height:1.1;margin:16px 0}}h2{{margin-top:44px}}p{{color:#a9b9cf}}.tag{{color:#64e5c4;letter-spacing:.14em;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:32px 0}}.card{{border:1px solid #293952;border-radius:14px;padding:22px;background:#111e31}}.value{{display:block;font-size:38px;font-weight:700}}.scroll{{overflow-x:auto;border:1px solid #293952;border-radius:12px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:12px;white-space:nowrap;border-bottom:1px solid #22314a}}th{{background:#17263b;color:#9fefd9}}code{{color:#9fefd9}}a{{color:#9fefd9}}label{{display:block;margin:16px 0;cursor:pointer}}footer{{margin-top:48px;color:#8ca1bc}}.hidden{{display:none}}
</style><main><div class="tag">PITBRIDGE / {kind}</div>
<h1>What was known<br>when the decision was made?</h1>
<p><a href="https://dev-belly.github.io/PITBridge/rolling/">Explore rolling-window features and their source membership</a></p>
<p>Availability-aware SQL snapshots with publication, ingestion, revision and record-level lineage.</p>
<div class="cards"><div class="card"><span class="value">{summary['decisions']}</span>Decisions</div><div class="card"><span class="value">{summary['snapshot_rows']}</span>Feature lookups</div><div class="card"><span class="value">{summary['future_knowledge_rows']}</span>Unsafe future-data selections</div><div class="card"><span class="value">{summary['different_selections']}</span>Selections changed</div></div>
<p><b>Independent replay:</b> SQLite output matches the Python enumeration oracle. {counts}</p>
<h2>Inspect the leakage counterexample</h2><p>The unsafe comparison filters only event time and takes the highest revision. It intentionally ignores availability, tombstones and freshness; it is never exported as a training feature.</p>
<label><input type="checkbox" id="different" checked> Show changed selections only</label>
<div class="scroll"><table id="comparison"><thead><tr><th>Decision</th><th>Source</th><th>Feature</th><th>Safe value</th><th>Safe status</th><th>Unsafe value</th><th>Uses future knowledge?</th></tr></thead><tbody>{comparison_rows}</tbody></table></div>
<h2>Trace each selected observation</h2><p>Knowledge time = max(publication, ingestion). Every selected observation was available at or before the decision. A later historical correction cannot overwrite an earlier snapshot.</p>
<div class="scroll"><table><thead><tr><th>Decision</th><th>Source</th><th>Feature</th><th>Record</th><th>Revision</th><th>Event time</th><th>Available time</th></tr></thead><tbody>{lineage_rows}</tbody></table></div>
<h2>Replay locally</h2><p><code>pitbridge verify --out demo</code> checks file hashes, recomputes every snapshot through both implementations, and compares all derived evidence. Hashes detect accidental edits; they are not a digital signature.</p>
<footer>{provenance} · <a href="https://github.com/dev-belly/PITBridge">Source and methodology</a></footer></main>
<script>const box=document.getElementById('different');function filter(){{document.querySelectorAll('#comparison tbody tr').forEach(r=>r.classList.toggle('hidden',box.checked&&r.dataset.different==='false'))}}box.addEventListener('change',filter);filter();</script></html>\n"""


def artifacts(data):
    obs, dec, specs = decode_inputs(data)
    normalized = {"data_kind": data.get("data_kind", "user_supplied"), "observations": [asdict(r) for r in obs], "decisions": [asdict(r) for r in dec], "specs": [asdict(r) for r in specs]}
    rows = build_snapshot(obs, dec, specs)
    if rows != reference_snapshot(obs, dec, specs):
        raise ValueError("SQL/reference replay mismatch")
    comparison = compare_unsafe(obs, rows)
    summary = {"schema_version": 1, "data_kind": normalized["data_kind"], "observations": len(obs), "decisions": len(dec), "snapshot_rows": len(rows), "status_counts": dict(sorted(Counter(r.status for r in rows).items())), "future_knowledge_rows": sum(r["unsafe_uses_future_knowledge"] for r in comparison), "different_selections": sum(r["different_selection"] for r in comparison), "independent_replay": True}
    # All outputs are derived from normalized inputs; there is no wall-clock timestamp.
    return {"inputs.json": canonical(normalized), "snapshots.csv": csv_text([asdict(r) for r in rows], list(asdict(rows[0]))), "comparison.csv": csv_text(comparison, list(comparison[0])), "summary.json": canonical(summary), "report.html": render_report(summary, comparison, rows)}


def write_bundle(data, out):
    files = artifacts(data)
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8", newline="")
    manifest = {"schema_version": 1, "engine": "pitbridge/0.1.0", "files": {name: sha256(content.encode()).hexdigest() for name, content in sorted(files.items())}}
    (target / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return read_json(target / "summary.json")


def verify_bundle(out):
    target = Path(out)
    manifest = read_json(target / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict) or manifest.get("schema_version") != 1 or manifest.get("engine") != "pitbridge/0.1.0" or set(manifest["files"]) != set(FILES):
        raise ValueError("unsupported manifest or unexpected artifact paths")
    for name in FILES:
        if sha256((target / name).read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError(f"hash mismatch: {name}")
    expected = artifacts(read_json(target / "inputs.json"))
    for name, content in expected.items():
        if (target / name).read_bytes() != content.encode():
            raise ValueError(f"semantic replay mismatch: {name}")
    return {"verified": True, "files": len(FILES), "independent_replay": True}
