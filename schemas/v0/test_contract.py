import json
import unittest
from datetime import datetime
from itertools import product
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parent
SCHEMAS = {
    path.name: json.loads(path.read_text(encoding="utf-8"))
    for path in ROOT.glob("*.schema.json")
}
REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values()
)


def validator(name, fragment=""):
    ref = SCHEMAS[name + ".schema.json"]["$id"] + fragment
    return Draft202012Validator({"$ref": ref}, registry=REGISTRY, format_checker=FormatChecker())


def example(visit):
    path = ROOT / "examples" / f"demo_001_{visit}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def event(before, after, actor="system"):
    return {"at": "2026-04-10T10:00:00+08:00", "actor": actor,
            "from": before, "to": after, "note": "示意记录"}


class Pack01(unittest.TestCase):
    def test_schema_dialect(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(name=name):
                self.assertEqual(schema["$schema"], Draft202012Validator.META_SCHEMA["$id"])
                Draft202012Validator.check_schema(schema)

    def test_prototype_scope_and_nullable_measurements(self):
        bundle = example("baseline")
        exam = bundle["exam"]
        check = validator("exam")
        for field, value in (("disease", "other"), ("modality", "MR"),
                             ("prototype_banner", ""), ("attenuation_corrected", None)):
            with self.subTest(field=field):
                self.assertFalse(check.is_valid({**exam, field: value}))
        missing_values = {**bundle["measurements"][0], "suv_max": None, "longest_diameter_mm": None}
        measure = validator("measurement")
        measure.validate(missing_values)
        for field in ("suv_max", "longest_diameter_mm"):
            with self.subTest(field=field):
                self.assertFalse(measure.is_valid({**missing_values, field: -1}))

    def test_paired_examples(self):
        baseline, followup = example("baseline"), example("followup")
        for bundle in (baseline, followup):
            validator("exam", "#/$defs/bundle").validate(bundle)
            exam = bundle["exam"]
            self.assertTrue(exam["is_synthetic"])
            self.assertTrue(bundle["lesions"])
            lesion_ids = {row["lesion_id"] for row in bundle["lesions"]}
            self.assertEqual(lesion_ids, {row["lesion_id"] for row in bundle["measurements"]})
            for lesion in bundle["lesions"]:
                self.assertEqual(lesion["exam_id"], exam["exam_id"])
            for row in bundle["measurements"]:
                self.assertIsNotNone(row["suv_max"])
                self.assertIsNotNone(row["longest_diameter_mm"])
                self.assertEqual(row["state"], "proposed")
        prior, current = baseline["exam"], followup["exam"]
        self.assertIsNone(prior["prior_exam_id"])
        self.assertNotEqual(prior["exam_id"], current["exam_id"])
        self.assertEqual(current["prior_exam_id"], prior["exam_id"])
        self.assertEqual(current["patient_pseudo_id"], prior["patient_pseudo_id"])
        self.assertLess(datetime.fromisoformat(prior["study_datetime"]),
                        datetime.fromisoformat(current["study_datetime"]))

    def test_only_authorized_transitions(self):
        states = ("draft", "proposed", "needs_review", "accepted", "rejected")
        allowed = {("draft", "proposed"), ("proposed", "needs_review"),
                   ("needs_review", "accepted"), ("needs_review", "rejected")}
        entry = validator("finding_state", "#/$defs/audit_entry")
        for before, after, actor in product(states, states, ("user", "system")):
            with self.subTest(before=before, after=after, actor=actor):
                expected = (before, after) in allowed and (
                    after not in ("accepted", "rejected") or actor == "user"
                )
                self.assertEqual(entry.is_valid(event(before, after, actor)), expected)

    def test_audit_fields(self):
        entry = validator("finding_state", "#/$defs/audit_entry")
        first = event("draft", "proposed")
        for field in first:
            with self.subTest(missing=field):
                self.assertFalse(entry.is_valid({k: v for k, v in first.items() if k != field}))
        self.assertFalse(entry.is_valid({**first, "at": "yesterday"}))

    def test_current_state_matches_complete_history(self):
        bundle = example("baseline")
        first = event("draft", "proposed")
        review = event("proposed", "needs_review")
        accept = event("needs_review", "accepted", "user")
        reject = event("needs_review", "rejected", "user")
        cases = [
            ("draft", [], True), ("proposed", [first], True),
            ("needs_review", [first, review], True),
            ("accepted", [first, review, accept], True),
            ("rejected", [first, review, reject], True),
            ("proposed", [], False), ("accepted", [], False),
            ("needs_review", [review], False), ("needs_review", [first, first], False),
            ("accepted", [first, review, reject], False),
            ("draft", [first, review, accept, first], False),
        ]
        for name, base, key in (("finding_state", {}, "state"),
                                ("lesion", bundle["lesions"][0], "status"),
                                ("measurement", bundle["measurements"][0], "state")):
            check = validator(name)
            for state, audit, expected in cases:
                with self.subTest(name=name, state=state, audit=audit):
                    self.assertEqual(check.is_valid({**base, key: state, "audit": audit}), expected)

    def test_rejects_extra_fields_at_every_level(self):
        check = validator("exam", "#/$defs/bundle")
        for field in ("deauville_score", "lugano", "diagnosis", "response", "malignancy"):
            bundle = example("baseline")
            lesion, measurement = bundle["lesions"][0], bundle["measurements"][0]
            for obj in (bundle, bundle["exam"], lesion, lesion["audit"][0],
                        measurement, measurement["audit"][0]):
                with self.subTest(field=field, keys=list(obj)):
                    obj[field] = 1
                    self.assertFalse(check.is_valid(bundle))
                    del obj[field]


if __name__ == "__main__":
    unittest.main()
