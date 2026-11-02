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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from main import MainWindow


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
            QTest.mouseClick(window.demo_button, Qt.MouseButton.LeftButton)
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
            first = window.store.bundle["measurements"][0]["roi_ref"]
            self.assertTrue((root / first).is_file())
            QTest.mouseClick(window.erase_button, Qt.MouseButton.LeftButton)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
            measurement = window.store.bundle["measurements"][0]
            self.assertTrue(measurement["edited"])
            self.assertIn("人工修订", window.audit_info.text())
            self.assertNotEqual(first, measurement["roi_ref"])
            self.assertTrue((root / first).is_file())
            self.assertIsNone(measurement["suv_max"])
            self.assertIsNone(measurement["longest_diameter_mm"])
            self.assertEqual(measurement["state"], "proposed")
            self.assertEqual(len(measurement["audit"]), 1)
            self.assertTrue(window.banner.isVisible())

            with patch.object(QFileDialog, "getExistingDirectory", return_value=str(window.source_dir)):
                QTest.mouseClick(window.import_button, Qt.MouseButton.LeftButton)
                self.wait_for_import(window)
            self.assertEqual(window.table.rowCount(), 1)
            self.assertEqual(window.store.bundle["measurements"][0], measurement)
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


if __name__ == "__main__":
    unittest.main()
