import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pydicom

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "petfollow-lymphoma"))

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QLineEdit, QTableWidget, QWidget

from main import MainWindow
from fixtures.make_demo import make_demo
from imaging import load_study
from roi_store import StudyStore, grow_region


class WorkstationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for_import(self, window):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if window.import_task is None:
                break
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(window.import_task)
        self.assertIsNotNone(window.store, window.message.text())

    def test_import_edit_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            window = MainWindow(data_root=root)
            def close():
                with patch.object(window, "can_discard", return_value=True):
                    window.close()
            self.addCleanup(close)
            window.show()
            self.assertIn("淋巴瘤 PET 随访原型", window.windowTitle())
            self.assertEqual(window.banner.text(), "原型·不可用于临床诊疗决策")
            # Start with a standalone, unannotated quantitative study for ROI creation.
            source = root / "source"
            make_demo(source, quantitative=True)
            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(source)):
                QTest.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
                self.wait_for_import(window)
            self.assertTrue(window.synthetic_badge.isVisible())
            self.assertTrue(window.store.bundle["exam"]["is_synthetic"])
            self.assertEqual(window.table.rowCount(), 0)

            # The fixture's central PET slice has a focus at source column 104, row 90.
            canvas = window.pet.findChild(QWidget, "sliceCanvas")
            side = min(canvas.width(), canvas.height())
            point = QPoint(round((canvas.width() - side) / 2 + 104.5 / 192 * side),
                           round((canvas.height() - side) / 2 + 90.5 / 192 * side))
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
            self.assertTrue(window.save_button.isEnabled(), window.message.text())
            window.label_edit.setText("纵隔病灶")
            QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
            self.assertEqual(window.table.rowCount(), 1)
            initial = window.store.bundle["measurements"][0]
            first = initial["roi_ref"]
            self.assertTrue((root / first).is_file())
            self.assertGreater(initial["suv_max"], 0)
            self.assertAlmostEqual(initial["suv_max"], 9.3492437, places=5)
            self.assertGreater(initial["longest_diameter_mm"], 0)
            self.assertEqual(len(window.store.value_history(window.lesion_id)), 2)
            QTest.mouseClick(window.erase_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
            measurement = window.store.bundle["measurements"][0]
            self.assertTrue(measurement["edited"])
            self.assertIn("人工修订", window.audit_info.text())
            self.assertNotEqual(first, measurement["roi_ref"])
            self.assertTrue((root / first).is_file())
            self.assertLess(measurement["suv_max"], initial["suv_max"])
            self.assertGreater(measurement["longest_diameter_mm"], 0)
            self.assertEqual(measurement["state"], "proposed")
            self.assertEqual(len(measurement["audit"]), 1)
            self.assertTrue(window.banner.isVisible())
            self.assertEqual(len(window.store.value_history(window.lesion_id)), 4)

            for column, value in ((1, "7.25"), (2, "13.5")):
                def enter_value():
                    dialog = QApplication.activeModalWidget()
                    dialog.findChild(QLineEdit, "measurementValue").setText(value)
                    dialog.findChild(QLineEdit, "changeNote").setText("人工核对示意值")
                    dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Save).click()
                cell = window.table.visualItemRect(window.table.item(0, column)).center()
                QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
                QTimer.singleShot(0, enter_value)
                QTest.mouseDClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=cell)
                self.assertEqual(float(window.table.item(0, column).text()), float(value))
            measurement = window.store.bundle["measurements"][0]
            self.assertEqual((measurement["suv_max"], measurement["longest_diameter_mm"]), (7.25, 13.5))
            self.assertEqual(len(measurement["audit"]), 1)
            history = window.store.value_history(window.lesion_id)
            self.assertEqual(len(history), 6)
            self.assertEqual([e["actor"] for e in history[-2:]], ["user", "user"])
            visible_history = []
            def inspect_history():
                dialog = QApplication.activeModalWidget()
                table = dialog.findChild(QTableWidget)
                visible_history.append((table.rowCount(), table.item(0, 5).text()))
                dialog.accept()
            QTimer.singleShot(0, inspect_history)
            window.history_button.click()
            self.assertEqual(visible_history, [(6, "人工核对示意值")])

            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(window.source_dir)):
                QTest.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
                self.wait_for_import(window)
            self.assertEqual(window.table.rowCount(), 1)
            self.assertEqual(window.store.bundle["measurements"][0], measurement)
            self.assertEqual(window.store.value_history(measurement["lesion_id"]), history)
            window.table.selectRow(0)
            self.assertIsNotNone(window.mask)
            self.assertFalse(window.mask[90, 104])
            self.assertEqual(window.label_edit.text(), "纵隔病灶")
            before = window.store.bundle
            window.open_directory(root / "missing-source")
            self.wait_for_import(window)
            self.assertIn("导入失败", window.message.text())
            self.assertEqual(window.store.bundle, before)
            window.close()

    def test_uncorrected_pack02_roi_is_backfilled_once_and_flagged_in_list(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            make_demo(source)
            for path in (source / "petfollow-demo-v1" / "PT").glob("*.dcm"):
                ds = pydicom.dcmread(path)
                del ds.CorrectedImage
                ds.save_as(path, enforce_file_format=True)
            study = load_study(source)
            self.assertFalse(study.exam["attenuation_corrected"])
            legacy = StudyStore(root, study.exam)
            mask = grow_region(study.pet[10], 104, 90, 0.65)
            lesion = legacy.save_roi(mask, slice_index=10, sop_uid=study.pet_uids[10],
                                     seed=(104, 90), fraction=0.65, label="示意病灶")
            original_ref = legacy.bundle["measurements"][0]["roi_ref"]
            window = MainWindow(data_root=root)
            self.addCleanup(window.close)
            window.show()
            for _ in range(2):
                window.open_directory(source)
                self.wait_for_import(window)
                m = window.store.bundle["measurements"][0]
                self.assertEqual(m["roi_ref"], original_ref)
                self.assertIsNone(m["suv_max"])
                self.assertGreater(m["longest_diameter_mm"], 0)
                self.assertEqual(m["state"], "needs_review")
                self.assertEqual([row["to"] for row in m["audit"]], ["proposed", "needs_review"])
                self.assertEqual(len(window.store.value_history(lesion)), 2)
                self.assertEqual(window.table.item(0, 3).text(), "需复核")
                window.table.selectRow(0)
                self.assertTrue(window.review_reason.isVisible())
                self.assertIn("缺/未衰减校正，SUV 仅供复核", window.review_reason.text())
                self.assertTrue(window.banner.isVisible())
            window.close()

    def test_reopening_same_sops_without_weight_flags_only_suv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            window = MainWindow(data_root=root)
            self.addCleanup(window.close)
            window.show()
            window.demo_button.click()
            self.wait_for_import(window)
            window.table.selectRow(0)
            lesion_id = window.lesion_id
            window.store.edit_value(lesion_id, "longest_diameter_mm", 11.5, "人工核对测径")
            source = window.source_dir
            for path in (source / "PT").glob("*.dcm"):
                ds = pydicom.dcmread(path)
                del ds.PatientWeight
                ds.save_as(path, enforce_file_format=True)
            for _ in range(2):
                window.open_directory(source)
                self.wait_for_import(window)
                m = window.store.bundle["measurements"][0]
                self.assertIsNone(m["suv_max"])
                self.assertEqual(m["longest_diameter_mm"], 11.5)
                self.assertEqual(m["state"], "needs_review")
                self.assertEqual(len(m["audit"]), 2)
                window.table.selectRow(0)
                self.assertIn("体重", window.review_reason.text())
                history = window.store.value_history(lesion_id)
                self.assertEqual(len(history), 4)
                self.assertEqual((history[-1]["field"], history[-1]["to"]), ("suv_max", None))
            window.close()


if __name__ == "__main__":
    unittest.main()
