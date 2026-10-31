// Check the exact inline core that is delivered in the no-install lesson.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import vm from "node:vm";

const html = readFileSync(fileURLToPath(new URL("../site/try/index.html", import.meta.url)), "utf8");
const extract = id => {
  const matches = [...html.matchAll(new RegExp(`<script id="${id}"[^>]*>([\\s\\S]*?)<\\/script>`, "g"))];
  assert.equal(matches.length, 1, `Exactly one ${id} script is required`);
  return matches[0][1];
};
const fixture = JSON.parse(extract("invoice-fixture"));
const before = JSON.stringify(fixture);
const sandbox = vm.createContext({});
vm.runInContext(extract("trial-core"), sandbox);
const {select, parseUtc, inputs} = sandbox.PITTrial;
const project = row => ({record_id: row.record_id, value: row.value, status: row.status,
  unsafe_record_id: row.unsafe_record_id, unsafe_value: row.unsafe_value, unsafe_future: row.unsafe_future});

if (process.argv.includes("--cases")) {
  const cases = JSON.parse(readFileSync(0, "utf8"));
  const results = cases.map(({decision, ingested}) => {
    try { return {ok: true, ...project(select(fixture, decision, ingested)), inputs: inputs(fixture, decision, ingested)}; }
    catch { return {ok: false}; }
  });
  process.stdout.write(JSON.stringify(results));
} else {
  const ingested = "2026-04-03T00:00:00Z";
  for (const [decision, record, status, value, future] of [
    ["2026-01-30T00:00:00Z", null, "no_history", null, false],
    ["2026-02-01T00:00:00Z", null, "not_available", null, true],
    ["2026-02-15T00:00:00Z", "invoice-v1", "selected", 100000, true],
    ["2026-04-15T00:00:00Z", "invoice-v2", "selected", 135000, false],
    ["2026-05-01T00:00:00Z", "invoice-v2", "selected", 135000, false],
    ["2026-05-01T00:00:00.000001Z", null, "stale", null, false],
  ]) {
    const result = select(fixture, decision, ingested);
    assert.equal(result.record_id, record); assert.equal(result.status, status);
    assert.equal(result.value, value); assert.equal(result.unsafe_future, future);
  }
  assert.equal(parseUtc("1970-01-01T00:00:00.000001Z"), 1n);
  assert.equal(parseUtc("1969-12-31T23:59:59.999999Z"), -1n);
  assert.equal(select(fixture, ingested, "2026-04-03T00:00:00.000001Z").record_id, "invoice-v1");
  assert.equal(select(fixture, "2026-04-03T00:00:00.000001Z", "2026-04-03T00:00:00.000001Z").record_id, "invoice-v2");
  for (const stamp of ["2026-04-03T00:00:00.0000009Z", "2026-04-03T00:00:00.0000000Z", "2026-02-30T00:00:00Z", "0000-01-01T00:00:00Z", "2026-01-01", "2026-01-01T00:00:00+08:00", "<img src=x onerror=alert(1)>"]) {
    assert.throws(() => parseUtc(stamp));
    assert.throws(() => inputs(fixture, stamp, ingested));
    assert.throws(() => inputs(fixture, ingested, stamp));
  }
  assert.throws(() => select(fixture, ingested, "2026-01-30T00:00:00Z"));
  assert.throws(() => inputs(fixture, ingested, "2026-01-30T00:00:00Z"));
  const portable = inputs(fixture, "2026-04-03T00:00:00Z", "2026-04-03T00:00:00.000001Z");
  assert.equal(portable.data_kind, "synthetic");
  assert.equal(portable.observations[1].ingested_at, "2026-04-03T00:00:00.000001Z");
  portable.observations[0].value = -1;
  assert.equal(inputs(fixture, ingested, ingested).observations[0].value, 100000);
  assert.equal(JSON.stringify(fixture), before, "Selecting must not rewrite source records");
  console.log(JSON.stringify({status: "passed", core: "exact shipped inline script", precision: "integer microseconds", fixed_decisions: 6}));
}
