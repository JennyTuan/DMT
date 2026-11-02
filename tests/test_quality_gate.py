import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from quality_gate import BANNER, evaluate_bundle, measurement_gates, prior_gates, report_gates


def example(visit):
    path = ROOT / "schemas/v0/examples" / f"demo_001_{visit}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def levels(results):
    return {item["gate_id"]: item["level"] for item in results}


class MeasurementGatesTests(unittest.TestCase):
    def setUp(self):
        current = example("followup")
        self.exam = current["exam"]
        self.measure, = current["measurements"]
        self.measure["roi_ref"] = "existing-version.json"

    def test_absent_ac_is_distinct_from_missing_metadata(self):
        self.exam["attenuation_corrected"] = False
        self.measure["suv_max"] = None
        for errors in ({}, {"suv_max": "缺/未衰减校正，SUV 仅供复核"},
                       {"suv_max": "示意 SUV。缺/未衰减校正，SUV 仅供复核"}):
            checks = levels(measurement_gates(self.exam, self.measure, roi_valid=True, field_errors=errors))
            self.assertEqual(checks["AC_MISSING"], "review")
            self.assertEqual(checks["SUV_META_MISSING"], "not_checked")
            self.assertEqual(checks["CT_ALIGN_FAIL"], "pass")

    def test_failed_source_takes_precedence_over_preserved_human_values(self):
        self.measure.update(edited=True, state="needs_review")
        before = deepcopy(self.measure)
        errors = {"suv_max": "PET 单位缺失或不支持 SUVbw 换算",
                  "longest_diameter_mm": "ROI 投影超出 CT 视野。"}
        checks = measurement_gates(self.exam, self.measure, roi_valid=True, field_errors=errors)
        self.assertEqual(levels(checks), {"AC_MISSING": "pass", "SUV_META_MISSING": "review",
                                        "CT_ALIGN_FAIL": "review", "ROI_EMPTY": "pass"})
        self.assertEqual(self.measure, before)
        self.assertTrue(all(item["target_id"] == self.measure["measurement_id"] for item in checks))
        self.assertTrue(all(item["message"] and item["action"] for item in checks))

    def test_unusable_roi_does_not_claim_ct_or_calibration_failed(self):
        self.measure.update(suv_max=None, longest_diameter_mm=None)
        for ref, valid in ((None, None), ("   ", True), ("empty-or-missing-on-disk", False)):
            with self.subTest(ref=ref):
                self.measure["roi_ref"] = ref
                checks = levels(measurement_gates(self.exam, self.measure, roi_valid=valid))
                self.assertEqual(checks, {"AC_MISSING": "pass", "ROI_EMPTY": "review",
                                          "SUV_META_MISSING": "not_checked", "CT_ALIGN_FAIL": "not_checked"})

    def test_nonfinite_or_negative_measurements_cannot_pass(self):
        for bad in (True, float("inf"), float("nan"), -1.):
            self.measure.update(suv_max=bad, longest_diameter_mm=bad)
            with self.subTest(bad=bad):
                checks = levels(measurement_gates(self.exam, self.measure, roi_valid=True))
                self.assertEqual(checks["SUV_META_MISSING"], "review")
                self.assertEqual(checks["CT_ALIGN_FAIL"], "review")

    def test_pack03_shared_roi_source_failure_has_one_reason(self):
        reason = "ROI 量测失败（本次导入的 PET 实例不匹配）"
        errors = dict.fromkeys(("suv_max", "longest_diameter_mm"), reason)
        checks = measurement_gates(self.exam, self.measure, roi_valid=True, field_errors=errors)
        self.assertEqual(levels(checks), {"AC_MISSING": "pass", "ROI_EMPTY": "review",
                                         "SUV_META_MISSING": "not_checked", "CT_ALIGN_FAIL": "not_checked"})
        self.assertIn(reason, next(item["message"] for item in checks if item["gate_id"] == "ROI_EMPTY"))

    def test_pack03_mask_mismatch_is_not_a_ct_or_unit_failure(self):
        errors = {"suv_max": "PET ROI 为空或与层面不匹配",
                  "longest_diameter_mm": "ROI 与 PET 层面不匹配或为空，请重新核对轮廓。"}
        self.measure.update(suv_max=None, longest_diameter_mm=None)
        checks = levels(measurement_gates(self.exam, self.measure, roi_valid=True, field_errors=errors))
        self.assertEqual(checks, {"AC_MISSING": "pass", "ROI_EMPTY": "review",
                                  "SUV_META_MISSING": "not_checked", "CT_ALIGN_FAIL": "not_checked"})

    def test_uninspected_mask_and_contour_only_save_do_not_overclaim(self):
        self.assertEqual(levels(measurement_gates(self.exam, self.measure))["ROI_EMPTY"], "not_checked")
        self.measure.update(suv_max=None, longest_diameter_mm=None)
        checks = levels(measurement_gates(self.exam, self.measure, roi_valid=True, quantitative=False))
        self.assertEqual(checks, {"AC_MISSING": "pass", "ROI_EMPTY": "pass",
                                  "SUV_META_MISSING": "not_checked", "CT_ALIGN_FAIL": "not_checked"})
        checks = levels(measurement_gates(self.exam, self.measure, roi_valid=True))
        self.assertEqual(checks["SUV_META_MISSING"], "review")
        self.assertEqual(checks["CT_ALIGN_FAIL"], "review")


class PriorGatesTests(unittest.TestCase):
    def setUp(self):
        self.current = example("followup")
        self.prior = example("baseline")
        self.lesion, = self.current["lesions"]

    def test_invalid_links_block_but_absence_of_a_link_is_valid(self):
        for change in (None, {"exam_id": "other"}, {"patient_pseudo_id": "unrelated"},
                       {"study_datetime": "2029-01-01T00:00:00Z"}, {"study_datetime": "invalid"}):
            with self.subTest(change=change):
                prior = deepcopy(self.prior) if change else None
                if prior:
                    prior["exam"].update(change)
                self.assertEqual(levels(prior_gates(self.current, prior))["PRIOR_BROKEN"], "block")
        self.current["exam"]["prior_exam_id"] = None
        self.assertEqual(levels(prior_gates(self.current, None))["PRIOR_BROKEN"], "pass")
        self.assertNotIn("warn", levels(prior_gates(self.current, None)).values())

    def test_only_unique_pairs_and_explicit_skips_clear_the_track_warning(self):
        self.assertEqual(levels(prior_gates(self.current, self.prior))["TRACK_INCOMPLETE"], "pass")
        for track in (None, "  ", "standalone"):
            self.lesion["lesion_track_id"] = track
            check, = (r for r in prior_gates(self.current, self.prior) if r["gate_id"] == "TRACK_INCOMPLETE")
            self.assertEqual((check["target_id"], check["level"]), (self.lesion["lesion_id"], "warn"))
            skipped = [self.lesion["lesion_id"]]
            self.assertEqual(levels(prior_gates(self.current, self.prior, skipped=skipped))["TRACK_INCOMPLETE"], "pass")
        self.lesion["lesion_track_id"] = self.prior["lesions"][0]["lesion_track_id"]
        for bundle in (self.current, self.prior):
            bundle["lesions"].append({**bundle["lesions"][0], "lesion_id": "duplicate"})
            self.assertEqual(levels(prior_gates(self.current, self.prior))["TRACK_INCOMPLETE"], "warn")
            bundle["lesions"].pop()


class ReportGatesTests(unittest.TestCase):
    def setUp(self):
        self.current = example("followup")

    def test_declaration_must_match_source_and_exact_first_line_of_output(self):
        for text in ("", "\n" + BANNER, BANNER + "追加", "其它\n" + BANNER,
                     " " + BANNER, BANNER + "\v正文"):
            self.assertEqual(levels(report_gates(self.current, text))["PROTOTYPE_BANNER"], "block")
        self.assertEqual(levels(report_gates(self.current, BANNER + "\r\n正文"))["PROTOTYPE_BANNER"], "pass")
        self.current["exam"]["prototype_banner"] = BANNER + " "
        self.assertEqual(levels(report_gates(self.current, BANNER))["PROTOTYPE_BANNER"], "block")

    def test_block_report_and_imported_labels_without_echoing_excluded_terms(self):
        for term in ("Ｄｅａｕｖｉｌｌｅ 4", "LUGANO", "ＰＭＤ", "部分代谢缓解", "恶性", "良性", "辅助诊断",
                     "疗效结论", "complete metabolic response", "partial response", "stable disease",
                     "disease progression", "malignant", "remission", "AI-assisted diagnosis",
                     "FDGDeauvilleScore", "applyLuganoCriteria", "response: PR", "应答：CR"):
            with self.subTest(term=term):
                for in_label in (True, False):
                    self.current["lesions"][0]["label"] = term if in_label else "纵隔"
                    text = BANNER if in_label else BANNER + "\n" + term
                    result, = (r for r in report_gates(self.current, text) if r["gate_id"] == "BANNED_TERMS")
                    self.assertEqual(result["level"], "block")
                    self.assertNotIn(term.casefold(), (result["message"] + result["action"]).casefold())

    def test_descriptive_text_and_harmless_identifier_substrings_are_allowed(self):
        text = BANNER + "\ntrack_CMR_01 / xpmr2 / series_CR_01 / PR interval / 12mm. 本次与上次层面不同。"
        self.assertEqual(levels(report_gates(self.current, text))["BANNED_TERMS"], "pass")

    def test_new_visit_has_all_gate_ids_without_inventing_lesions_or_measurements(self):
        self.current.update(lesions=[], measurements=[])
        self.current["exam"]["prior_exam_id"] = None
        for corrected, expected_ac in ((True, "pass"), (False, "warn")):
            self.current["exam"]["attenuation_corrected"] = corrected
            rows = evaluate_bundle(self.current)
            self.assertEqual(levels(rows), {"AC_MISSING": expected_ac, "SUV_META_MISSING": "not_checked",
                             "CT_ALIGN_FAIL": "not_checked", "ROI_EMPTY": "not_checked",
                             "TRACK_INCOMPLETE": "not_checked", "PRIOR_BROKEN": "pass",
                             "PROTOTYPE_BANNER": "pass", "BANNED_TERMS": "pass"})
            self.assertEqual({r["target_id"] for r in rows}, {self.current["exam"]["exam_id"]})

    def test_bundle_applies_evidence_to_the_matching_measurement_only(self):
        first, = self.current["measurements"]
        first["roi_ref"] = "r1"
        second = dict(first, measurement_id="second", lesion_id="other", roi_ref="r2")
        self.current["measurements"].append(second)
        self.current["lesions"].append(dict(self.current["lesions"][0], lesion_id="other", lesion_track_id=None))
        before = deepcopy(self.current)
        results = evaluate_bundle(self.current, example("baseline"), roi_validity={first["measurement_id"]: True,
                                  "second": False}, field_errors={first["measurement_id"]: {"suv_max": "体重缺失"}})
        by_target = {(r["gate_id"], r["target_id"]): r for r in results}
        self.assertEqual(by_target["SUV_META_MISSING", first["measurement_id"]]["level"], "review")
        self.assertEqual(by_target["ROI_EMPTY", first["measurement_id"]]["level"], "pass")
        self.assertEqual(by_target["ROI_EMPTY", "second"]["level"], "review")
        self.assertEqual(by_target["TRACK_INCOMPLETE", "other"]["level"], "warn")
        self.assertTrue(all({"gate_id", "target_id", "level", "message", "action"} <= r.keys() for r in results))
        self.assertEqual(self.current, before)


if __name__ == "__main__":
    unittest.main()
