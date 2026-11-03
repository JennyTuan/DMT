import sys
import unittest
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from geometry import ImageGeometry
from reference_voi import sample_reference_voxels, reference_outline


class ReferenceVoiTests(unittest.TestCase):
    def setUp(self):
        headers = []
        for z in range(-20, 21, 4):
            ds = Dataset()
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [-20, -20, z]
            ds.PixelSpacing = [2, 2]
            ds.Rows = ds.Columns = 21
            headers.append(ds)
        self.geometry = ImageGeometry.from_headers(headers)
        self.volume = np.full((11, 21, 21), 7.0, dtype=np.float32)

    def test_liver_sphere_samples_three_dimensions(self):
        values = sample_reference_voxels(self.volume, self.geometry, (0, 0, 0), "liver")
        self.assertGreater(len(values), 100)
        self.assertLess(len(values), self.volume.size)
        self.assertEqual(float(values.mean()), 7.0)

    def test_blood_pool_cylinder_and_edge_rejection(self):
        values = sample_reference_voxels(self.volume, self.geometry, (0, 0, 0), "blood_pool")
        self.assertGreater(len(values), 20)
        self.assertLess(len(values), len(sample_reference_voxels(self.volume, self.geometry, (0, 0, 0), "liver")))
        with self.assertRaisesRegex(ValueError, "边界"):
            sample_reference_voxels(self.volume, self.geometry, (19, 0, 0), "liver")

    def test_outline_tracks_3d_intersection(self):
        x, y, rx, ry = reference_outline(self.geometry, (0, 0, 0), "liver", 5)
        self.assertEqual((x, y), (10, 10))
        self.assertEqual((rx, ry), (7.5, 7.5))
        self.assertIsNone(reference_outline(self.geometry, (0, 0, 0), "liver", 0))


if __name__ == "__main__":
    unittest.main()
