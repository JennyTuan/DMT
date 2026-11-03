import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma"))

from fixtures.make_demo import make_demo_pair
from imaging import load_study
from manual_params import effective_headers, read_manual, save_manual, revoke_manual
from suv import _scale


class ManualParamsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        _, current = make_demo_pair(Path(self.temp.name) / "data/fixtures")
        self.study = load_study(current)
        self.headers = self.study.pet_headers
        self.original_scale = _scale(self.headers)[0]
        self.dose = float(self.headers[0].RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose)
        for ds in self.headers:
            del ds.RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose

    def tearDown(self):
        self.temp.cleanup()

    def test_two_matching_sources_restore_missing_dose_with_watermark(self):
        with self.assertRaisesRegex(ValueError, "剂量"):
            _scale(self.headers)
        source = {"name": "注射记录", "values": {"dose_bq": self.dose}}
        record = save_manual(self.temp.name, self.study.exam["exam_id"], self.headers,
                             source, {**source, "name": "扫描日志"}, "doctor-1")
        self.assertEqual(record["watermark"], "[Manual Input]")
        self.assertAlmostEqual(_scale(effective_headers(self.headers, record))[0], self.original_scale)
        self.assertEqual(read_manual(self.temp.name, self.study.exam["exam_id"])["version"], 1)
        event = revoke_manual(self.temp.name, self.study.exam["exam_id"], "doctor-1", "发现记录错误")
        self.assertTrue(event["revoked"])
        self.assertIsNone(read_manual(self.temp.name, self.study.exam["exam_id"]))

    def test_disagreement_and_conflict_are_rejected(self):
        first = {"name": "注射记录", "values": {"dose_bq": self.dose}}
        second = {"name": "扫描日志", "values": {"dose_bq": self.dose * 2}}
        with self.assertRaisesRegex(ValueError, "一致"):
            save_manual(self.temp.name, self.study.exam["exam_id"], self.headers, first, second, "doctor-1")
        self.headers[0].RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose = self.dose * 2
        with self.assertRaisesRegex(ValueError, "冲突"):
            save_manual(self.temp.name, self.study.exam["exam_id"], self.headers,
                        first, {**first, "name": "扫描日志"}, "doctor-1")


if __name__ == "__main__":
    unittest.main()
