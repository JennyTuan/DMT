import os
import sys
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "petfollow-lymphoma"))
from viewport import SliceView


class SliceViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = SliceView("CT")
        self.canvas = self.view.findChild(QWidget, "sliceCanvas")
        self.view.resize(460, 450)
        self.view.show()
        self.app.processEvents()
        self.addCleanup(self.view.close)

    def test_click_and_drag_follow_anisotropic_pixels_after_resize(self):
        clicks, moves = [], []
        self.view.pixel_clicked.connect(lambda x, y: clicks.append((x, y)))
        self.view.pixel_dragged.connect(lambda x, y: moves.append((x, y)))
        # Eight wide columns and four tall rows form a physical square.
        self.view.set_volume(np.zeros((1, 4, 8), np.float32), spacing=(2, 1))
        for width, height in [(600, 370), (370, 600)]:
            self.view.resize(width, height)
            self.app.processEvents()
            w, h = self.canvas.width(), self.canvas.height()
            side = min(w, h)
            left, top = (w - side) / 2, (h - side) / 2
            start = QPoint(round(left + side * 2.5 / 8), round(top + side * 1.5 / 4))
            end = QPoint(round(left + side * 6.5 / 8), round(top + side * 3.5 / 4))
            QTest.mouseClick(self.canvas, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
            QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(self.canvas, end)
            QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(clicks, [(2, 1), (2, 1)])
        self.assertEqual(moves, [(6, 3), (6, 3)])

    def test_wheel_navigation_and_slice_scoped_outline(self):
        self.view.set_volume(np.full((3, 8, 8), 40, np.float32))
        self.assertEqual(self.view.index, 1)
        clean = self.canvas.grab().toImage()
        mask = np.zeros((8, 8), bool)
        mask[2:6, 2:6] = True
        self.view.set_mask(mask)
        outlined = self.canvas.grab().toImage()
        self.assertNotEqual(clean, outlined)
        center = self.canvas.rect().center()
        self.assertEqual(clean.pixelColor(center), outlined.pixelColor(center))
        changes = []
        self.view.slice_changed.connect(changes.append)
        event = QWheelEvent(QPointF(center), QPointF(self.canvas.mapToGlobal(center)),
                            QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        self.app.sendEvent(self.canvas, event)
        self.assertEqual(self.view.index, 2)
        self.view.set_index(200)
        self.assertEqual(changes, [2])
        self.assertEqual(self.canvas.grab().toImage(), clean)

    def test_window_level_and_photometric_inversion(self):
        volume = np.full((1, 8, 8), 40, np.float32)
        self.view.set_volume(volume)
        center = self.canvas.rect().center()
        level = self.view.findChild(QDoubleSpinBox, "windowLevel")
        level.setValue(-1200)
        self.assertEqual(self.canvas.grab().toImage().pixelColor(center).red(), 255)
        self.view.set_volume(volume, inverted=True)
        level.setValue(-1200)
        self.assertEqual(self.canvas.grab().toImage().pixelColor(center).red(), 0)


if __name__ == "__main__":
    unittest.main()
