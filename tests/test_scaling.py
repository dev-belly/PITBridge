import tempfile
import unittest
from pathlib import Path

from pitbridge.benchmark import measure, run_scaling, workload
from pitbridge.core import build_snapshot, reference_snapshot


class ScalingTests(unittest.TestCase):
    def test_late_revisions_tombstones_fallback_and_ttl(self):
        inputs = workload(40)
        actual = build_snapshot(*inputs)
        self.assertEqual(actual, reference_snapshot(*inputs))
        first = [row for row in actual if row.entity_id == "E0000000"]
        self.assertEqual([row.revision for row in first], [1, 2, 1, None])
        self.assertEqual(
            [row.status for row in first], ["selected", "selected", "selected", "stale"]
        )
        self.assertEqual(first[2].record_id, "O0000000-16-1")

    def test_isolated_trials_are_deterministic_and_record_full_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_scaling((40,), repeats=2, destination=directory)
            runs = result["trials"][0]["runs"]
            self.assertEqual(runs[0]["output_sha256"], runs[1]["output_sha256"])
            self.assertEqual(runs[0]["oracle_lookups"], 8)
            self.assertEqual(runs[0]["lookups"], 8)
            self.assertTrue((Path(directory) / "scaling.json").is_file())
            self.assertEqual(set(result["source_sha256"]), {"benchmark.py", "core.py"})

    def test_rejects_partial_entity_workloads(self):
        for rows in (0, 19, 21):
            with self.assertRaises(ValueError):
                measure(rows)


if __name__ == "__main__":
    unittest.main()
