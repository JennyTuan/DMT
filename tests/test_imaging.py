"""Exercise Pack 02 through written DICOM files, including a non-demo study."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pydicom
from jsonschema import Draft202012Validator, FormatChecker
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, PositronEmissionTomographyImageStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/petfollow-lymphoma"), str(ROOT / "fixtures")]


def write_plane(path, modality, number, **changes):
    is_pet = modality == "PT"
    series = "2.25.1001" if is_pet else "2.25.1002"
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, preamble=b"\0" * 128, file_meta=meta)
    ds.SOPClassUID = PositronEmissionTomographyImageStorage if is_pet else CTImageStorage
    ds.SOPInstanceUID = f"{series}.{number}"
    ds.StudyInstanceUID = "2.25.1000"
    ds.SeriesInstanceUID = series
    ds.PatientName = "Example^Private"
    ds.PatientID = "local-private-id"
    ds.Modality = modality
    ds.StudyDate = "20240523"
    ds.StudyTime = "230405.5"
    ds.TimezoneOffsetFromUTC = "-0330"
    ds.InstanceNumber = number
    # On this sagittal stack, physical order is descending instance number.
    ds.ImageOrientationPatient = [0, 1, 0, 0, 0, 1]
    ds.ImagePositionPatient = [-4 * number, 0, 0]
    ds.PixelSpacing = [2, 3]
    ds.Rows, ds.Columns = 2, 3
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation = 1
    ds.PixelData = np.full((2, 3), number * 10, dtype="<i2").tobytes()
    ds.RescaleSlope, ds.RescaleIntercept = number, -5
    if is_pet:
        ds.CorrectedImage = ["DECY", "ATTN"]
    for key, value in changes.items():
        if value is None:
            if key in ds:
                del ds[key]
        else:
            setattr(ds, key, value)
    ds.save_as(path, enforce_file_format=True)


class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.folder = Path(self.scratch.name)

    def pair(self, **pet_changes):
        write_plane(self.folder / "one", "PT", 1, **pet_changes)
        write_plane(self.folder / "two", "CT", 1)

    def load(self):
        from imaging import load_study
        return load_study(self.folder)

    def test_sorted_rescaled_private_and_schema_valid(self):
        self.pair()
        write_plane(self.folder / "three", "PT", 2)
        study = self.load()
        schema = json.loads((ROOT / "schemas/v0/exam.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(study.exam)
        self.assertEqual(study.pet.dtype, np.float32)
        np.testing.assert_equal(study.pet[:, 0, 0], [35, 5])
        self.assertEqual(study.ct.shape, (1, 2, 3))
        self.assertEqual(study.pet_spacing, (2, 3))
        self.assertFalse(study.pet_inverted)
        self.assertEqual(len(set(study.pet_uids)), 2)
        serialized = json.dumps([study.exam, study.pet_uids])
        for private in ("Example", "local-private-id", "2.25.100", self.folder.name):
            self.assertNotIn(private, serialized)
        self.assertTrue(study.exam["study_datetime"].startswith("2024-05-23T23:04:05.5"))
        self.assertTrue(study.exam["study_datetime"].endswith("-03:30"))
        self.assertIs(study.exam["attenuation_corrected"], True)
        self.assertIs(study.exam["is_synthetic"], False)
        (self.folder / "one").rename(self.folder / "renamed")
        reopened = self.load()
        self.assertEqual(study.exam, reopened.exam)
        self.assertEqual(study.pet_uids, reopened.pet_uids)

    def test_correction_unknown_or_uncorrected_is_never_confirmed(self):
        for fields, label in [
            ({"CorrectedImage": None}, "未知"),
            ({"CorrectedImage": ["DECY", "SCAT"]}, "未校正"),
            ({"CorrectedImage": ["MOTN", "PMOT"]}, "未校正"),
            ({"CorrectedImage": ["NONE", "ATTN"]}, "未知"),
            ({"AttenuationCorrected": "NO"}, "未知"),  # contradicts ATTN
        ]:
            with self.subTest(fields=fields):
                self.pair(**fields)
                study = self.load()
                self.assertIs(study.exam["attenuation_corrected"], False)
                self.assertIn(label, study.correction_label)
        self.pair()
        write_plane(self.folder / "three", "PT", 2, CorrectedImage=None)
        self.assertIn("未知", self.load().correction_label)

    def test_cannot_mix_studies_patients_series_or_duplicate_planes(self):
        self.pair()
        for changes, message in [
            ({"StudyInstanceUID": "2.25.99"}, "检查"),
            ({"PatientID": "another-patient"}, "患者"),
            ({"PatientName": "Different^Patient"}, "患者"),
            ({"SeriesInstanceUID": "2.25.99"}, "序列"),
            ({"ImagePositionPatient": [-4, 0, 0]}, "位置"),
            ({"ImageOrientationPatient": [1, 0, 0, 0, 1, 0]}, "方向"),
            ({"SOPInstanceUID": "2.25.1001.1"}, "实例"),
        ]:
            with self.subTest(changes=changes):
                write_plane(self.folder / "three", "PT", 2, **changes)
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_local_time_fallback_and_independent_display_polarity(self):
        for modality, name, photo in [("CT", "ct", "MONOCHROME1"), ("PT", "pet", "MONOCHROME2")]:
            write_plane(self.folder / name, modality, 1, TimezoneOffsetFromUTC=None,
                        ImagePositionPatient=None, ImageOrientationPatient=None,
                        PhotometricInterpretation=photo)
        study = self.load()
        self.assertEqual(datetime.fromisoformat(study.exam["study_datetime"]),
                         datetime(2024, 5, 23, 23, 4, 5, 500000).astimezone())
        self.assertTrue(study.ct_inverted)
        self.assertFalse(study.pet_inverted)
        np.testing.assert_equal(study.ct, 5)

    def test_mixed_temporal_frames_need_one_static_stack(self):
        self.pair(TemporalPositionIdentifier=1)
        write_plane(self.folder / "three", "PT", 2, TemporalPositionIdentifier=2)
        with self.assertRaisesRegex(ValueError, "时相"):
            self.load()

    def test_missing_pair_time_or_unsupported_frames_cannot_pass(self):
        write_plane(self.folder / "two", "CT", 1)
        with self.assertRaisesRegex(ValueError, "PET"):
            self.load()
        self.pair(NumberOfFrames=2)
        with self.assertRaisesRegex(ValueError, "帧"):
            self.load()
        self.pair()
        for modality, name in [("CT", "two"), ("PT", "one")]:
            write_plane(self.folder / name, modality, 1, StudyDate=None)
        with self.assertRaisesRegex(ValueError, "日期"):
            self.load()

    def test_synthetic_demo_reproducible_and_seed_visible(self):
        from make_demo import make_demo
        make_demo(self.folder)
        study = self.load()
        self.assertIs(study.exam["is_synthetic"], True)
        self.assertEqual(study.pet.shape, (21, 192, 192))
        self.assertEqual(study.pet_spacing, (2, 2))
        self.assertGreater(study.pet[10, 90, 104], 3 * study.pet[10, 90, 118])
        make_demo(self.folder)
        reopened = self.load()
        self.assertEqual(study.exam, reopened.exam)
        np.testing.assert_array_equal(study.pet, reopened.pet)


if __name__ == "__main__":
    unittest.main()
