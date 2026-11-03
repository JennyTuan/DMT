import json
import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))
import pairing
from roi_store import StudyStore, _writer_lock


class PairingTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        example = ROOT / "schemas/v0/examples/demo_001_baseline.json"
        self.template = json.loads(example.read_text(encoding="utf-8"))["exam"]
        self.base, self.b1, self.b2 = self.visit("baseline", 2)
        self.current, self.c1, self.c2 = self.visit("followup", 4)
        self.pairs = pairing.Pairing(self.current)

    def visit(self, exam_id, day, patient="demo_001", prior=None):
        exam = dict(self.template, exam_id=exam_id, patient_pseudo_id=patient,
                    prior_exam_id=prior, study_datetime=f"2026-02-{day:02d}T10:00:00+08:00")
        store = StudyStore(self.root, exam)
        ids = [store.save_roi(np.ones((1, 1), bool), slice_index=0, sop_uid="1.2.3",
                              seed=(0, 0), fraction=.6, label="示意") for _ in range(2)]
        return store, *ids

    def reopen(self, store):
        return StudyStore(self.root, store.bundle["exam"])

    @staticmethod
    def tracks(store):
        return [lesion.get("lesion_track_id") for lesion in store.bundle["lesions"]]

    def history(self):
        path = self.root / "data/pairings/followup.json"
        return json.loads(path.read_text(encoding="utf-8"))["events"]

    def test_only_earlier_exams_for_this_patient_can_be_set_or_replaced(self):
        self.visit("other", 1, patient="foreign")
        self.visit("later", 5)
        self.visit("simultaneous", 4)
        self.visit("second", 3)
        self.assertEqual([e["exam_id"] for e in self.pairs.candidates()], ["second", "baseline"])
        for invalid in ("other", "later", "followup", "simultaneous", "missing", "../baseline"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.pairs.set_prior(invalid)
        for prior_id in ("baseline", "second", None):
            self.pairs.set_prior(prior_id)
            self.assertEqual(self.reopen(self.current).bundle["exam"]["prior_exam_id"], prior_id)
            prior = self.pairs.prior_bundle()
            self.assertEqual(prior["exam"]["exam_id"] if prior else None, prior_id)

    def test_manual_pair_reassign_unpair_and_independent_track_preserve_measures_and_audit(self):
        initial = deepcopy(self.current.bundle)
        self.pairs.set_prior("baseline")
        self.pairs.new_track(self.c2)
        independent = self.tracks(self.current)[1]
        self.pairs.pair(self.c1, self.b1)
        first = self.tracks(self.current)[0]
        self.assertTrue(first)
        self.assertEqual(self.tracks(self.reopen(self.base)), [first, None])
        with self.assertRaises(ValueError):
            self.pairs.pair(self.c2, self.b1)
        self.pairs.pair(self.c1, self.b2)
        second = self.tracks(self.current)[0]
        self.assertNotEqual(first, second)
        self.assertEqual(self.tracks(self.reopen(self.base)), [first, second])
        self.pairs.unpair(self.c1)
        self.assertEqual(self.tracks(self.current), [None, independent])
        self.pairs.pair(self.c1, self.b1)
        self.pairs.set_prior(None)
        self.assertEqual(self.tracks(self.current), [None, independent])
        self.assertEqual(self.tracks(self.reopen(self.base)), [first, second])
        self.assertEqual(self.current.bundle["measurements"], initial["measurements"])
        self.assertEqual(self.current.bundle["lesions"][0]["audit"], initial["lesions"][0]["audit"])
        event = next(e for e in self.history() if e["action"] == "pair")
        self.assertEqual((event["current_exam_id"], event["prior_exam_id"],
                          event["current_lesion_id"], event["prior_lesion_id"]),
                         ("followup", "baseline", self.c1, self.b1))
        self.assertEqual((event["track_before"], event["track_after"]), (None, first))
        self.assertEqual(event["actor"], "user")
        self.assertTrue(event["operator"] and datetime.fromisoformat(event["at"]).tzinfo)

    def test_a_later_pair_cannot_silently_be_destroyed_by_editing_its_prior(self):
        self.pairs.set_prior("baseline")
        self.pairs.pair(self.c1, self.b1)
        later, l1, _ = self.visit("later", 6, prior="followup")
        last = pairing.Pairing(later)
        last.pair(l1, self.c1)
        fixed_track = self.tracks(later)[0]
        for edit in (lambda: self.pairs.new_track(self.c1), lambda: self.pairs.unpair(self.c1),
                     lambda: self.pairs.set_prior(None), lambda: self.pairs.pair(self.c1, self.b2)):
            with self.assertRaises(ValueError):
                edit()
        self.assertEqual(self.tracks(self.reopen(self.current))[0], fixed_track)
        self.assertEqual(self.tracks(self.reopen(self.base))[0], fixed_track)
        last.unpair(l1)
        self.pairs.unpair(self.c1)

    def test_stale_display_and_cross_exam_lesions_are_refused(self):
        old = pairing.Pairing(self.reopen(self.current))
        self.pairs.set_prior("baseline")
        with self.assertRaisesRegex(ValueError, "重新"):
            old.snapshot()
        self.pairs.prior_bundle()
        baseline = pairing.Pairing(self.reopen(self.base))
        baseline.new_track(self.b1)
        with self.assertRaisesRegex(ValueError, "重新"):
            self.pairs.pair(self.c1, self.b1)
        self.pairs.prior_bundle()
        for ids in ((self.b1, self.b2), (self.c1, self.c2)):
            with self.assertRaises(ValueError):
                self.pairs.pair(*ids)
        self.pairs.pair(self.c1, self.b1)
        self.assertEqual(self.tracks(self.current)[0], self.tracks(self.reopen(self.base))[0])

    def test_interrupted_pair_rolls_back_before_either_exam_can_be_edited(self):
        self.pairs.set_prior("baseline")
        audit = self.history()
        replace = os.replace

        def stop_before_audit(src, dst):
            if Path(dst) == self.root / "data/pairings/followup.json":
                raise KeyboardInterrupt("模拟掉电")
            return replace(src, dst)

        with patch("roi_store.os.replace", side_effect=stop_before_audit), self.assertRaises(KeyboardInterrupt):
            self.pairs.pair(self.c1, self.b1)
        reopened_base = self.reopen(self.base)
        self.assertEqual(self.tracks(reopened_base), [None, None])
        reopened_base.edit_value(self.b1, "suv_max", 4, "人工核对")
        self.assertEqual(self.tracks(self.reopen(self.current)), [None, None])
        self.assertEqual(self.history(), audit)
        self.assertEqual(self.reopen(self.base).bundle["measurements"][0]["suv_max"], 4.)

    def test_interrupted_measurement_is_recovered_before_pairing_updates_the_same_prior(self):
        self.pairs.set_prior("baseline")
        replace = os.replace

        def stop_before_history(src, dst):
            if Path(dst) == self.base.history_path:
                raise KeyboardInterrupt("模拟掉电")
            return replace(src, dst)

        with patch("roi_store.os.replace", side_effect=stop_before_history), self.assertRaises(KeyboardInterrupt):
            self.base.edit_value(self.b1, "suv_max", 4, "人工核对")
        self.pairs.pair(self.c1, self.b1)
        saved = self.reopen(self.base)
        self.assertEqual(self.tracks(saved)[0], self.tracks(self.current)[0])
        self.assertTrue(self.tracks(saved)[0])
        self.assertIsNone(saved.bundle["measurements"][0]["suv_max"])

    def test_prior_writer_lock_blocks_changes_to_its_manifest(self):
        self.pairs.set_prior("baseline")
        with _writer_lock(self.base.lock_path), self.assertRaisesRegex(ValueError, "重新"):
            self.pairs.pair(self.c1, self.b1)
        self.assertEqual(self.tracks(self.reopen(self.base)), [None, None])
        self.assertEqual(self.tracks(self.reopen(self.current)), [None, None])

    def test_explicit_clear_decision_survives_without_an_existing_prior(self):
        self.assertFalse(self.pairs.has_prior_decision())
        self.pairs.set_prior(None)
        self.assertTrue(pairing.Pairing(self.reopen(self.current)).has_prior_decision())

    def test_demo_initialization_is_system_recorded_once_and_honors_an_explicit_clear(self):
        self.pairs.ensure_demo_prior("baseline")
        self.pairs.ensure_demo_prior("baseline")
        self.assertEqual(self.current.bundle["exam"]["prior_exam_id"], "baseline")
        init, = self.history()
        self.assertEqual((init["actor"], init["operator"], init["prior_exam_id"]), ("system", "demo", "baseline"))
        self.pairs.set_prior(None)
        pairing.Pairing(self.reopen(self.current)).ensure_demo_prior("baseline")
        self.assertIsNone(self.reopen(self.current).bundle["exam"]["prior_exam_id"])
        self.assertEqual([e["actor"] for e in self.history()], ["system", "user"])

    def test_real_studies_cannot_participate_in_demo_initialization(self):
        self.template["is_synthetic"] = False
        real_prior, _, _ = self.visit("real_prior", 1)
        real_current, _, _ = self.visit("real_current", 6)
        for current, base in ((self.current, real_prior), (real_current, self.base)):
            with self.assertRaises(ValueError):
                pairing.Pairing(current).ensure_demo_prior(base.exam_id)
            self.assertIsNone(self.reopen(current).bundle["exam"]["prior_exam_id"])

    def test_switching_prior_records_both_lesion_ids_for_an_already_shared_independent_track(self):
        self.pairs.set_prior("baseline")
        self.pairs.pair(self.c1, self.b1)
        self.pairs.new_track(self.c2)
        track = self.tracks(self.current)[1]
        other, o1, _ = self.visit("second", 3)
        # Imported exams can already carry a shared, explicit longitudinal ID.
        other.bundle["lesions"][0]["lesion_track_id"] = track
        other.path.write_text(json.dumps(other.bundle), encoding="utf-8")
        self.pairs.set_prior("second")
        self.assertEqual(self.tracks(self.current), [None, track])
        known, = [e for e in self.history() if e["action"] == "existing_track"]
        self.assertEqual((known["current_exam_id"], known["prior_exam_id"], known["current_lesion_id"],
                          known["prior_lesion_id"], known["track_before"], known["track_after"]),
                         ("followup", "second", self.c2, o1, track, track))

    def test_blank_legacy_tracks_get_a_real_id_only_on_manual_pair(self):
        for store in (self.current, self.base):
            for lesion in store.bundle["lesions"]:
                lesion["lesion_track_id"] = " "
            store.path.write_text(json.dumps(store.bundle), encoding="utf-8")
        self.pairs.set_prior("baseline")
        self.pairs.pair(self.c1, self.b1)
        track = self.tracks(self.current)[0]
        self.assertTrue(track.strip())
        self.assertEqual(self.tracks(self.reopen(self.base)), [track, " "])

    def test_committed_pair_survives_interrupted_cleanup_exactly_once(self):
        self.pairs.set_prior("baseline")
        unlink = Path.unlink

        def stop_after_audit(path, *args, **kwargs):
            if path == self.root / "data/pairings/.pending":
                raise KeyboardInterrupt("模拟提交后掉电")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", stop_after_audit), self.assertRaises(KeyboardInterrupt):
            self.pairs.pair(self.c1, self.b1)
        recovered = self.reopen(self.current)
        track = self.tracks(recovered)[0]
        self.assertTrue(track)
        self.assertEqual(self.tracks(self.reopen(self.base))[0], track)
        pairing.Pairing(recovered).pair(self.c1, self.b1)
        self.assertEqual([e["action"] for e in self.history()], ["set_prior", "pair"])


if __name__ == "__main__":
    unittest.main()
