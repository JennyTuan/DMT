import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import pydicom
from pydicom.uid import KeyObjectSelectionDocumentStorage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))

from fixtures.make_demo import make_demo_pair
from imaging import load_study
from key_image import key_object_bytes
from roi_store import StudyStore, grow_region


class KeyImageTests(unittest.TestCase):
    def test_key_object_references_selected_pet_and_ct(self):
        with tempfile.TemporaryDirectory() as directory:
            _, current = make_demo_pair(Path(directory) / "data/fixtures")
            study = load_study(current)
            store = StudyStore(directory, study.exam)
            mask = grow_region(study.pet[10], 104, 90, .65)
            lesion_id = store.save_roi(mask, slice_index=10, sop_uid=study.pet_uids[10],
                                       seed=(104, 90), fraction=.65, label="示意病灶")
            blob = key_object_bytes(study, store, lesion_id)
            result = pydicom.dcmread(BytesIO(blob))
            self.assertEqual(result.SOPClassUID, KeyObjectSelectionDocumentStorage)
            self.assertEqual(result.Modality, "KO")
            refs = [item.ReferencedSOPInstanceUID
                    for study_item in result.CurrentRequestedProcedureEvidenceSequence
                    for series in study_item.ReferencedSeriesSequence
                    for item in series.ReferencedSOPSequence]
            self.assertIn(study.pet_headers[10].SOPInstanceUID, refs)
            self.assertGreaterEqual(len(refs), 1)


if __name__ == "__main__":
    unittest.main()
