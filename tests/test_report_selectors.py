"""Browser option values must retain the identity used by data-decision rows."""

from html.parser import HTMLParser
import json
import re
import unittest

from pitbridge.rolling_bundle import rolling_artifacts, rolling_demo_inputs


class RollingSelector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.option = None
        self.values = []
        self.decisions = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "option":
            self.option = (attrs, [])
        elif tag == "tr" and "data-decision" in attrs:
            self.decisions.add(attrs["data-decision"])

    def handle_data(self, data):
        if self.option is not None:
            self.option[1].append(data)

    def handle_endtag(self, tag):
        if tag == "option":
            attrs, text = self.option
            fallback = re.sub(r"[ \t\n\r\f]+", " ", "".join(text)).strip(" \t\n\r\f")
            self.values.append(attrs.get("value", fallback))
            self.option = None


class ReportSelectorTests(unittest.TestCase):
    def test_internal_whitespace_and_markup_ids_keep_exact_selector_values(self):
        self.check_labels(["decision  one", "decision one", 'decision\ttwo " & <cutoff>', "decision\nthree"])

    def test_cr_lf_and_nul_ids_cannot_collapse_into_other_decisions(self):
        self.check_labels(["decision\rone", "decision\none", "decision\x00one", "decision�one"])

    def check_labels(self, labels):
        data = rolling_demo_inputs()
        for row, label in zip(data["decisions"], labels, strict=True):
            row["decision_id"] = label
        html = rolling_artifacts(data)["report.html"]
        parser = RollingSelector()
        parser.feed(html.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "�"))
        self.assertEqual({json.loads(value) for value in parser.values if value}, set(labels))
        self.assertEqual({json.loads(value) for value in parser.decisions}, set(labels))
        self.assertEqual(len(parser.values), len(labels) + 1)
        self.assertNotIn("<cutoff>", html)


if __name__ == "__main__":
    unittest.main()
