import sys
import unittest
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))

from mpr import reconstruct


class MprTests(unittest.TestCase):
    def setUp(self):
        self.headers = []
        for z in (0, 2, 4):
            ds = Dataset()
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [0, 0, z]
            ds.PixelSpacing = [2, 3]
            ds.Rows = 4
            ds.Columns = 5
            self.headers.append(ds)
        self.volume = np.arange(60, dtype=np.float32).reshape(3, 4, 5)

    def test_orthogonal_planes_and_mip_preserve_intensity(self):
        coronal, spacing = reconstruct(self.volume, self.headers, "coronal", 2)
        np.testing.assert_array_equal(coronal, self.volume[::-1, 2, :])
        self.assertEqual(spacing, (2, 3))
        sagittal, spacing = reconstruct(self.volume, self.headers, "sagittal", 1)
        np.testing.assert_array_equal(sagittal, self.volume[::-1, :, 1])
        self.assertEqual(spacing, (2, 2))
        mip, _ = reconstruct(self.volume, self.headers, "mip")
        np.testing.assert_array_equal(mip, self.volume.max(axis=1)[::-1])

    def test_irregular_spacing_rejects_reconstruction(self):
        self.headers[-1].ImagePositionPatient = [0, 0, 8]
        with self.assertRaisesRegex(ValueError, "间距不规则"):
            reconstruct(self.volume, self.headers, "mip")


if __name__ == "__main__":
    unittest.main()
