import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))
from roi_store import StudyStore


def measure(mask, index, sop_uid):
    return ({"suv_max": 3., "longest_diameter_mm": 10.},
            {"suv_max": "示意 SUV", "longest_diameter_mm": "示意 CT 径线"})


class MeasurementGateTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        example = ROOT / "schemas/v0/examples/demo_001_baseline.json"
        self.exam = json.loads(example.read_text(encoding="utf-8"))["exam"]
        self.mask = np.array([[True, False], [False, True]])
        self.args = dict(slice_index=0, sop_uid="1.2.3", seed=(0, 0), fraction=.5, label="示意部位")

    def test_manual_save_after_mask_emptied_retires_automatic_values_and_preserves_the_edit(self):
        store = StudyStore(self.root, self.exam, measure)
        lesion = store.save_roi(self.mask, **self.args)
        measurement, = store.bundle["measurements"]
        path = self.root / measurement["roi_ref"]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["mask_bits"] = "AA=="
        path.write_text(json.dumps(record), encoding="utf-8")

        store.edit_value(lesion, "suv_max", 9., "人工核对")
        updated, = store.bundle["measurements"]
        self.assertEqual((updated["state"], updated["suv_max"], updated["longest_diameter_mm"]),
                         ("needs_review", 9., None))
        self.assertIn("ROI_EMPTY", updated["audit"][-1]["note"])
        history = store.value_history(lesion)
        self.assertEqual(StudyStore(self.root, self.exam, measure).value_history(lesion), history)

    def test_evidence_follows_the_current_roi_and_preserves_source_error_after_manual_edit(self):
        def incomplete(mask, index, sop_uid):
            if mask.sum() == 2:
                return ({"suv_max": None, "longest_diameter_mm": 10.},
                        {"suv_max": "示意单位缺失", "longest_diameter_mm": "示意 CT 径线"})
            return measure(mask, index, sop_uid)

        store = StudyStore(self.root, self.exam, incomplete)
        lesion = store.save_roi(self.mask, **self.args)
        measurement, = store.bundle["measurements"]
        self.assertIn("SUV_META_MISSING", measurement["audit"][-1]["note"])
        store.edit_value(lesion, "suv_max", 6., "人工核对")
        key = measurement["measurement_id"]
        self.assertEqual(store.quality_evidence(), ({key: True}, {key: {"suv_max": "示意单位缺失"}}))

        store.save_roi(np.ones((2, 2), bool), lesion_id=lesion, **self.args)
        self.assertEqual(store.quality_evidence(), ({key: True}, {key: {}}))
        self.assertEqual(len(store.bundle["measurements"][0]["audit"]), 2)

    def test_refresh_against_disk_is_per_measurement_and_idempotent(self):
        store = StudyStore(self.root, self.exam, measure)
        lesions = [store.save_roi(self.mask, **self.args) for _ in range(3)]
        missing, corrupt, good = store.bundle["measurements"]
        (self.root / missing["roi_ref"]).unlink()
        (self.root / corrupt["roi_ref"]).write_text("{", encoding="utf-8")
        expected = {missing["measurement_id"]: False, corrupt["measurement_id"]: False,
                    good["measurement_id"]: True}
        validity, _ = store.quality_evidence()
        self.assertEqual(validity, expected)
        self.assertEqual(store.bundle["measurements"][0]["state"], "proposed")
        validity, errors = store.refresh_quality()
        self.assertEqual(validity, expected)
        self.assertTrue(errors[corrupt["measurement_id"]]["suv_max"])
        self.assertEqual(errors[good["measurement_id"]], {})
        saved = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual([(m["state"], m["suv_max"], m["longest_diameter_mm"])
                          for m in saved["measurements"]],
                         [("needs_review", None, None), ("needs_review", None, None), ("proposed", 3., 10.)])
        histories = [store.value_history(lesion) for lesion in lesions]
        store.refresh_quality()
        self.assertEqual([store.value_history(lesion) for lesion in lesions], histories)

    def test_absent_roi_ref_in_legacy_store_still_gates_manual_save(self):
        store = StudyStore(self.root, self.exam)
        lesion = store.save_roi(self.mask, **self.args)
        bundle = json.loads(store.path.read_text(encoding="utf-8"))
        bundle["measurements"][0]["roi_ref"] = None
        store.path.write_text(json.dumps(bundle), encoding="utf-8")
        store = StudyStore(self.root, self.exam)
        store.edit_value(lesion, "longest_diameter_mm", 0., "人工复核记录")
        m, = store.bundle["measurements"]
        self.assertEqual((m["state"], m["suv_max"], m["longest_diameter_mm"]), ("needs_review", None, 0.))
        self.assertIn("ROI_EMPTY", m["audit"][-1]["note"])
        self.assertEqual(len(store.value_history(lesion)), 1)

    def test_old_human_terminal_is_checked_without_rewriting_its_state(self):
        from quality_gate import measurement_gates
        store = StudyStore(self.root, self.exam, measure)
        lesion = store.save_roi(self.mask, **self.args)
        bundle = json.loads(store.path.read_text(encoding="utf-8"))
        m = bundle["measurements"][0]
        event = dict(m["audit"][0], actor="user", note="人工记录")
        m["audit"].extend([{**event, "from": "proposed", "to": "needs_review"},
                           {**event, "from": "needs_review", "to": "accepted"}])
        m["state"] = "accepted"
        store.path.write_text(json.dumps(bundle), encoding="utf-8")
        def missing_weight(*args):
            return ({"suv_max": None, "longest_diameter_mm": 10.},
                    {"suv_max": "缺少体重", "longest_diameter_mm": "可核对"})
        reopened = StudyStore(self.root, self.exam, missing_weight)
        validity, errors = reopened.refresh_quality()
        target = m["measurement_id"]
        findings = measurement_gates(self.exam, m, roi_valid=validity[target], field_errors=errors[target])
        self.assertEqual(next(r for r in findings if r["gate_id"] == "SUV_META_MISSING")["level"], "block")
        self.assertEqual(reopened.bundle, bundle)
        self.assertEqual(reopened.value_history(lesion), store.value_history(lesion))
