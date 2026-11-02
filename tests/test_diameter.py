import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from pydicom.dataset import Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))
from diameter import diameter_for_roi


def plane(origin, spacing=(1, 1), orientation=(1, 0, 0, 0, 1, 0)):
    header = Dataset()
    header.FrameOfReferenceUID = "2.25.789"
    header.ImagePositionPatient = list(origin)
    header.ImageOrientationPatient = list(orientation)
    header.PixelSpacing = list(spacing)
    header.SliceThickness = 2
    return header


def study_with(pet, ct):
    return SimpleNamespace(pet_headers=[pet], ct_headers=ct, pet=np.zeros((1, 8, 8)),
                           ct=np.zeros((len(ct), 10, 15)))


class DiameterTests(unittest.TestCase):
    def setUp(self):
        self.study = study_with(plane((0, 0, 0)), [plane((0, 0, 0))])
        self.mask = np.zeros((8, 8), bool)
        self.mask[1:3, 1:3] = True

    def test_rotated_anisotropic_ct_grid_and_nearest_physical_slice(self):
        study = study_with(
            plane((0, 0, 4), spacing=(3, 2)),
            [plane((10.25, -0.25, z), (1.5, 1), (0, 1, 0, -1, 0, 0))
             for z in (0, 4.4, 8)],
        )
        # PET footprint is 4 x 6 mm. Inside it, CT centers span x=1.25..4.25,
        # y=1.75..6.75 mm. The two opposite CT centers are sqrt(34) mm apart.
        value, note = diameter_for_roi(study, self.mask, 0)
        self.assertAlmostEqual(value, math.sqrt(34))
        self.assertIn("投影", note)
        self.assertRegex(note, r"CT\s*第\s*2\s*层")

    def test_sagittal_flipped_ct_and_cross_shaped_roi(self):
        study = study_with(
            plane((3, 0, 0), orientation=(0, 1, 0, 0, 0, 1)),
            [plane((x, 8, 0), orientation=(0, -1, 0, 0, 0, 1)) for x in (6, 3, 0)],
        )
        self.mask[:] = False
        self.mask[3, 1:6] = True
        self.mask[1:6, 3] = True
        value, note = diameter_for_roi(study, self.mask, 0)
        self.assertAlmostEqual(value, 4)  # Bounding-box corners are outside the ROI.
        self.assertRegex(note, r"CT\s*第\s*2\s*层")

    def test_reference_and_geometry_required_even_when_image_sizes_match(self):
        for modality, attr, replacement, reason in [
            ("pet", "FrameOfReferenceUID", None, "参考系"),
            ("ct", "FrameOfReferenceUID", "2.25.790", "参考系"),
            ("pet", "ImageOrientationPatient", None, "方向"),
            ("ct", "ImagePositionPatient", None, "位置"),
            ("pet", "PixelSpacing", [0, 1], "间距"),
            ("ct", "PixelSpacing", None, "间距"),
            ("pet", "ImageOrientationPatient", [1, 0, 0, 1, 0, 0], "方向"),
            ("ct", "ImageOrientationPatient", [1, 0, 0, 0, 0, 1], "层面"),
        ]:
            with self.subTest(modality=modality, attr=attr):
                study = study_with(plane((0, 0, 0)), [plane((0, 0, 0))])
                header = getattr(study, modality + "_headers")[0]
                if replacement is None:
                    delattr(header, attr)
                else:
                    setattr(header, attr, replacement)
                value, note = diameter_for_roi(study, self.mask, 0)
                self.assertIsNone(value)
                self.assertIn(reason, note)

    def test_slice_gap_or_outside_scan_cannot_use_closest_slice_anyway(self):
        for ct_positions in [(-10, 10), (2,), (-4, -2)]:
            with self.subTest(positions=ct_positions):
                study = study_with(plane((0, 0, 0)),
                                   [plane((0, 0, z)) for z in ct_positions])
                value, note = diameter_for_roi(study, self.mask, 0)
                self.assertIsNone(value)
                self.assertIn("覆盖", note)

    def test_missing_thickness_only_supports_coincident_plane(self):
        del self.study.ct_headers[0].SliceThickness
        self.assertAlmostEqual(diameter_for_roi(self.study, self.mask, 0)[0], math.sqrt(2))
        self.study.ct_headers[0].ImagePositionPatient = [0, 0, 0.8]
        value, note = diameter_for_roi(self.study, self.mask, 0)
        self.assertIsNone(value)
        self.assertIn("层厚", note)

    def test_even_a_partly_clipped_pixel_footprint_refuses_diameter(self):
        self.study.ct_headers[0].ImagePositionPatient = [1.05, 0, 0]
        value, note = diameter_for_roi(self.study, self.mask, 0)
        self.assertIsNone(value)
        self.assertIn("视野", note)

    def test_coarse_ct_sampling_with_only_one_center_cannot_define_caliper(self):
        self.study.ct_headers[0].PixelSpacing = [3, 3]
        self.study.ct_headers[0].ImagePositionPatient = [2, 2, 0]
        value, note = diameter_for_roi(self.study, self.mask, 0)
        self.assertIsNone(value)
        self.assertIn("像素", note)

    def test_bad_roi_or_unavailable_header_cannot_use_a_different_slice(self):
        for mask, index in [(self.mask[:3], 0), (np.zeros((8, 8), bool), 0), (self.mask, -1)]:
            with self.subTest(shape=mask.shape, index=index):
                self.assertIsNone(diameter_for_roi(self.study, mask, index)[0])
        self.study.ct_headers.clear()
        self.assertIsNone(diameter_for_roi(self.study, self.mask, 0)[0])


if __name__ == "__main__":
    unittest.main()
