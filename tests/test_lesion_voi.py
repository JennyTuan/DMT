import sys
import unittest
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from geometry import ImageGeometry
from lesion_voi import grow_lesion


class LesionVoiTests(unittest.TestCase):
    def setUp(self):
        headers = []
        for z in range(-20, 22, 2):
            ds = Dataset()
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [-40, -40, z]
            ds.PixelSpacing = [2, 2]
            ds.Rows = ds.Columns = 41
            headers.append(ds)
        self.geometry = ImageGeometry.from_headers(headers)
        self.volume = np.ones((21, 41, 41), dtype=np.float32)
        zz, yy, xx = np.ogrid[-20:22:2, -40:42:2, -40:42:2]
        lesion = (zz ** 2 + xx ** 2 + yy ** 2) <= 6 ** 2
        self.volume[lesion] = 10
        self.volume[10, 34:37, 34:37] = 50  # disconnected physiologic uptake

    def test_connected_three_dimensional_threshold_excludes_other_hotspot(self):
        mask, detail = grow_lesion(self.volume, self.geometry, 10, 20, 20)
        self.assertGreater(np.count_nonzero(mask.any(axis=(1, 2))), 1)
        self.assertEqual(detail["maximum_raw"], 10)
        self.assertEqual(detail["threshold_raw"], 4.1)
        self.assertFalse(mask[10, 35, 35])
        self.assertEqual(detail["maximum_mm"][2], -6)

    def test_boundary_and_background_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "正的 PET 值|边界"):
            grow_lesion(np.zeros_like(self.volume), self.geometry, 10, 20, 20)
        with self.assertRaisesRegex(ValueError, "边界"):
            grow_lesion(np.full_like(self.volume, 10), self.geometry, 10, 20, 20)


if __name__ == "__main__":
    unittest.main()
