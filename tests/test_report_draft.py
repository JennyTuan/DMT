import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from report_draft import ReportDraft, comparison_rows
from report_ui import ReportDialog


def example(visit):
    path = ROOT / "schemas/v0/examples" / f"demo_001_{visit}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.current = example("followup")
        self.prior = example("baseline")
        for bundle in self.current, self.prior:
            bundle["lesions"][0]["lesion_track_id"] = "track-001"

    def test_comparison_joins_only_unique_tracks_and_keeps_missing_values(self):
        self.current["measurements"][0].update(suv_max=0., longest_diameter_mm=None,
                                               state="needs_review")
        self.prior["measurements"][0].update(suv_max=2.5, longest_diameter_mm=8.)
        first_lesion = self.current["lesions"][0]
        self.current["lesions"].append(dict(first_lesion, lesion_id="c2", lesion_track_id=None))
        self.prior["lesions"].append(dict(self.prior["lesions"][0], lesion_id="p2", lesion_track_id=None))
        matched, new, prior_only = comparison_rows(self.current, self.prior)
        self.assertEqual((matched["current_suv"], matched["prior_suv"], matched["delta_suv"]),
                         (0., 2.5, -2.5))
        self.assertEqual((matched["current_mm"], matched["prior_mm"], matched["delta_mm"]),
                         (None, 8., None))
        self.assertEqual((matched["status"], matched["prior_status"]), ("needs_review", "proposed"))
        self.assertEqual((new["lesion_id"], new["prior_lesion_id"], new["delta_suv"]), ("c2", None, None))
        self.assertEqual((prior_only["lesion_id"], prior_only["prior_lesion_id"]), (None, "p2"))

    def test_duplicate_tracks_on_either_side_never_pair_even_with_identical_labels(self):
        for side in self.current, self.prior:
            side["lesions"].append(dict(side["lesions"][0], lesion_id="duplicate"))
            rows = comparison_rows(self.current, self.prior)
            self.assertEqual(len(rows), 3)
            self.assertFalse(any(r["lesion_id"] and r["prior_lesion_id"] for r in rows))
            self.assertTrue(all(r["delta_suv"] is None for r in rows))
            side["lesions"].pop()

    def test_unlinked_foreign_and_later_exams_cannot_supply_prior_data(self):
        for field, invalid in (("exam_id", "different"), ("patient_pseudo_id", "another"),
                               ("study_datetime", "2029-01-01T00:00:00Z")):
            original = self.prior["exam"][field]
            self.prior["exam"][field] = invalid
            row, = comparison_rows(self.current, self.prior)
            self.assertEqual((row["prior_lesion_id"], row["prior_suv"], row["delta_suv"]), (None, None, None))
            self.prior["exam"][field] = original
        self.current["exam"]["prior_exam_id"] = None
        for prior in self.prior, None:
            row, = comparison_rows(self.current, prior)
            self.assertIsNone(row["prior_lesion_id"])

    def test_save_regenerate_and_export_a_readable_snapshot(self):
        self.current["lesions"].append(dict(self.current["lesions"][0], lesion_id="unpaired",
                                            label="左肺", lesion_track_id=None))
        draft = ReportDraft(self.root, self.current, self.prior)
        draft.description = "纵隔本次手工描记。\n请核对层面。"
        draft.save(self.current, self.prior)
        stored = self.root / "data/reports/ex_lymphoma_demo_followup.json"
        saved = json.loads(stored.read_text(encoding="utf-8"))
        self.assertEqual((saved["version"], saved["exam_id"], saved["description"]),
                         (1, self.current["exam"]["exam_id"], draft.description))
        self.current["measurements"][0]["suv_max"] = 7.25
        reopened = ReportDraft(self.root, self.current, self.prior)
        self.assertEqual(reopened.generated, saved["generated"])
        with self.assertRaisesRegex(ValueError, "重新生成"):
            reopened.save(self.current, self.prior)
        target = self.root / "草稿.md"
        with self.assertRaisesRegex(ValueError, "重新生成"):
            reopened.export(target, self.current, self.prior)
        self.assertFalse(target.exists())
        reopened.regenerate(self.current, self.prior)
        self.assertEqual(reopened.description, draft.description)
        reopened.export(target, self.current, self.prior)
        result = target.read_text(encoding="utf-8")
        self.assertTrue(result.startswith("原型·不可用于临床诊疗决策\n"))
        for part in ("demo_001", "ex_lymphoma_demo_followup", "ex_lymphoma_demo_baseline",
                     "2026-04-10", "2026-01-10", "示意数据", "track-001", "SUVmax",
                     "最长径", "7.25", "-5.15", "左肺", "—", "proposed", draft.description):
            self.assertIn(part, result)
        for term in ("Deauville", "Lugano", "CMR", "PMR", "NMR", "PMD", "缓解", "良恶性", "辅助诊断"):
            self.assertNotIn(term, result)
        reopened.save(self.current, self.prior)
        self.assertFalse(reopened.dirty)

    def test_stale_editor_and_unrelated_files_are_preserved(self):
        first = ReportDraft(self.root, self.current, self.prior)
        stale = ReportDraft(self.root, self.current, self.prior)
        first.description = "先保存的描述"
        first.save(self.current, self.prior)
        stale.description = "另一窗口的描述"
        with self.assertRaisesRegex(ValueError, "重新打开"):
            stale.save(self.current, self.prior)
        self.assertEqual(ReportDraft(self.root, self.current, self.prior).description, first.description)
        for name in ("source.json", "README.md"):
            path = self.root / name
            path.write_bytes(b"original")
            with self.assertRaises((OSError, ValueError)):
                stale.export(path, self.current, self.prior)
            self.assertEqual(path.read_bytes(), b"original")
        original = first.path.read_bytes()
        with self.assertRaises(ValueError):
            first.regenerate(self.prior, None)
        self.assertEqual(first.path.read_bytes(), original)

    def test_published_text_stays_descriptive_without_losing_editor_text(self):
        draft = ReportDraft(self.root, self.current, self.prior)
        target = self.root / "草稿.md"
        for text in ("Deauville 4", "Lugano", "完全代谢缓解", "恶性", "辅助诊断", "PMR"):
            draft.description = text
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "描述性"):
                    draft.export(target, self.current, self.prior)
                with self.assertRaisesRegex(ValueError, "描述性"):
                    draft.save(self.current, self.prior)
                self.assertEqual(draft.description, text)
                self.assertFalse(draft.path.exists())
                self.assertFalse(target.exists())

    def test_dialog_preserves_edits_through_refresh_and_handles_export_cancel_and_close(self):
        dialog = ReportDialog(None, self.root, lambda: (self.current, self.prior))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.assertTrue(dialog.banner.isVisible())
        self.assertTrue(dialog.generated.isReadOnly())
        dialog.description.setPlainText("人工核对两次层面。")
        with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            dialog.export_button.click()
        self.assertFalse(dialog.draft.path.exists())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.close()
        self.assertTrue(dialog.isVisible())
        self.current["measurements"][0]["suv_max"] = 8.5
        dialog.regenerate_button.click()
        self.assertIn("8.5", dialog.generated.toPlainText())
        self.assertEqual(dialog.description.toPlainText(), "人工核对两次层面。")
        dialog.save_button.click()
        self.assertTrue(dialog.draft.path.exists())
        dialog.reject()
        self.assertFalse(dialog.isVisible())
        reopened = ReportDialog(None, self.root, lambda: (self.current, self.prior))
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.description.toPlainText(), "人工核对两次层面。")
        reopened.description.setPlainText("仅写入此次导出。")
        target = self.root / "人工导出"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "Markdown (*.md)")):
            reopened.export_button.click()
        self.assertIn("仅写入此次导出。", target.with_suffix(".md").read_text(encoding="utf-8"))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            reopened.reject()
        self.assertEqual(ReportDraft(self.root, self.current, self.prior).description, "人工核对两次层面。")


if __name__ == "__main__":
    unittest.main()
