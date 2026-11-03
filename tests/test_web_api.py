"""Browser API exercises existing quantitative and audit rules with synthetic data."""

import sys
import tempfile
import unittest
import base64
from io import BytesIO
from pathlib import Path
from werkzeug.datastructures import MultiDict
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/petfollow-lymphoma/web"))

from server import create_app


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_demo_roi_pair_and_report(self):
        current_id = self.client.post("/api/demo", json={}).json["exam_id"]
        state = self.client.get("/api/state").json
        prior_id = state["prior"]["exam_id"]
        self.assertEqual(len(state["exams"]), 2)
        self.assertEqual(state["pet_count"], 21)
        for plane in ("coronal", "sagittal", "mip"):
            image_response = self.client.get("/api/image", query_string={
                "exam_id": current_id, "modality": "pet", "plane": plane, "index": 0,
            })
            self.assertEqual(image_response.status_code, 200, image_response.get_json() if image_response.is_json else plane)
        ct = Image.open(BytesIO(self.client.get("/api/image", query_string={
            "exam_id": current_id, "modality": "ct", "index": 15,
        }).data))
        fusion_zero = Image.open(BytesIO(self.client.get("/api/image", query_string={
            "exam_id": current_id, "modality": "fusion", "index": 15, "opacity": 0,
        }).data))
        fusion_full = Image.open(BytesIO(self.client.get("/api/image", query_string={
            "exam_id": current_id, "modality": "fusion", "index": 15, "opacity": 1,
        }).data))
        self.assertEqual(fusion_zero.tobytes(), ct.tobytes())
        self.assertNotEqual(fusion_full.tobytes(), ct.tobytes())
        self.assertEqual(self.client.get("/api/image", query_string={
            "exam_id": current_id, "modality": "fusion", "index": 15, "opacity": 2,
        }).status_code, 400)

        aligned = self.client.post("/api/align", json={
            "exam_id": current_id,
            "base": {"index": 10, "point": [104, 90]},
            "current": {"index": 10, "point": [104, 90]},
        })
        self.assertEqual(aligned.status_code, 200, aligned.get_json())
        self.assertEqual(aligned.json["offset_mm"], [0.0, 0.0, 0.0])
        self.assertEqual(len(aligned.json["slice_locations"]["basePet"]), 21)
        self.assertEqual(len(aligned.json["slice_locations"]["currentCt"]), 31)

        reference = self.client.post("/api/reference", json={
            "exam_id": current_id, "kind": "liver", "index": 10, "point": [90, 90],
        })
        self.assertEqual(reference.status_code, 200, reference.get_json())
        self.assertGreater(reference.json["suv_mean"], 0)
        self.assertEqual(self.client.get("/api/state").json["references"]["liver"]["version"], 1)
        displayed = Image.open(BytesIO(self.client.get("/api/image", query_string={
            "exam_id": current_id, "modality": "pet", "index": 10,
        }).data))
        self.assertGreater(sum(pixel == (216, 176, 108) for pixel in displayed.getdata()), 0)
        missing_reviewer = self.client.post("/api/reference/confirm", json={
            "exam_id": current_id, "kind": "liver", "version": 1, "reviewer": "",
        })
        self.assertEqual(missing_reviewer.status_code, 400)
        confirmed = self.client.post("/api/reference/confirm", json={
            "exam_id": current_id, "kind": "liver", "version": 1, "reviewer": "test-doctor",
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        self.assertTrue(confirmed.json["placement_confirmed"])

        preview = self.client.post("/api/roi/preview", json={
            "exam_id": current_id, "index": 10, "seed": [104, 90], "fraction": .65,
        })
        self.assertEqual(preview.status_code, 200)
        self.assertGreater(preview.json["pixels"], 0)
        marker_png = base64.b64decode(preview.json["image"].split(",", 1)[1])
        marker = Image.open(BytesIO(marker_png))
        self.assertEqual(marker.getpixel((98, 90)), (169, 194, 208))

        for exam_id in (prior_id, current_id):
            saved = self.client.post("/api/roi", json={
                "exam_id": exam_id, "index": 10, "seed": [104, 90],
                "fraction": .65, "label": "纵隔示意病灶",
            })
            self.assertEqual(saved.status_code, 200, saved.get_json())

        current = self.client.get("/api/state", query_string={"exam_id": current_id}).json
        prior = self.client.get("/api/state", query_string={"exam_id": prior_id}).json
        current_lesion = current["lesions"][0]["lesion_id"]
        prior_lesion = prior["lesions"][0]["lesion_id"]
        assessment = current["assessments"][current_lesion]
        self.assertTrue(assessment["fingerprint"])
        confirmed_assessment = self.client.post("/api/assessment/confirm", json={
            "exam_id": current_id, "lesion_id": current_lesion,
            "fingerprint": assessment["fingerprint"], "score": "4",
            "category": "PMR", "reviewer": "test-doctor", "reason": "影像复核",
        })
        self.assertEqual(confirmed_assessment.status_code, 200, confirmed_assessment.get_json())
        self.assertEqual(self.client.get("/api/state").json["assessments"][current_lesion]["confirmed"]["score"], "4")
        response = self.client.post("/api/pair", json={
            "exam_id": current_id, "lesion_id": current_lesion,
            "prior_lesion_id": prior_lesion,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNotNone(response.json["rows"][0]["delta_suv"])
        self.assertIsNotNone(response.json["rows"][0]["delta_spd_pct"])
        self.assertTrue(response.json["assessments"][current_lesion]["stale"])

        report = self.client.get("/api/report", query_string={"exam_id": current_id})
        self.assertEqual(report.status_code, 200)
        self.assertIn("原型·不可用于临床诊疗决策", report.json["generated"])
        self.assertEqual(self.client.get("/api/report/export", query_string={"exam_id": current_id}).status_code, 200)

    def test_rejects_outside_import_and_bad_slice(self):
        self.client.post("/api/demo", json={})
        self.assertEqual(self.client.post("/api/import", json={"path": str(ROOT)}).status_code, 400)
        self.assertEqual(self.client.get("/api/image?modality=pet&index=999").status_code, 400)

    def test_browser_folder_upload_uses_dicom_validation(self):
        self.client.post("/api/demo", json={})
        source = Path(self.temp.name) / "data/fixtures/petfollow-demo-v2"
        files = MultiDict([("files", (BytesIO(path.read_bytes()), f"selected/{path.relative_to(source).as_posix()}"))
                           for path in source.rglob("*.dcm")])
        response = self.client.post("/api/upload", data=files, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.client.get("/api/state").json["exam"]["exam_id"], response.json["exam_id"])
        bad = self.client.post("/api/upload", data={"files": (BytesIO(b"bad"), "../escape.dcm")},
                               content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
