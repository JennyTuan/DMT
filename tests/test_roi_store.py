import json
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))
from roi_store import StudyStore, grow_region


class RegionGrowingTests(unittest.TestCase):
    def test_seed_relative_threshold_is_inclusive_and_four_connected(self):
        plane = np.array([[60, 100, 59, 99],
                          [ 0,  61, 60,  0],
                          [80,   0, np.nan, np.inf]])
        want = [[True, True, False, False],
                [False, True, True, False],
                [False, False, False, False]]
        mask = grow_region(plane, 1, 0, 0.6)
        self.assertEqual(mask.dtype, np.bool_)
        np.testing.assert_array_equal(mask, want)
        mask[0, 1] = False
        np.testing.assert_array_equal(grow_region(plane, 1, 0, 0.6), want)

    def test_rejects_invalid_seed_and_threshold(self):
        plane = np.array([[0, -2, np.inf, np.nan, 1.]])
        for x, y, fraction in ((0, 0, .6), (1, 0, .6), (2, 0, .6), (3, 0, .6),
                               (-1, 0, .6), (5, 0, .6), (4, 1, .6), (4, 0, 0),
                               (4, 0, 1.1), (4, 0, float("nan"))):
            with self.subTest(x=x, y=y, fraction=fraction), self.assertRaises(ValueError):
                grow_region(plane, x, y, fraction)


class StudyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        example = ROOT / "schemas/v0/examples/demo_001_baseline.json"
        self.exam = json.loads(example.read_text(encoding="utf-8"))["exam"]
        self.manifest = self.root / "data/exams" / (self.exam["exam_id"] + ".json")
        self.mask = np.array([[False, True, False], [True, True, False]])
        self.args = dict(slice_index=3, sop_uid="1.2.840.13", seed=(1, 0),
                         fraction=.6, label="纵隔")

    def test_reopen_retains_proposal_and_reloadable_pixel_mask(self):
        store = StudyStore(self.root, self.exam)
        lesion_id = store.save_roi(self.mask, **self.args)
        bundle = json.loads(self.manifest.read_text(encoding="utf-8"))
        lesion, = bundle["lesions"]
        measurement, = bundle["measurements"]
        self.assertEqual(bundle["exam"], self.exam)
        self.assertEqual(lesion["exam_id"], self.exam["exam_id"])
        self.assertEqual((lesion["lesion_id"], measurement["lesion_id"]), (lesion_id, lesion_id))
        self.assertEqual((lesion["status"], measurement["state"]), ("proposed", "proposed"))
        for row in (lesion, measurement):
            event, = row["audit"]
            self.assertEqual((event["from"], event["to"]), ("draft", "proposed"))
        self.assertIsNone(measurement["suv_max"])
        self.assertIsNone(measurement["longest_diameter_mm"])
        self.assertFalse(measurement["edited"])
        self.assertTrue(measurement["roi_ref"].startswith("data/rois/"))
        reopened = StudyStore(self.root, self.exam)
        self.assertEqual(reopened.bundle, bundle)
        mask, info = reopened.load_roi(lesion_id)
        np.testing.assert_array_equal(mask, self.mask)
        self.assertEqual(mask.dtype, np.bool_)
        for key in ("slice_index", "sop_uid", "seed", "fraction"):
            self.assertEqual(info[key], self.args[key])

    def test_edit_preserves_old_version_and_status_audits(self):
        store = StudyStore(self.root, self.exam)
        lesion_id = store.save_roi(self.mask, **self.args)
        old = store.bundle["measurements"][0]
        initial = (self.root / old["roi_ref"]).read_bytes()
        edited = self.mask.copy()
        edited[0, 0] = True
        store.save_roi(edited, **{**self.args, "label": "纵隔 2"}, lesion_id=lesion_id, edited=True)
        measurement, = store.bundle["measurements"]
        lesion, = store.bundle["lesions"]
        self.assertEqual(lesion["label"], "纵隔 2")
        self.assertEqual(measurement["measurement_id"], old["measurement_id"])
        self.assertTrue(measurement["edited"])
        self.assertEqual(measurement["audit"], old["audit"])
        self.assertNotEqual(measurement["roi_ref"], old["roi_ref"])
        self.assertEqual((self.root / old["roi_ref"]).read_bytes(), initial)
        mask, info = StudyStore(self.root, self.exam).load_roi(lesion_id)
        np.testing.assert_array_equal(mask, edited)
        self.assertEqual(info["previous_ref"], old["roi_ref"])
        self.assertEqual(info["actor"], "user")
        self.assertTrue(info["operator"])
        self.assertIsNotNone(datetime.fromisoformat(info["at"]).tzinfo)

    def test_stale_session_cannot_replace_newer_bundle(self):
        first = StudyStore(self.root, self.exam)
        stale = StudyStore(self.root, self.exam)
        lesion_id = first.save_roi(self.mask, **self.args)
        with self.assertRaisesRegex(ValueError, "重新"):
            stale.save_roi(self.mask, **self.args)
        reopened = StudyStore(self.root, self.exam)
        self.assertEqual([row["lesion_id"] for row in reopened.bundle["lesions"]], [lesion_id])

    def test_reimport_cannot_silently_change_correction_or_source(self):
        StudyStore(self.root, self.exam)
        for key in ("attenuation_corrected", "is_synthetic"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                StudyStore(self.root, {**self.exam, key: not self.exam[key]})

    def test_second_writer_is_refused_while_first_commits(self):
        first = StudyStore(self.root, self.exam)
        second = StudyStore(self.root, self.exam)
        writing, resume = Event(), Event()
        replace = os.replace

        def hold_first_commit(src, dst):
            if Path(dst) == self.manifest and not writing.is_set():
                writing.set()
                self.assertTrue(resume.wait(timeout=5))
            return replace(src, dst)

        with patch("roi_store.os.replace", side_effect=hold_first_commit), ThreadPoolExecutor(1) as pool:
            commit = pool.submit(first.save_roi, self.mask, **self.args)
            try:
                self.assertTrue(writing.wait(timeout=5))
                with self.assertRaisesRegex(ValueError, "重新"):
                    second.save_roi(self.mask, **self.args)
            finally:
                resume.set()
            lesion_id = commit.result(timeout=5)
        reopened = StudyStore(self.root, self.exam)
        self.assertEqual([row["lesion_id"] for row in reopened.bundle["lesions"]], [lesion_id])

    def test_failed_manifest_write_keeps_last_committed_mask(self):
        store = StudyStore(self.root, self.exam)
        lesion_id = store.save_roi(self.mask, **self.args)
        original = self.manifest.read_bytes()
        replace = os.replace

        def fail_manifest_write(src, dst):
            if Path(dst) == self.manifest:
                raise PermissionError("检查文件暂时被占用")
            return replace(src, dst)

        edited = ~self.mask
        with patch("roi_store.os.replace", side_effect=fail_manifest_write), self.assertRaises(OSError):
            store.save_roi(edited, **self.args, lesion_id=lesion_id, edited=True)
        self.assertEqual(self.manifest.read_bytes(), original)
        np.testing.assert_array_equal(store.load_roi(lesion_id)[0], self.mask)
        versions = list((self.root / "data/rois").rglob("*.json"))
        self.assertEqual(len(versions), 1)

    def test_rejects_unsafe_ids_and_invalid_exam_before_write(self):
        for changes in ({"exam_id": "../escape"}, {"exam_id": "CON"},
                        {"study_datetime": "2026-02-31"}, {"prototype_banner": "test"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                StudyStore(self.root, {**self.exam, **changes})
        self.assertFalse(self.manifest.exists())
        store = StudyStore(self.root, self.exam)
        for mask, args in ((np.zeros((2, 3), bool), self.args),
                           (self.mask, {**self.args, "lesion_id": "../bad"}),
                           (self.mask, {**self.args, "slice_index": -1}),
                           (self.mask, {**self.args, "seed": (3, 0)})):
            with self.subTest(args=args), self.assertRaises(ValueError):
                store.save_roi(mask, **args)
        self.assertFalse(store.bundle["lesions"])

    def test_load_ref_cannot_leave_study_roi_directory(self):
        store = StudyStore(self.root, self.exam)
        lesion_id = store.save_roi(self.mask, **self.args)
        bundle = json.loads(self.manifest.read_text(encoding="utf-8"))
        bundle["measurements"][0]["roi_ref"] = "data/exams/" + self.manifest.name
        self.manifest.write_text(json.dumps(bundle), encoding="utf-8")
        with self.assertRaises(ValueError):
            StudyStore(self.root, self.exam).load_roi(lesion_id)

    def test_damaged_layer_reference_is_rejected_before_display(self):
        store = StudyStore(self.root, self.exam)
        lesion_id = store.save_roi(self.mask, **self.args)
        roi = self.root / store.bundle["measurements"][0]["roi_ref"]
        record = json.loads(roi.read_text(encoding="utf-8"))
        for changes in ({"slice_index": -1}, {"sop_uid": ""}, {"pet_series_ref": "other"},
                        {"mask_bits": ""}):
            with self.subTest(changes=changes):
                roi.write_text(json.dumps({**record, **changes}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    store.load_roi(lesion_id)


if __name__ == "__main__":
    unittest.main()
