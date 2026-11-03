import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))

from assessment import evidence_for, confirm_assessment, read_assessments


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = {
            "exam": {"exam_id": "exam_1", "prior_exam_id": "exam_0"},
            "lesions": [{"lesion_id": "les_1"}],
            "measurements": [{"lesion_id": "les_1", "roi_ref": "r1", "suv_max": 4.0}],
            "rows": [{"lesion_id": "les_1", "prior_suv": 8.0, "delta_suv_pct": -50.0}],
            "references": {
                "blood_pool": {"version": 1, "placement_confirmed": True, "suv_mean": 2.0},
                "liver": {"version": 1, "placement_confirmed": True, "suv_mean": 3.0},
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_candidate_uses_confirmed_references_and_rejects_stale_confirmation(self):
        context = evidence_for(self.state, "les_1")
        self.assertIn("4–5", context["suggestion"])
        result = confirm_assessment(self.temp.name, self.state, "les_1", context["fingerprint"],
                                    "4", "PMR", "doctor-1", "影像复核后确认")
        self.assertEqual(result["version"], 1)
        self.assertEqual(read_assessments(self.temp.name, "exam_1")["les_1"][-1]["score"], "4")
        self.state["measurements"][0]["suv_max"] = 5.0
        with self.assertRaisesRegex(ValueError, "已更新"):
            confirm_assessment(self.temp.name, self.state, "les_1", context["fingerprint"],
                               "5", "PMD", "doctor-1", "旧依据")

    def test_unconfirmed_reference_has_no_numeric_candidate(self):
        self.state["references"]["liver"]["placement_confirmed"] = False
        self.assertIn("无法", evidence_for(self.state, "les_1")["suggestion"])


if __name__ == "__main__":
    unittest.main()
