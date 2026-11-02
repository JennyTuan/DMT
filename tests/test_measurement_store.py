import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))
from roi_store import StudyStore


FIELDS = ("suv_max", "longest_diameter_mm")


def measure(mask, slice_index, sop_uid):
    if (slice_index, sop_uid) != (2, "1.2.3"):
        raise ValueError("原 PET 实例与层面不匹配")
    return ({"suv_max": float(mask.sum()), "longest_diameter_mm": 10.0},
            {"suv_max": "示意 SUV", "longest_diameter_mm": "示意投影长度"})


class MeasurementStoreTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        example = ROOT / "schemas/v0/examples/demo_001_baseline.json"
        self.exam = json.loads(example.read_text(encoding="utf-8"))["exam"]
        self.mask = np.array([[True, False], [True, True]])
        self.roi = dict(slice_index=2, sop_uid="1.2.3", seed=(0, 0), fraction=.6, label="纵隔")

    def open(self, callback=measure):
        return StudyStore(self.root, self.exam, measure=callback)

    def test_save_edit_both_fields_then_recalculate_with_each_roi_revision(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        first, = store.bundle["measurements"]
        self.assertEqual((first["suv_max"], first["longest_diameter_mm"], first["state"]),
                         (3., 10., "proposed"))
        self.assertFalse(first["edited"])
        store.edit_value(lesion_id, "suv_max", 6.5, "人工核对 SUV")
        store.edit_value(lesion_id, "longest_diameter_mm", 10., "确认测径")
        store = self.open()
        revised, = store.bundle["measurements"]
        self.assertTrue(revised["edited"])
        self.assertEqual(revised["suv_max"], 6.5)
        store.save_roi(~self.mask, lesion_id=lesion_id, **self.roi)
        current, = self.open().bundle["measurements"]
        self.assertEqual(current["audit"], first["audit"])
        self.assertEqual(current["suv_max"], 1.)
        self.assertNotEqual(first["roi_ref"], current["roi_ref"])
        events = self.open().value_history(lesion_id)
        self.assertEqual([(e["field"], e["actor"], e["from"], e["to"]) for e in events], [
            (FIELDS[0], "system", None, 3.), (FIELDS[1], "system", None, 10.),
            (FIELDS[0], "user", 3., 6.5), (FIELDS[1], "user", 10., 10.),
            (FIELDS[0], "system", 6.5, 1.), (FIELDS[1], "system", 10., 10.),
        ])
        self.assertEqual([e["roi_ref"] for e in events], [first["roi_ref"]]*4 + [current["roi_ref"]]*2)
        self.assertEqual(events[2]["note"], "人工核对 SUV")
        self.assertTrue(all(e["note"] and datetime.fromisoformat(e["at"]).tzinfo for e in events))

    def test_review_gate_is_preserved_through_human_edits_and_roi_recalculation(self):
        self.exam["attenuation_corrected"] = False
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        finding, = store.bundle["measurements"]
        self.assertEqual(finding["state"], "needs_review")
        self.assertIsNone(finding["suv_max"])
        self.assertIn("缺/未衰减校正，SUV 仅供复核", finding["audit"][1]["note"])
        self.assertEqual((finding["audit"][1]["actor"], finding["audit"][1]["from"],
                          finding["audit"][1]["to"]), ("system", "proposed", "needs_review"))
        store.edit_value(lesion_id, FIELDS[0], 9, "人工复核示意数值")
        store.save_roi(self.mask, lesion_id=lesion_id, **self.roi)
        self.assertEqual(self.open().bundle["measurements"][0]["audit"], finding["audit"])
        self.assertEqual(len(self.open().value_history(lesion_id)), 5)

    def test_legacy_reopen_backfills_only_missing_fields_and_preserves_manual_numbers(self):
        legacy = StudyStore(self.root, self.exam)
        first = legacy.save_roi(self.mask, **self.roi, edited=True)
        second = legacy.save_roi(~self.mask, **self.roi)
        bundle = legacy.bundle
        bundle["measurements"][1].update(edited=True, suv_max=8.5)
        legacy.path.write_text(json.dumps(bundle), encoding="utf-8")
        store = self.open()
        self.assertEqual(store.bundle["measurements"][0]["suv_max"], 3.)
        self.assertTrue(store.bundle["measurements"][0]["edited"])
        self.assertEqual(store.bundle["measurements"][1]["suv_max"], 8.5)
        self.assertEqual(store.bundle["measurements"][1]["longest_diameter_mm"], 10.)
        self.assertEqual([e["field"] for e in store.value_history(first)], list(FIELDS))
        self.assertEqual([e["field"] for e in store.value_history(second)], [FIELDS[1]])
        reopened = self.open()
        self.assertEqual(reopened.value_history(first), store.value_history(first))
        self.assertEqual(reopened.value_history(second), store.value_history(second))

    def test_missing_corrupt_or_wrong_sop_on_backfill_is_reviewable_and_idempotent(self):
        legacy = StudyStore(self.root, self.exam)
        ids = [legacy.save_roi(self.mask, **self.roi) for _ in range(3)]
        paths = [self.root / m["roi_ref"] for m in legacy.bundle["measurements"]]
        paths[0].unlink()
        paths[1].write_text("damaged", encoding="utf-8")
        record = json.loads(paths[2].read_text(encoding="utf-8"))
        paths[2].write_text(json.dumps({**record, "sop_uid":"2.3.4"}), encoding="utf-8")
        store = self.open()
        for lesion_id, m in zip(ids, store.bundle["measurements"]):
            self.assertEqual((m["state"], m[FIELDS[0]], m[FIELDS[1]]), ("needs_review", None, None))
            self.assertEqual(len(m["audit"]), 2)
            history = store.value_history(lesion_id)
            self.assertEqual([e["field"] for e in history], list(FIELDS))
            self.assertTrue(all(e["to"] is None and e["note"] for e in history))
            self.assertEqual(self.open().value_history(lesion_id), history)
        self.assertIn("实例", store.bundle["measurements"][2]["audit"][1]["note"])

    def test_missing_one_calculation_keeps_other_and_records_reason(self):
        def partial(*_):
            return ({FIELDS[0]: 2.5, FIELDS[1]: None}, {FIELDS[0]: "示意 SUV", FIELDS[1]: "CT 间距缺失"})

        store = self.open(partial)
        lesion_id = store.save_roi(self.mask, **self.roi)
        m, = store.bundle["measurements"]
        self.assertEqual((m["state"], m[FIELDS[0]], m[FIELDS[1]]), ("needs_review", 2.5, None))
        self.assertIn("CT 间距缺失", m["audit"][1]["note"])
        self.assertEqual(len(self.open(partial).value_history(lesion_id)), 2)

    def test_partial_legacy_manual_history_does_not_skip_other_fields_backfill(self):
        legacy = StudyStore(self.root, self.exam)
        lesion_id = legacy.save_roi(self.mask, **self.roi)
        legacy.edit_value(lesion_id, FIELDS[0], 5.25, "人工核对")
        reopened = self.open()
        m, = reopened.bundle["measurements"]
        self.assertEqual((m[FIELDS[0]], m[FIELDS[1]]), (5.25, 10.))
        self.assertEqual([(e["field"], e["actor"]) for e in reopened.value_history(lesion_id)],
                         [(FIELDS[0], "user"), (FIELDS[1], "system")])

    def test_missing_stored_roi_after_manual_edit_retains_human_value_and_invalidates_automatic_one(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        store.edit_value(lesion_id, FIELDS[0], 4., "人工核对")
        (self.root / store.bundle["measurements"][0]["roi_ref"]).unlink()
        reopened = self.open()
        m, = reopened.bundle["measurements"]
        self.assertEqual((m["state"], m[FIELDS[0]], m[FIELDS[1]]), ("needs_review", 4., None))
        events = reopened.value_history(lesion_id)
        self.assertEqual((len(events), events[-1]["from"], events[-1]["to"]), (5, 10., None))
        self.assertEqual((events[-2]["from"], events[-2]["to"]), (4., 4.))
        self.assertIn("保留人工", events[-2]["note"])
        self.assertEqual(self.open().value_history(lesion_id), events)

    def test_current_pet_source_mismatch_is_gated_without_recalculating_manual_values(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        store.edit_value(lesion_id, FIELDS[0], 4., "人工核对")

        def measure_on_changed_source(mask, index, uid):
            if mask.shape == (2, 2) and (index, uid) == (2, "1.2.3"):
                raise ValueError("本次导入的 PET 实例不匹配")
            return measure(mask, index, uid)

        for _ in range(2):
            reopened = self.open(measure_on_changed_source)
            m, = reopened.bundle["measurements"]
            self.assertEqual((m["state"], m[FIELDS[0]], m[FIELDS[1]]), ("needs_review", 4., None))
            self.assertIn("本次导入", m["audit"][1]["note"])
            self.assertEqual(len(reopened.value_history(lesion_id)), 5)

    def test_changed_pixels_in_an_existing_revision_cannot_keep_its_old_measurements(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        path = self.root / store.bundle["measurements"][0]["roi_ref"]
        revision = json.loads(path.read_text(encoding="utf-8"))
        revision["mask_bits"] = "wA=="  # 1100 instead of 1011; still a valid nonempty 2×2 ROI.
        path.write_text(json.dumps(revision), encoding="utf-8")
        reopened = self.open()
        finding, = reopened.bundle["measurements"]
        self.assertEqual((finding["state"], finding[FIELDS[0]], finding[FIELDS[1]]),
                         ("needs_review", None, None))
        self.assertEqual(len(reopened.value_history(lesion_id)), 4)
        self.assertEqual(self.open().value_history(lesion_id), reopened.value_history(lesion_id))

    def test_lost_calibration_revalidates_each_field_once_and_preserves_manual_overrides(self):
        store = self.open()
        automatic = store.save_roi(self.mask, **self.roi)
        manual = store.save_roi(self.mask, **self.roi)
        store.edit_value(manual, FIELDS[0], 4.25, "人工核对 SUV")

        def lost_weight(*_):
            return ({FIELDS[0]: None, FIELDS[1]: 10.},
                    {FIELDS[0]: "缺少患者体重，无法换算 SUV", FIELDS[1]: "示意投影长度"})

        for _ in range(2):
            store = self.open(lost_weight)
            for lesion_id, expected_suv, count in ((automatic, None, 3), (manual, 4.25, 4)):
                m = next(m for m in store.bundle["measurements"] if m["lesion_id"] == lesion_id)
                self.assertEqual((m[FIELDS[0]], m[FIELDS[1]], m["state"]), (expected_suv, 10., "needs_review"))
                self.assertIn("体重", m["audit"][-1]["note"])
                events = store.value_history(lesion_id)
                self.assertEqual((len(events), events[-1]["field"], events[-1]["to"]),
                                 (count, FIELDS[0], expected_suv))
                self.assertIn("体重", events[-1]["note"])
        restored = self.open()
        self.assertEqual([m[FIELDS[0]] for m in restored.bundle["measurements"]], [3., 4.25])
        for m in restored.bundle["measurements"]:
            self.assertEqual(m["state"], "needs_review")
            self.assertEqual(len(m["audit"]), 2)
        self.assertEqual(self.open().value_history(manual), restored.value_history(manual))

    def test_malformed_sidecar_event_fails_closed_with_an_actionable_error(self):
        store = self.open()
        store.save_roi(self.mask, **self.roi)
        data = json.loads(store.history_path.read_text(encoding="utf-8"))
        events, = data["by_measurement"].values()
        del events[0]["actor"]
        store.history_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "留痕"):
            self.open()

    def test_manual_edit_rejects_invalid_values_without_adding_events(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        for bad in (True, float("nan"), float("inf"), -1, None, "1.2"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                store.edit_value(lesion_id, FIELDS[0], bad, "人工修订")
        for field, note in (("label", "人工修订"), (FIELDS[1], "  ")):
            with self.assertRaises(ValueError):
                store.edit_value(lesion_id, field, 2, note)
        self.assertEqual(len(self.open().value_history(lesion_id)), 2)

    def test_terminal_records_are_neither_backfilled_nor_manually_overwritten(self):
        legacy = StudyStore(self.root, self.exam)
        ids = [legacy.save_roi(self.mask, **self.roi) for _ in range(2)]
        for m, end in zip(legacy.bundle["measurements"], ("accepted", "rejected")):
            at = m["audit"][0]["at"]
            m.update(state=end, suv_max=7.)
            m["audit"].extend([{"at": at, "actor": "system", "from": "proposed",
                                "to": "needs_review", "note": "请复核"},
                               {"at": at, "actor": "user", "from": "needs_review",
                                "to": end, "note": "人工复核"}])
        legacy.path.write_text(json.dumps(legacy.bundle), encoding="utf-8")
        store = self.open()
        self.assertEqual(store.bundle, legacy.bundle)
        for lesion_id in ids:
            with self.assertRaises(ValueError):
                store.edit_value(lesion_id, FIELDS[0], 10., "修改")
            with self.assertRaises(ValueError):
                store.save_roi(self.mask, lesion_id=lesion_id, **self.roi)
            self.assertEqual(store.value_history(lesion_id), [])

    def test_simultaneous_sessions_detect_a_stale_history_even_for_equal_values(self):
        first = self.open()
        lesion_id = first.save_roi(self.mask, **self.roi)
        first.edit_value(lesion_id, FIELDS[0], 3., "核对")
        stale = self.open()
        first.edit_value(lesion_id, FIELDS[0], 3., "再次核对")
        with self.assertRaisesRegex(ValueError, "重新"):
            stale.edit_value(lesion_id, FIELDS[1], 5., "人工改数")
        self.assertEqual(self.open().value_history(lesion_id)[-1]["note"], "再次核对")

    def test_interrupted_roi_commit_recovers_previous_manifest_roi_and_history(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        original = store.bundle
        original_history = store.value_history(lesion_id)
        replace = os.replace

        def stop_before_history(src, dst):
            if Path(dst).parent == self.root / "data/measurements":
                raise KeyboardInterrupt("模拟进程中断")
            return replace(src, dst)

        with patch("roi_store.os.replace", side_effect=stop_before_history), self.assertRaises(KeyboardInterrupt):
            store.save_roi(~self.mask, lesion_id=lesion_id, **self.roi)
        recovered = self.open()
        self.assertEqual(recovered.bundle, original)
        self.assertEqual(recovered.value_history(lesion_id), original_history)
        self.assertEqual(len(list((self.root / "data/rois").rglob("*.json"))), 1)
        recovered.save_roi(~self.mask, lesion_id=lesion_id, **self.roi)
        self.assertEqual(len(self.open().value_history(lesion_id)), 4)

    def test_interruption_after_history_commit_keeps_completed_change_exactly_once(self):
        store = self.open()
        lesion_id = store.save_roi(self.mask, **self.roi)
        unlink = Path.unlink

        def stop_at_cleanup(path, *args, **kwargs):
            if path == store.journal_path:
                raise KeyboardInterrupt("模拟提交完成后进程中断")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", stop_at_cleanup), self.assertRaises(KeyboardInterrupt):
            store.edit_value(lesion_id, FIELDS[1], 7.75, "复核长度")
        recovered = self.open()
        self.assertEqual(recovered.bundle["measurements"][0][FIELDS[1]], 7.75)
        history = recovered.value_history(lesion_id)
        self.assertEqual((len(history), history[-1]["to"]), (3, 7.75))
        self.assertEqual(self.open().value_history(lesion_id), history)
