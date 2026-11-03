import sys
import unittest
from pathlib import Path

from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from geometry import ImageGeometry, alignment_offset


def headers(z_values, *, x=0.0, y=0.0):
    result = []
    for z in z_values:
        ds = Dataset()
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [x, y, z]
        ds.PixelSpacing = [2.0, 3.0]
        ds.Rows = 20
        ds.Columns = 30
        result.append(ds)
    return result


class GeometryTests(unittest.TestCase):
    def test_point_and_nearest_slice_use_patient_millimetres(self):
        g = ImageGeometry.from_headers(headers([-5, 0, 5]))
        self.assertEqual(g.pixel_to_patient(1, 4, 3), (12.0, 6.0, 0.0))
        self.assertEqual(g.nearest_index((12.0, 6.0, 4.0)), 2)

    def test_one_point_alignment_offsets_study_origin(self):
        base = ImageGeometry.from_headers(headers([-5, 0, 5]))
        current = ImageGeometry.from_headers(headers([15, 20, 25], x=8, y=-4))
        offset = alignment_offset(base, current, 1, (4, 3), 1, (4, 3))
        self.assertEqual(offset, (8.0, -4.0, 20.0))
        self.assertEqual(current.nearest_index(tuple(a+b for a,b in zip(base.pixel_to_patient(2, 4, 3), offset))), 2)

    def test_geometry_requires_consistent_orientation_and_positions(self):
        broken = headers([0, 5])
        del broken[1].ImagePositionPatient
        with self.assertRaisesRegex(ValueError, "空间位置"):
            ImageGeometry.from_headers(broken)


if __name__ == "__main__":
    unittest.main()
