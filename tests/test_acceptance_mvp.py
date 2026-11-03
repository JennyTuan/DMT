"""Run the hospital-trial prototype's local acceptance path with synthetic DICOM."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

import pydicom
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QFileDialog, QTableWidget, QWidget

from main import MainWindow
from fixtures.make_demo import make_demo


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.window = MainWindow(data_root=self.root)
        self.addCleanup(self.window.close)
        self.window.show()

    def loaded(self):
        deadline = time.monotonic() + 30
        while self.window.import_task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.window.import_task)
        self.assertIsNotNone(self.window.store, self.window.message.text())

    def choose_prior(self, target):
        def choose():
            dialog = self.app.activeModalWidget()
            choice = dialog.findChild(QComboBox)
            choice.setCurrentIndex(choice.findData(target))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0, choose)
        self.window.prior_button.click()

    def seed_demo_roi(self):
        canvas = self.window.pet.findChild(QWidget, "sliceCanvas")
        side = min(canvas.width(), canvas.height())
        point = QPoint(round((canvas.width() - side) / 2 + 104.5 / 192 * side),
                       round((canvas.height() - side) / 2 + 90.5 / 192 * side))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)

    def test_demo_seed_measure_link_pair_gate_draft_and_export(self):
        w = self.window
        w.demo_button.click()
        self.loaded()
        prior_id = w.store.bundle["exam"]["prior_exam_id"]
        w.new_button.click()
        self.seed_demo_roi()
        w.label_edit.setText("纵隔验收条目")
        w.save_button.click()
        lesion_id = w.lesion_id
        m = next(m for m in w.store.bundle["measurements"] if m["lesion_id"] == lesion_id)
        self.assertAlmostEqual(m["suv_max"], 9.3492, places=4)
        self.assertAlmostEqual(m["longest_diameter_mm"], 12.90349, places=4)
        self.assertEqual(m["state"], "proposed")
        self.assertTrue((self.root / m["roi_ref"]).is_file())

        self.choose_prior(None)
        self.choose_prior(prior_id)
        panel = w.comparison
        current_row = next(i for i, r in enumerate(panel.rows) if r["lesion_id"] == lesion_id)
        panel.table.selectRow(current_row * 4)
        panel.candidates.setCurrentIndex(1)
        panel.pair_button.click()
        self.assertTrue(panel.unpair_button.isEnabled(), w.message.text())
        # The other current finding is deliberately left out of this comparison.
        panel.table.selectRow(0)
        panel.skip_button.click()
        self.assertIn("取消", panel.skip_button.text())
        panel.skip_button.click()
        self.assertFalse(w.pairing.quality_snapshot()[2])
        panel.skip_button.click()
        self.assertTrue(w.banner.isVisible())
        export = self.root / "随访示意草稿.md"
        def write_report():
            dialog = self.app.activeModalWidget()
            dialog.description.setPlainText("人工核对同层量测。")
            dialog.regenerate_button.click()
            dialog.save_button.click()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "Markdown")):
                dialog.export_button.click()
            dialog.reject()
        QTimer.singleShot(0, write_report)
        w.report_button.click()
        text = export.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "原型·不可用于临床诊疗决策")
        self.assertIn("纵隔验收条目", text)
        self.assertIn("人工核对同层量测。", text)
        self.assertNotRegex(text, r"(?i)deauville|lugano|\b(?:CMR|PMR|NMR|PMD)\b|缓解|恶性|辅助诊断")
        exam_id = w.store.exam_id
        for path in (f"exams/{exam_id}.json", f"exams/{prior_id}.json",
                     f"measurements/{exam_id}.history.json", f"pairings/{exam_id}.json",
                     f"reports/{exam_id}.json", f"gates/{exam_id}.json"):
            self.assertTrue((self.root / "data" / path).is_file(), path)
        gates = json.loads((self.root / "data/gates" / (exam_id + ".json")).read_text(encoding="utf-8"))
        self.assertEqual({r["gate_id"] for r in gates["results"]},
                         {"AC_MISSING", "SUV_META_MISSING", "CT_ALIGN_FAIL", "ROI_EMPTY", "PRIOR_BROKEN",
                          "TRACK_INCOMPLETE", "PROTOTYPE_BANNER", "BANNED_TERMS"})
        self.assertFalse(any(r["level"] in ("review", "block", "warn") for r in gates["results"]))

    def test_uncorrected_dicom_creates_review_and_persists_reason(self):
        w = self.window
        source = self.root / "source"
        make_demo(source, quantitative=True)
        series = source / "petfollow-demo-v2"
        for path in (series / "PT").glob("*.dcm"):
            ds = pydicom.dcmread(path)
            ds.CorrectedImage = ["DECY"]
            ds.save_as(path, enforce_file_format=True)
        w.open_directory(series)
        self.loaded()
        self.seed_demo_roi()
        w.save_button.click()
        m = w.store.bundle["measurements"][0]
        self.assertIsNone(m["suv_max"])
        self.assertIsNotNone(m["longest_diameter_mm"])
        self.assertEqual([a["to"] for a in m["audit"]], ["proposed", "needs_review"])
        gate_file = self.root / "data/gates" / (w.store.exam_id + ".json")
        rows = json.loads(gate_file.read_text(encoding="utf-8"))["results"]
        ac, = [r for r in rows if r["gate_id"] == "AC_MISSING" and r["target_id"] == m["measurement_id"]]
        self.assertEqual(ac["level"], "review")
        self.assertIn("校正", ac["message"])
        self.assertTrue(w.review_reason.isVisible())

    def test_missing_prior_is_visible_blocks_export_and_can_be_cleared(self):
        w = self.window
        w.demo_button.click()
        self.loaded()
        w.tabs.setCurrentWidget(w.comparison)
        prior_id = w.store.bundle["exam"]["prior_exam_id"]
        # Model a moved prior in this isolated demo store, after it was displayed.
        path = self.root / "data/exams" / (prior_id + ".json")
        path.rename(path.with_suffix(".moved"))
        failures = []
        def inspect_gate():
            dialog = self.app.activeModalWidget()
            table = dialog.findChild(QTableWidget, "qualityGateTable")
            failures.extend(table.item(i, 1).text() for i in range(table.rowCount())
                            if table.item(i, 0).text() == "阻断")
            dialog.accept()
        QTimer.singleShot(0, inspect_gate)
        w.quality_button.click()
        self.assertIn("PRIOR_BROKEN", failures)
        target = self.root / "不可导出.md"
        checked = []
        def try_export():
            dialog = self.app.activeModalWidget()
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "Markdown")) as chooser:
                dialog.export_button.click()
            checked.append((chooser.called, dialog.gates.toPlainText()))
            dialog.reject()
        QTimer.singleShot(0, try_export)
        w.report_button.click()
        self.assertEqual(len(checked), 1)
        self.assertFalse(checked[0][0])
        self.assertIn("PRIOR_BROKEN", checked[0][1])
        self.assertFalse(target.exists())
        self.choose_prior(None)
        self.assertIsNone(w.store.bundle["exam"]["prior_exam_id"], w.message.text())
        gates = json.loads((self.root / "data/gates" / (w.store.exam_id + ".json")).read_text(encoding="utf-8"))
        self.assertFalse(any(row["level"] == "block" for row in gates["results"]))


if __name__ == "__main__":
    unittest.main()
