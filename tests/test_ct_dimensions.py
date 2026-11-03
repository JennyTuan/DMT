import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))

from ct_dimensions import dimensions_for_roi


class CtDimensionsTests(unittest.TestCase):
    def test_same_plane_long_short_spd(self):
        header = Dataset()
        header.FrameOfReferenceUID = "2.25.1"
        header.ImagePositionPatient = [0, 0, 0]
        header.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        header.PixelSpacing = [1, 1]
        header.SliceThickness = 2
        study = SimpleNamespace(pet_headers=[header], ct_headers=[header],
                                pet=np.zeros((1, 12, 12)), ct=np.zeros((1, 12, 12)))
        mask = np.zeros((12, 12), bool)
        mask[2:5, 3:8] = True
        result, note = dimensions_for_roi(study, mask, 0)
        self.assertEqual(result["ct_index"], 0)
        self.assertGreater(result["long_mm"], result["short_mm"])
        self.assertAlmostEqual(result["spd_mm2"], result["long_mm"] * result["short_mm"])
        self.assertIn("估计", note)


if __name__ == "__main__":
    unittest.main()
