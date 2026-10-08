"""Invalid day limits must fail before binary64 conversion or artifact creation."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from pitbridge.core import FeatureSpec
from pitbridge.demo import demo_inputs
from pitbridge.rolling import RollingSpec
from pitbridge.rolling_bundle import rolling_demo_inputs


INVALID_LIMITS = (10**400, -(10**400), 10**1000, -(10**1000))


class WindowContractTests(unittest.TestCase):
    def test_snapshot_enormous_integer_limits_are_contract_errors(self):
        for limit in INVALID_LIMITS:
            with self.subTest(digits=len(str(abs(limit))), negative=limit < 0):
                with self.assertRaisesRegex(ValueError, "max_age_days"):
                    FeatureSpec("tax", "revenue", limit)

    def test_rolling_enormous_integer_limits_are_contract_errors(self):
        for limit in INVALID_LIMITS:
            with self.subTest(digits=len(str(abs(limit))), negative=limit < 0):
                with self.assertRaisesRegex(ValueError, "window_days"):
                    RollingSpec("revenue_sum", "tax", "revenue", limit)

    def assert_cli_rejected(self, data, command, field):
        with TemporaryDirectory() as tmp:
            inputs = Path(tmp, "inputs.json")
            inputs.write_text(json.dumps(data), encoding="utf-8")
            output = Path(tmp, "evidence")
            result = subprocess.run(
                [sys.executable, "-m", "pitbridge", command,
                 "--inputs", str(inputs), "--out", str(output)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("pitbridge:", result.stderr)
            self.assertIn(field, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((output / "manifest.json").exists())

    def test_snapshot_cli_rejects_enormous_json_limits_cleanly(self):
        for limit in INVALID_LIMITS:
            with self.subTest(digits=len(str(abs(limit))), negative=limit < 0):
                data = demo_inputs()
                data["specs"][0]["max_age_days"] = limit
                self.assert_cli_rejected(data, "build", "max_age_days")

    def test_rolling_cli_rejects_enormous_json_limits_cleanly(self):
        for limit in INVALID_LIMITS:
            with self.subTest(digits=len(str(abs(limit))), negative=limit < 0):
                data = rolling_demo_inputs()
                data["rolling_specs"][0]["window_days"] = limit
                self.assert_cli_rejected(data, "aggregate", "window_days")
