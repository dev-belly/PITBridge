"""Exercise report selectors in the runner's real Chrome, without Python extras.

Requires Google Chrome and a matching chromedriver on PATH, or the
CHROMEWEBDRIVER directory supplied by GitHub's Ubuntu runner image.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT = r"""
const spec = arguments[0];
const select = document.getElementById(spec.select);
if (!select) throw new Error('Missing selector');
for (const label of spec.labels) {
    const option = Array.from(select.options).find(o => o.value && JSON.parse(o.value) === label);
    if (!option) throw new Error('Missing exact identity: ' + JSON.stringify(label));
    select.value = option.value;
    select.dispatchEvent(new Event('change', {bubbles:true}));
    if (spec.chart) {
        const expected = data.histograms[label].counts;
        const actual = Array.from(document.querySelectorAll('#histogram rect'), r => Number(r.getAttribute('height')));
        const peak = Math.max(...expected,1);
        if (actual.length !== expected.length || actual.some((v,i) => Math.abs(v-200*expected[i]/peak)>1e-10))
            throw new Error('Histogram selected another scenario');
        const sectors = data.sector_es.filter(r => r.scenario === label).length;
        if (!sectors || document.querySelectorAll('#sectors tr').length !== sectors)
            throw new Error('Sector attribution missing or selected another scenario');
    } else {
        const rows = Array.from(document.querySelectorAll(spec.rows))
            .filter(r => getComputedStyle(r).display !== 'none');
        if (!rows.length || rows.some(r => JSON.parse(r.dataset[spec.attribute]) !== label))
            throw new Error('Empty or incorrect filtered result: ' + JSON.stringify(label));
    }
}
return spec.labels.length;
"""

TRIAL_SCRIPT = r"""
const expected = [null, 'invoice-v1', 'invoice-v2'];
const statuses = ['not_available', 'selected', 'selected'];
const presets = [...document.querySelectorAll('[data-preset]')];
if (presets.length !== 3) throw new Error('Missing invoice presets');
const record = document.getElementById('safe-record');
const output = document.getElementById('output');
const error = document.getElementById('input-error');
const decision = document.getElementById('decision-at');
const ingestion = document.getElementById('ingested-at');
const form = document.getElementById('timing-form');
function check(status, id) {
  if (output.hidden || !error.hidden || !record.textContent.startsWith(status)
      || (id && !record.textContent.includes(id))) throw new Error('Incorrect visible snapshot: ' + record.textContent);
}
for (let index=0; index<presets.length; index++) {
  presets[index].click(); check(statuses[index], expected[index]);
}
decision.value = '2026-04-03T00:00:00Z';
ingestion.value = '2026-04-03T00:00:00.000001Z';
form.requestSubmit(); check('selected', 'invoice-v1');
ingestion.value = '2026-04-03T00:00:00Z';
form.requestSubmit(); check('selected', 'invoice-v2');
ingestion.value = '2026-04-03T00:00:00.0000009Z';
form.requestSubmit();
if (error.hidden || !output.hidden || !error.textContent.includes('six fractional digits')
    || !document.getElementById('share').disabled) throw new Error('Invalid precision retained a visible result or share link');
presets[1].click(); check('selected', 'invoice-v1');
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.get('decision') !== decision.value || fragment.get('ingested') !== ingestion.value)
  throw new Error('Share fragment does not reproduce the visible scenario');
if (document.documentElement.scrollWidth > window.innerWidth + 1) throw new Error('Lesson overflows its viewport');
return 7;
"""

TRIAL_EXPORT_SCRIPT = r"""
const done = arguments[arguments.length - 1];
(async () => {
  const decision = document.getElementById('decision-at');
  const ingestion = document.getElementById('ingested-at');
  const link = document.getElementById('download-case');
  if (!link || link.download !== 'pitbridge-scenario.json') throw new Error('Missing named download');
  async function edit(stamp) {
    ingestion.value = stamp;
    ingestion.dispatchEvent(new Event('input', {bubbles: true}));
    if (!link.href.startsWith('blob:')) throw new Error('Missing current export URL');
    return (await fetch(link.href)).json();
  }
  decision.value = '2026-04-03T00:00:00Z';
  const late = await edit('2026-04-03T00:00:00.000001Z');
  if (!document.getElementById('safe-record').textContent.includes('invoice-v1'))
    throw new Error('Input edit did not update visible selection');
  const equal = await edit('2026-04-03T00:00:00Z');
  if (!document.getElementById('safe-record').textContent.includes('invoice-v2'))
    throw new Error('Cutoff equality did not update visible selection');
  if (late.observations[1].ingested_at !== '2026-04-03T00:00:00.000001Z'
      || equal.observations[1].ingested_at !== '2026-04-03T00:00:00Z')
    throw new Error('Export is stale or lost microsecond precision');
  ingestion.value = '2026-04-03T00:00:00.0000009Z';
  ingestion.dispatchEvent(new Event('input', {bubbles: true}));
  if (link.hasAttribute('href') || !document.getElementById('output').hidden)
    throw new Error('Invalid input retained a downloadable case');
  const downloaded = await edit('2026-04-03T00:00:00.000001Z');
  if (document.documentElement.scrollWidth > innerWidth + 1) throw new Error('Export overflows viewport');
  link.click();
  return {downloaded, checks: 4};
})().then(done, error => done({error: String(error)}));
"""


def browser_check(cases, root):
    from pitbridge.bundle import decode_inputs, verify_bundle, write_bundle
    from pitbridge.core import build_snapshot, reference_snapshot

    downloads = root / "downloads"
    downloads.mkdir()
    driver = shutil.which("chromedriver")
    if not driver:
        candidate = Path(os.environ.get("CHROMEWEBDRIVER", "")) / "chromedriver"
        if candidate.is_file():
            driver = str(candidate.resolve())
    if not driver:
        raise RuntimeError("Install Chrome and a matching chromedriver, or set CHROMEWEBDRIVER")
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    address = f"http://127.0.0.1:{port}"

    def call(method, endpoint, payload=None, *, timeout=15):
        request = urllib.request.Request(
            address + endpoint,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)["value"]
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error

    session = None
    process = subprocess.Popen([driver, f"--port={port}"], stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                call("GET", "/status")
                break
            except urllib.error.URLError:
                if process.poll() is not None:
                    raise RuntimeError("chromedriver exited before becoming ready") from None
                time.sleep(0.1)
        else:
            raise RuntimeError("chromedriver did not become ready")
        session = call(
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "chrome",
                        "goog:chromeOptions": {
                            "args": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage"],
                            "prefs": {"download.default_directory": str(downloads), "download.prompt_for_download": False},
                        },
                    }
                }
            },
            # A busy hosted runner may need longer for Chrome's first startup.
            # Page operations and selector assertions keep their shorter limit.
            timeout=60,
        )["sessionId"]
        selections = 0
        viewport_widths = []
        downloaded_cases = 0
        for case in cases:
            if "viewport" in case:
                call("POST", f"/session/{session}/window/rect", case["viewport"])
            call("POST", f"/session/{session}/url", {"url": (root / case["file"]).as_uri()})
            if "viewport" in case:
                width = call("POST", f"/session/{session}/execute/sync", {"script": "return window.innerWidth;", "args": []})
                if width != case["viewport"]["width"]:
                    raise RuntimeError(f"Requested viewport width {case['viewport']['width']}, observed {width}")
                viewport_widths.append(width)
            route = "async" if case.get("export") else "sync"
            result = call("POST", f"/session/{session}/execute/{route}", {"script": case.get("script", SCRIPT), "args": [case]})
            if case.get("export"):
                if "error" in result:
                    raise AssertionError(result["error"])
                downloaded = downloads / "pitbridge-scenario.json"
                for _ in range(100):
                    if downloaded.is_file():
                        break
                    time.sleep(0.05)
                else:
                    raise AssertionError("Chrome did not save the scenario download")
                portable = json.loads(downloaded.read_text(encoding="utf-8"))
                if portable != result["downloaded"] or portable.get("data_kind") != "synthetic":
                    raise AssertionError("Downloaded bytes differ from the current synthetic scenario")
                inputs = decode_inputs(portable)
                rows = build_snapshot(*inputs)
                if rows != reference_snapshot(*inputs) or len(rows) != 1 or rows[0].record_id != "invoice-v1" or rows[0].value != 100000:
                    raise AssertionError("Downloaded scenario differs from visible browser selection")
                report = root / f"downloaded-report-{downloaded_cases}"
                write_bundle(portable, report)
                if verify_bundle(report).get("verified") is not True:
                    raise AssertionError("Downloaded case did not independently replay")
                downloaded.unlink()
                downloaded_cases += 1
                selections += result["checks"]
            else:
                selections += result
        print(json.dumps({"status": "passed", "browser": "Chrome", "reports": len(cases), "selections": selections, "viewport_widths": viewport_widths, "downloaded_cases_replayed": downloaded_cases}))
    finally:
        if session is not None:
            try:
                call("DELETE", f"/session/{session}")
            finally:
                process.terminate()
        else:
            process.terminate()
        process.wait(timeout=10)


def main():
    from pitbridge.rolling_bundle import rolling_artifacts, rolling_demo_inputs

    labels = ["sample\rone", "sample\none", "sample\x00one", "sample�one"]
    data = rolling_demo_inputs()
    for row, label in zip(data["decisions"], labels, strict=True):
        row["decision_id"] = label
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        (root / "report.html").write_text(rolling_artifacts(data)["report.html"], encoding="utf-8")
        (root / "try.html").write_bytes((Path(__file__).resolve().parents[1] / "site/try/index.html").read_bytes())
        browser_check(
            [
                {
                    "file": "report.html",
                    "select": "decision",
                    "rows": "tr[data-decision]",
                    "attribute": "decision",
                    "labels": labels,
                },
                {"file": "try.html", "script": TRIAL_SCRIPT, "viewport": {"width": 1280, "height": 1000}},
                {"file": "try.html", "script": TRIAL_SCRIPT, "viewport": {"width": 390, "height": 844}},
                {"file": "try.html", "script": TRIAL_EXPORT_SCRIPT, "export": True, "viewport": {"width": 1280, "height": 1000}},
                {"file": "try.html", "script": TRIAL_EXPORT_SCRIPT, "export": True, "viewport": {"width": 390, "height": 844}},
            ],
            root,
        )


if __name__ == "__main__":
    main()
