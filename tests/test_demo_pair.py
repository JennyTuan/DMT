"""Exercise both visits through the same DICOM importer and ROI measurement as the UI."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/petfollow-lymphoma"), str(ROOT / "fixtures")]

from imaging import load_study
from make_demo import make_demo, make_demo_pair
from roi_store import grow_region
from suv import suv_for_roi


class DemoPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.directory = Path(tmp.name)
        # Simulate upgrading an existing Pack 03 installation.
        make_demo(cls.directory, quantitative=True)
        cls.original = load_study(cls.directory / "petfollow-demo-v2")
        cls.baseline_dir, cls.followup_dir = make_demo_pair(cls.directory)
        cls.baseline = load_study(cls.baseline_dir)
        cls.followup = load_study(cls.followup_dir)

    def test_distinct_ordered_visits_for_the_same_patient(self):
        earlier, later = self.baseline.exam, self.followup.exam
        self.assertEqual(earlier["patient_pseudo_id"], later["patient_pseudo_id"])
        self.assertNotEqual(earlier["exam_id"], later["exam_id"])
        self.assertLess(datetime.fromisoformat(earlier["study_datetime"]),
                        datetime.fromisoformat(later["study_datetime"]))
        self.assertTrue(earlier["is_synthetic"] and later["is_synthetic"])
        self.assertTrue(earlier["attenuation_corrected"] and later["attenuation_corrected"])
        headers = [*self.baseline.pet_headers, *self.baseline.ct_headers,
                   *self.followup.pet_headers, *self.followup.ct_headers]
        self.assertEqual(len({ds.StudyInstanceUID for ds in headers}), 2)
        self.assertEqual(len({ds.SeriesInstanceUID for ds in headers}), 4)
        self.assertEqual(len({ds.SOPInstanceUID for ds in headers}), 104)
        self.assertEqual(self.followup_dir, self.directory / "petfollow-demo-v2")
        self.assertEqual(self.followup.exam, self.original.exam)
        self.assertEqual(self.followup.pet_uids, self.original.pet_uids)

    def test_same_seed_yields_distinct_measurable_foci(self):
        sizes, peaks = [], []
        for study in (self.baseline, self.followup):
            plane = study.pet[10]
            self.assertGreater(plane[90, 104], 3 * plane[90, 118])
            mask = grow_region(plane, 104, 90, 0.65)
            peak, _ = suv_for_roi(study, mask, 10)
            self.assertIsNotNone(peak)
            sizes.append(mask.sum())
            peaks.append(peak)
        self.assertGreater(sizes[0], sizes[1])
        self.assertGreater(peaks[0], peaks[1])
        self.assertAlmostEqual(peaks[1], 9.34924368521668, places=6)

    def test_repeated_generation_reuses_files(self):
        before = {p: p.stat().st_mtime_ns for p in self.directory.rglob("*.dcm")}
        self.assertEqual(make_demo_pair(self.directory), (self.baseline_dir, self.followup_dir))
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.directory.rglob("*.dcm")}, before)

    def test_existing_different_content_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            existing = directory / self.baseline_dir.name / "PT" / "001.dcm"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"unrelated")
            with self.assertRaises(ValueError):
                make_demo_pair(directory)
            self.assertEqual(existing.read_bytes(), b"unrelated")


if __name__ == "__main__":
    unittest.main()
