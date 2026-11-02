"""Pack 03 PET measurements through classic single-frame DICOM import."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from pydicom.dataset import Dataset

from test_imaging import write_plane
from imaging import load_study
from make_demo import make_demo


class SUVTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        write_plane(self.folder / "ct", "CT", 1)
        self.mask = np.array([[True, True, False], [False, False, False]])
        self.pixels = np.array([[20, 1000, 9000], [0, 0, 0]], dtype="<i2").tobytes()

    def pet(self, number=1, **fields):
        fields = dict({"Units": "GML", "RescaleSlope": 0.01, "RescaleIntercept": 0,
                       "PixelData": self.pixels}, **fields)
        write_plane(self.folder / f"p{number}", "PT", number, **fields)

    def result(self, index=0):
        from suv import suv_for_roi
        return suv_for_roi(load_study(self.folder), self.mask, index)

    def bqml(self, *, number=1, tracer=None, **changes):
        isotope = Dataset()
        isotope.RadionuclideTotalDose = 100_000_000  # Bq at administration
        isotope.RadionuclideHalfLife = 3600           # seconds, artificial isotope
        isotope.RadiopharmaceuticalStartDateTime = "20240522235500-0330"
        for key, value in (tracer or {}).items():
            if value is None:
                del isotope[key]
            else:
                setattr(isotope, key, value)
        fields = dict(Units="BQML", RescaleSlope=2, PatientWeight=50, DecayCorrection="START",
                      AcquisitionDate="20240523", AcquisitionTime="005500",
                      RadiopharmaceuticalInformationSequence=[isotope])
        self.pet(number, **dict(fields, **changes))

    def test_headers_follow_volume_order_without_pixels(self):
        self.pet(1)
        self.pet(2)
        write_plane(self.folder / "ct2", "CT", 2)
        study = load_study(self.folder)
        self.assertTrue(hasattr(study, "pet_headers") and hasattr(study, "ct_headers"))
        for headers in (study.pet_headers, study.ct_headers):
            self.assertEqual([int(ds.InstanceNumber) for ds in headers], [2, 1])
            self.assertTrue(all("PixelData" not in ds for ds in headers))

    def test_gml_uses_roi_only_and_the_rescale_of_that_slice_once(self):
        self.pet(1, SUVType="BW")
        self.pet(2, RescaleSlope=0.02)  # absent SUVType implies BW
        self.assertAlmostEqual(self.result(0)[0], 20)
        self.assertAlmostEqual(self.result(1)[0], 10)

    def test_bqml_at_start_and_administration_use_different_dose_references(self):
        self.bqml()
        # ROI peak = 2000 Bq/ml. After one half-life, 50 MBq remains.
        self.assertAlmostEqual(self.result()[0], 2)
        # The same instant in UTC, encoded as a DT rather than DA/TM.
        self.bqml(AcquisitionDate=None, AcquisitionTime=None,
                  AcquisitionDateTime="20240523042500+0000")
        self.assertAlmostEqual(self.result()[0], 2)
        self.bqml(DecayCorrection="ADMIN", AcquisitionTime=None, AcquisitionDate=None,
                  tracer={"RadionuclideHalfLife": None, "RadiopharmaceuticalStartDateTime": None})
        self.assertAlmostEqual(self.result()[0], 1)

    def test_unknown_and_unattenuated_require_the_exact_review_note(self):
        for corrected in (None, ["DECY"], ["NONE", "ATTN"]):
            with self.subTest(corrected=corrected):
                self.pet(CorrectedImage=corrected)
                self.assertEqual(self.result(), (None, "缺/未衰减校正，SUV 仅供复核"))

    def test_missing_or_unsupported_calibration_never_uses_raw_counts(self):
        for fields in (dict(Units="CNTS"), dict(Units=None), dict(SUVType="LBM"),
                       dict(SUVType=""), dict(CorrectedImage=["ATTN"]),
                       dict(DecayCorrection="NONE"), dict(DecayCorrection="OTHER"),
                       dict(RescaleSlope=None, RescaleIntercept=None)):
            with self.subTest(fields=fields):
                self.pet(**fields)
                value, note = self.result()
                self.assertIsNone(value)
                self.assertTrue(note)

    def test_missing_or_ambiguous_bqml_inputs_require_review(self):
        for fields in (dict(PatientWeight=None), dict(PatientWeight=-5),
                       dict(SUVType="LBM"),
                       dict(DecayCorrection=None), dict(DecayCorrection="NONE"),
                       dict(AcquisitionDate=None), dict(AcquisitionTime=None),
                       dict(AcquisitionDateTime="20240523220405"),
                       dict(RadiopharmaceuticalInformationSequence=[]),
                       dict(RadiopharmaceuticalInformationSequence=[Dataset(), Dataset()]),
                       dict(tracer={"RadionuclideTotalDose": 0}),
                       dict(tracer={"RadionuclideTotalDose": None}),
                       dict(tracer={"RadionuclideHalfLife": None}),
                       dict(tracer={"RadiopharmaceuticalStartDateTime": "20240523010500"}),
                       dict(tracer={"RadiopharmaceuticalStartDateTime": None,
                                    "RadiopharmaceuticalStartTime": "235500"}),
                       dict(tracer={"RadiopharmaceuticalStartDateTime": "20240522"})):
            with self.subTest(fields=fields):
                self.bqml(**fields)
                value, note = self.result()
                self.assertIsNone(value)
                self.assertTrue(note)

    def test_inconsistent_or_incomplete_series_cannot_lend_another_slice_its_calibration(self):
        self.bqml()
        for fields in (dict(Units=None), dict(Units="GML"), dict(PatientWeight=None),
                       dict(PatientWeight=70), dict(DecayCorrection="ADMIN"),
                       dict(tracer={"RadionuclideTotalDose": 200_000_000}),
                       dict(AcquisitionTime="010500")):
            with self.subTest(fields=fields):
                self.bqml(number=2, **fields)
                for index in (0, 1):
                    self.assertIsNone(self.result(index)[0])

    def test_same_dose_for_two_distinct_administrations_is_still_ambiguous(self):
        self.bqml(DecayCorrection="ADMIN",
                  tracer={"RadiopharmaceuticalAdministrationEventUID": "2.25.101"})
        self.bqml(number=2, DecayCorrection="ADMIN",
                  tracer={"RadiopharmaceuticalAdministrationEventUID": "2.25.102"})
        self.assertIsNone(self.result()[0])

    def test_padding_in_the_roi_cannot_be_reported_as_an_uptake_peak(self):
        self.pet(PixelPaddingValue=990, PixelPaddingRangeLimit=1000)
        self.assertIsNone(self.result()[0])
        self.pet(PixelPaddingValue=-1)
        self.assertEqual(self.result()[0], 10)

    def test_invalid_roi_or_index_never_returns_a_number(self):
        from suv import suv_for_roi
        self.pet()
        study = load_study(self.folder)
        for mask, index in ((self.mask, -1), (self.mask, 1), (self.mask, False),
                            (~np.ones_like(self.mask), 0), (self.mask[:1], 0),
                            (self.mask.astype(float), 0)):
            with self.subTest(mask=mask, index=index):
                self.assertIsNone(suv_for_roi(study, mask, index)[0])

    def test_v1_counts_and_v2_quantitative_studies_have_separate_identities(self):
        from roi_store import grow_region
        from suv import suv_for_roi
        dest = self.folder / "fixtures"
        make_demo(dest)
        make_demo(dest, quantitative=True)
        v1 = load_study(dest / "petfollow-demo-v1")
        v2 = load_study(dest / "petfollow-demo-v2")
        self.assertNotEqual(v1.exam["exam_id"], v2.exam["exam_id"])
        self.assertFalse(set(v1.pet_uids) & set(v2.pet_uids))
        mask1 = grow_region(v1.pet[10], 104, 90, 0.65)
        mask2 = grow_region(v2.pet[10], 104, 90, 0.65)
        np.testing.assert_array_equal(mask1, mask2)
        self.assertIsNone(suv_for_roi(v1, mask1, 10)[0])
        self.assertAlmostEqual(suv_for_roi(v2, mask2, 10)[0], 9.34924368521668, places=6)


if __name__ == "__main__":
    unittest.main()
