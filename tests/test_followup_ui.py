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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QFileDialog

from main import MainWindow


class FollowupWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def loaded(self, window):
        deadline = time.monotonic() + 30
        while window.import_task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(window.import_task)
        self.assertIsNotNone(window.store, window.message.text())

    def pick_prior(self, window, exam_id):
        def choose():
            dialog = self.app.activeModalWidget()
            combo = dialog.findChild(QComboBox)
            combo.setCurrentIndex(combo.findData(exam_id))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0, choose)
        window.prior_button.click()

    def test_demo_switch_link_pair_unlink_and_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(data_root=Path(folder))
            self.addCleanup(window.close)
            window.show()
            window.demo_button.click()
            self.loaded(window)
            current = window.store.bundle
            prior_id = current["exam"]["prior_exam_id"]
            self.assertTrue(prior_id)
            self.assertTrue(current["lesions"])
            self.assertTrue(window.banner.isVisible())
            window.tabs.setCurrentWidget(window.comparison)
            panel = window.comparison
            self.assertFalse(panel.pair_button.isEnabled())
            panel.candidates.setCurrentIndex(1)
            panel.pair_button.click()
            current, prior = window.pairing.snapshot()
            current_lesion = current["lesions"][0]
            track = current_lesion["lesion_track_id"]
            self.assertTrue(track)
            self.assertEqual(track, prior["lesions"][0]["lesion_track_id"])
            self.assertAlmostEqual(float(panel.table.item(1, 3).text()),
                                   current["measurements"][0]["suv_max"] - prior["measurements"][0]["suv_max"],
                                   places=3)
            export = Path(folder) / "随访草稿.md"
            def write_report():
                dialog = self.app.activeModalWidget()
                dialog.description.setPlainText("两次均记录纵隔病灶，层面已经核对。")
                dialog.regenerate_button.click()
                dialog.save_button.click()
                with patch.object(QFileDialog, "getSaveFileName", return_value=(str(export), "Markdown")):
                    dialog.export_button.click()
                dialog.reject()
            QTimer.singleShot(0, write_report)
            window.report_button.click()
            saved = export.read_text(encoding="utf-8")
            self.assertTrue(saved.startswith("原型·不可用于临床诊疗决策\n"))
            for value in (current["exam"]["exam_id"], prior_id, track, "9.3492", "12.294", "层面已经核对"):
                self.assertIn(value, saved)
            panel.unpair_button.click()
            self.assertEqual(panel.table.item(1, 3).text(), "—")
            panel.track_button.click()
            self.assertTrue(window.store.bundle["lesions"][0]["lesion_track_id"])
            window.switch_demo_button.click()
            self.loaded(window)
            self.assertEqual(window.store.exam_id, prior_id)
            self.assertIsNone(window.store.bundle["exam"]["prior_exam_id"])
            window.switch_demo_button.click()
            self.loaded(window)
            self.assertEqual(window.store.exam_id, current["exam"]["exam_id"])
            self.pick_prior(window, None)
            self.assertIsNone(window.store.bundle["exam"]["prior_exam_id"])
            window.demo_button.click()
            self.loaded(window)
            self.assertIsNone(window.store.bundle["exam"]["prior_exam_id"])
            self.pick_prior(window, prior_id)
            self.assertEqual(window.store.bundle["exam"]["prior_exam_id"], prior_id)
            window.close()


if __name__ == "__main__":
    unittest.main()
