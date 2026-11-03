"""Percent change requires a valid, nonzero matched baseline."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from report_draft import comparison_rows, _format_section


def bundle(visit):
    return json.loads((ROOT / "schemas" / "v0" / "examples" / f"demo_001_{visit}.json").read_text(encoding="utf-8"))


class ComparisonPercentTests(unittest.TestCase):
    def setUp(self):
        self.current = bundle("followup")
        self.prior = bundle("baseline")
        for side in (self.current, self.prior):
            side["lesions"][0]["lesion_track_id"] = "paired"

    def test_percent_change_is_relative_to_baseline_and_appears_in_report(self):
        self.prior["measurements"][0]["suv_max"] = 12.0
        self.current["measurements"][0]["suv_max"] = 9.0
        row, = comparison_rows(self.current, self.prior)
        self.assertEqual(row["delta_suv_pct"], -25.0)
        self.assertIn("-25%", _format_section(self.current, self.prior))

    def test_zero_or_missing_baseline_has_no_percent_result(self):
        for baseline in (0.0, None):
            self.prior["measurements"][0]["suv_max"] = baseline
            row, = comparison_rows(self.current, self.prior)
            self.assertIsNone(row["delta_suv_pct"])


if __name__ == "__main__":
    unittest.main()
