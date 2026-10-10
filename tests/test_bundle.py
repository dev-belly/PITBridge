from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pitbridge.bundle import canonical, read_json, verify_bundle, write_bundle
from pitbridge.cli import main
from pitbridge.demo import demo_inputs


class BundleTests(unittest.TestCase):
    def test_demo_and_saved_inputs_replay(self):
        with TemporaryDirectory() as tmp:
            summary = write_bundle(demo_inputs(),tmp)
            self.assertEqual(summary["future_knowledge_rows"],11)
            self.assertEqual(summary["snapshot_rows"],45)
            self.assertTrue(verify_bundle(tmp)["verified"])

    def test_output_is_deterministic(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            write_bundle(demo_inputs(),a); write_bundle(demo_inputs(),b)
            self.assertEqual({p.name:p.read_bytes() for p in Path(a).iterdir()}, {p.name:p.read_bytes() for p in Path(b).iterdir()})

    def test_changed_hash_fails_verification(self):
        with TemporaryDirectory() as tmp:
            write_bundle(demo_inputs(),tmp)
            Path(tmp,"snapshots.csv").write_text("edited",encoding="utf-8",newline="")
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                verify_bundle(tmp)

    def test_rehashed_false_metric_still_fails_semantic_replay(self):
        with TemporaryDirectory() as tmp:
            write_bundle(demo_inputs(),tmp)
            path=Path(tmp,"summary.json")
            data=read_json(path); data["future_knowledge_rows"]=0
            path.write_text(canonical(data),encoding="utf-8",newline="")
            manifest=read_json(Path(tmp,"manifest.json"))
            manifest["files"][path.name]=sha256(path.read_bytes()).hexdigest()
            Path(tmp,"manifest.json").write_text(canonical(manifest),encoding="utf-8",newline="")
            with self.assertRaisesRegex(ValueError,"semantic replay mismatch"):
                verify_bundle(tmp)

    def test_unexpected_manifest_path_is_rejected(self):
        with TemporaryDirectory() as tmp:
            write_bundle(demo_inputs(),tmp)
            manifest=read_json(Path(tmp,"manifest.json")); manifest["files"]["../outside"]="0"
            Path(tmp,"manifest.json").write_text(canonical(manifest),encoding="utf-8",newline="")
            with self.assertRaisesRegex(ValueError,"unexpected artifact"):
                verify_bundle(tmp)

    def test_nonfinite_and_duplicate_json_are_rejected(self):
        with TemporaryDirectory() as tmp:
            for text in ('{"a": NaN}', '{"a":1,"a":2}'):
                Path(tmp,"bad.json").write_text(text,encoding="utf-8",newline="")
                with self.assertRaises(ValueError):
                    read_json(Path(tmp,"bad.json"))

    def test_html_escapes_untrusted_identifiers(self):
        with TemporaryDirectory() as tmp:
            data=demo_inputs(); data["decisions"][0]["decision_id"]="<script>unsafe</script>"
            write_bundle(data,tmp)
            html=Path(tmp,"report.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;",html)
            self.assertNotIn("<script>unsafe</script>",html)

    def test_user_supplied_report_is_not_labeled_synthetic(self):
        with TemporaryDirectory() as tmp:
            data=demo_inputs(); data.pop("data_kind")
            write_bundle(data,tmp)
            self.assertIn("USER-SUPPLIED DATA",Path(tmp,"report.html").read_text(encoding="utf-8"))

    def test_cli_returns_nonzero_for_missing_artifacts(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(main(["verify","--out",tmp]),2)

    def test_malformed_manifest_has_a_clear_validation_error(self):
        with TemporaryDirectory() as tmp:
            for payload in ([], {"files":None}, {"files":[]}):
                Path(tmp,"manifest.json").write_text(canonical(payload),encoding="utf-8",newline="")
                with self.assertRaisesRegex(ValueError,"unsupported manifest"):
                    verify_bundle(tmp)
