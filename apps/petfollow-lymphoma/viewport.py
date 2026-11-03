"""Independent PET/CT slice display and image-space pointer input."""

import math

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, qRgb
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QSizePolicy,
    QSlider, QStyle, QStyleOptionComboBox, QStyleOptionSpinBox, QVBoxLayout, QWidget,
)

from visuals import icon


# PET intensity rises from black through copper to ivory.
_PET_STOPS = [(0, 0, 0), (62, 33, 25), (146, 79, 47), (222, 155, 86), (255, 251, 224)]
_PET_CHANNELS = np.array([np.interp(np.linspace(0, 4, 256), range(5), channel)
                          for channel in zip(*_PET_STOPS)]).round().astype(int)
_PET_PALETTE = [qRgb(int(r), int(g), int(b)) for r, g, b in _PET_CHANNELS.T]


def _outline(mask: np.ndarray) -> QPainterPath:
    """Trace runs of exposed pixel edges, including holes and the image border."""
    path = QPainterPath()
    padded = np.pad(mask, 1)
    horizontal = padded[1:, 1:-1] != padded[:-1, 1:-1]
    vertical = (padded[1:-1, 1:] != padded[1:-1, :-1]).T
    for edges, transpose in ((horizontal, False), (vertical, True)):
        endpoints = np.argwhere(np.diff(np.pad(edges, ((0, 0), (1, 1))), axis=1))
        for (line, start), (_, end) in endpoints.reshape(-1, 2, 2).tolist():
            if transpose:
                path.moveTo(line, start)
                path.lineTo(line, end)
            else:
                path.moveTo(start, line)
                path.lineTo(end, line)
    return path


class _SliceCanvas(QWidget):
    clicked = Signal(int, int)
    dragged = Signal(int, int)
    stepped = Signal(int)

    def __init__(self, modality: str):
        super().__init__()
        self.setObjectName("sliceCanvas")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(100, 90)
        self._modality = modality
        self.image = QImage()
        self.spacing = (1.0, 1.0)
        self.outline = QPainterPath()
        self._last_pixel = None
        self._wheel_remainder = 0.0

    def _image_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        h = self.image.height() * self.spacing[0]
        w = self.image.width() * self.spacing[1]
        scale = min(self.width() / w, self.height() / h)
        w, h = w * scale, h * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#05080c"))
        target = self._image_rect()
        if target.isEmpty():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx, cy = self.width() / 2, self.height() / 2
            icon("layers", "#678093", 34).paint(painter, QRect(round(cx - 17), round(cy - 30), 34, 34))
            painter.setPen(QColor("#93a2b1"))
            painter.drawText(QRectF(0, cy + 8, self.width(), 25), Qt.AlignmentFlag.AlignCenter,
                             f"等待导入 {self._modality} 序列")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self.image)
        if not self.outline.isEmpty():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(target.topLeft())
            painter.scale(target.width() / self.image.width(), target.height() / self.image.height())
            pen = QPen(QColor("#67e1d1"), 1.6)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPath(self.outline)

    def _pixel_at(self, point: QPointF):
        target = self._image_rect()
        if target.isEmpty():
            return None
        u = (point.x() - target.left()) / target.width()
        v = (point.y() - target.top()) / target.height()
        if 0 <= u < 1 and 0 <= v < 1:
            return int(u * self.image.width()), int(v * self.image.height())
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pixel = self._pixel_at(event.position())
            if self._last_pixel is not None:
                self.clicked.emit(*self._last_pixel)

    def mouseMoveEvent(self, event):
        if self._last_pixel is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        pixel = self._pixel_at(event.position())
        if pixel is not None and pixel != self._last_pixel:
            self._last_pixel = pixel
            self.dragged.emit(*pixel)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pixel = None

    def wheelEvent(self, event):
        # Accumulate partial detents from high-resolution wheels and touchpads.
        delta = event.angleDelta().y()
        self._wheel_remainder += delta / 120 if delta else event.pixelDelta().y() / 40
        steps = int(self._wheel_remainder)
        if steps:
            self._wheel_remainder -= steps
            self.stepped.emit(steps)
        event.accept()


class _PresetBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        options = QStyleOptionComboBox()
        self.initStyleOption(options)
        arrow = self.style().subControlRect(QStyle.CC_ComboBox, options, QStyle.SC_ComboBoxArrow, self)
        with QPainter(self) as painter:
            painter.translate(QRectF(arrow).center())
            painter.rotate(90)
            color = "#a5b7c6" if self.isEnabled() else "#586a79"
            icon("chevron", color, 14).paint(painter, QRect(-7, -7, 14, 14))


class _WindowSpinBox(QDoubleSpinBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        options = QStyleOptionSpinBox()
        self.initStyleOption(options)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor("#a5b7c6" if self.isEnabled() else "#586a79")
            painter.setPen(QPen(color, 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for button in (QStyle.SC_SpinBoxUp, QStyle.SC_SpinBoxDown):
                rect = self.style().subControlRect(QStyle.CC_SpinBox, options, button, self)
                center = QRectF(rect).center()
                painter.drawLine(center - QPointF(2.5, 0), center + QPointF(2.5, 0))
                if button == QStyle.SC_SpinBoxUp:
                    painter.drawLine(center - QPointF(0, 2.5), center + QPointF(0, 2.5))


class SliceView(QFrame):
    pixel_clicked = Signal(int, int)
    pixel_dragged = Signal(int, int)
    slice_changed = Signal(int)

    def __init__(self, modality: str, parent=None):
        super().__init__(parent)
        self.modality = modality.upper()
        if self.modality not in {"PET", "CT"}:
            raise ValueError("视口仅支持 PET 或 CT")
        self.setObjectName("sliceView")
        self._volume = None
        self._index = 0
        self._inverted = False
        self._presets = {}
        self._canvas = _SliceCanvas(self.modality)
        self._canvas.clicked.connect(self.pixel_clicked)
        self._canvas.dragged.connect(self.pixel_dragged)
        self._canvas.stepped.connect(lambda step: self.set_index(self.index + step))

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(1, 1, 1, 1)
        header = QFrame(objectName="sliceHeader")
        heading = QHBoxLayout(header)
        heading.setContentsMargins(11, 7, 11, 6)
        heading.setSpacing(8)
        tag = QLabel(self.modality)
        tag.setObjectName("sliceTag")
        tag.setProperty("isPet", self.modality == "PET")
        heading.addWidget(tag)
        heading.addWidget(QLabel("正电子图像" if self.modality == "PET" else "断层图像",
                                 objectName="sliceTitle"))
        heading.addStretch()
        self._matrix = QLabel(objectName="sliceMatrix")
        self._matrix.setToolTip("图像矩阵（列 × 行）")
        heading.addWidget(self._matrix)
        layout.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("windowToolbar")
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(10, 0, 10, 7)
        controls.setSpacing(5)
        self._preset = _PresetBox()
        self._preset.setPlaceholderText("预设")
        self._preset.setAccessibleName("显示预设")
        self._preset.setToolTip("显示预设")
        self._preset.setMinimumWidth(73)
        self._preset.setMaximumWidth(128)
        self._preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls.addWidget(self._preset, 1)
        controls.addStretch()
        self._width = _WindowSpinBox()
        self._level = _WindowSpinBox()
        self._width.setObjectName("windowWidth")
        self._level.setObjectName("windowLevel")
        for label, spin in (("窗宽", self._width), ("窗位", self._level)):
            caption = QLabel(label, objectName="windowCaption")
            caption.setBuddy(spin)
            controls.addWidget(caption)
            spin.setAccessibleName(label)
            spin.setToolTip(f"{label} · 可直接输入数值或按 ↑ ↓ 微调")
            spin.setAlignment(Qt.AlignmentFlag.AlignRight)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
            spin.setDecimals(0 if self.modality == "CT" else 2)
            spin.setRange(-1e12, 1e12)
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            spin.setMinimumWidth(65)
            spin.setMaximumWidth(112)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._manual_window)
            controls.addWidget(spin, 1)
        self._width.setMinimum(1.0 if self.modality == "CT" else 0.01)
        self._preset.currentIndexChanged.connect(self._apply_preset)
        toolbar.setEnabled(False)
        self._toolbar = toolbar
        layout.addWidget(toolbar)
        layout.addWidget(self._canvas, 1)

        navigation = QFrame(objectName="sliceNavigation")
        footer = QHBoxLayout(navigation)
        footer.setContentsMargins(11, 4, 11, 4)
        footer.setSpacing(8)
        footer.addWidget(QLabel("切片", objectName="windowCaption"))
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setAccessibleName(f"{self.modality} 切层")
        self._slider.setToolTip("拖动滑块切层，也可在图像上滚动鼠标滚轮")
        self._slider.setFixedHeight(22)
        self._slider.setRange(0, 0)
        self._slider.setEnabled(False)
        self._slider.valueChanged.connect(self.set_index)
        footer.addWidget(self._slider, 1)
        self._counter = QLabel("— / —", objectName="sliceCounter")
        self._counter.setToolTip("当前层 / 总层数")
        footer.addWidget(self._counter)
        layout.addWidget(navigation)
        self.setStyleSheet("""
            QFrame#sliceView { background: #111923; border: 1px solid #293642; border-radius: 6px; }
            QFrame#sliceHeader, QFrame#windowToolbar, QFrame#sliceNavigation {
                background: transparent; border: none;
            }
            QFrame#sliceView QLabel { background: transparent; border: none; color: #dfe6eb; }
            QFrame#sliceView QLabel#sliceTag {
                color: #93cef7; background: #203649; border-radius: 4px; padding: 2px 7px;
                font: bold 13px "Consolas";
            }
            QFrame#sliceView QLabel#sliceTag[isPet="true"] { color: #f6ca8d; background: #3a3024; }
            QFrame#sliceView QLabel#sliceTitle { font-size: 15px; font-weight: 600; }
            QFrame#sliceView QLabel#sliceMatrix { color: #91a3b4; font: 12px "Consolas"; }
            QFrame#sliceView QLabel#windowCaption { color: #a2b1bd; font-size: 12px; }
            QFrame#sliceView QComboBox, QFrame#sliceView QDoubleSpinBox {
                color: #dae4ea; background: #1c2835; border: 1px solid #2b3a49;
                border-radius: 4px; padding: 1px 5px; min-height: 21px;
            }
            QFrame#sliceView QComboBox { font-size: 12px; padding-right: 15px; }
            QFrame#sliceView QDoubleSpinBox { font: 13px "Consolas"; padding-right: 17px; }
            QFrame#sliceView QDoubleSpinBox QLineEdit {
                border: none; background: transparent; padding: 0;
                selection-background-color: #315955; selection-color: #f2fcfa;
            }
            QFrame#sliceView QComboBox:hover, QFrame#sliceView QDoubleSpinBox:hover {
                border-color: #4a6071; background: #22303e;
            }
            QFrame#sliceView QComboBox:focus, QFrame#sliceView QDoubleSpinBox:focus {
                border-color: #76dbca;
            }
            QFrame#sliceView QComboBox::drop-down { width: 17px; border: none; background: transparent; }
            QFrame#sliceView QComboBox::down-arrow, QFrame#sliceView QDoubleSpinBox::up-arrow,
            QFrame#sliceView QDoubleSpinBox::down-arrow { width: 0; height: 0; image: none; }
            QFrame#sliceView QDoubleSpinBox::up-button, QFrame#sliceView QDoubleSpinBox::down-button {
                width: 14px; border: none; background: transparent;
            }
            QFrame#sliceView QDoubleSpinBox::up-button:hover, QFrame#sliceView QDoubleSpinBox::down-button:hover {
                background: #314555;
            }
            QFrame#sliceView QComboBox:disabled, QFrame#sliceView QDoubleSpinBox:disabled {
                color: #81909f; background: #17212b; border-color: #23303d;
            }
            QFrame#sliceView QComboBox QAbstractItemView {
                color: #dee8ee; background: #1c2835; border: 1px solid #374857; padding: 3px;
                selection-background-color: #2c4b50; selection-color: #e2f4f1;
            }
            QFrame#sliceView QLabel#sliceCounter { font: 13px "Consolas"; color: #cbd9e2; }
            QFrame#sliceView QSlider { border: none; background: transparent; }
            QFrame#sliceView QSlider::groove:horizontal {
                height: 3px; border-radius: 1px; background: #344354;
            }
            QFrame#sliceView QSlider::sub-page:horizontal { background: #509f96; border-radius: 1px; }
            QFrame#sliceView QSlider::handle:horizontal {
                background: #80d8c9; width: 11px; margin: -4px 0; border-radius: 5px;
            }
            QFrame#sliceView QSlider::handle:horizontal:hover,
            QFrame#sliceView QSlider::handle:horizontal:focus { background: #b0f3e7; }
            QFrame#sliceView QSlider::sub-page:horizontal:disabled { background: #344354; }
            QFrame#sliceView QSlider::handle:horizontal:disabled { background: #506170; }
        """)

    @property
    def index(self) -> int:
        return self._index

    def set_volume(self, volume: np.ndarray, spacing=(1.0, 1.0), inverted=False):
        """Display [slice, row, column] intensities at row/column spacing in mm."""
        volume = np.asarray(volume)
        if volume.ndim != 3 or min(volume.shape) < 1:
            raise ValueError("影像须为非空的三维序列")
        row_mm, col_mm = map(float, spacing)
        if not all(math.isfinite(v) and v > 0 for v in (row_mm, col_mm)):
            raise ValueError("像素间距须为正数")
        self._volume = volume
        self._matrix.setText(f"{volume.shape[2]} × {volume.shape[1]}")
        self._canvas.spacing = row_mm, col_mm
        self._inverted = inverted
        self._canvas.outline = QPainterPath()
        if self.modality == "PET":
            # PET may arrive in counts or activity units. Size the display window
            # from a bounded sample and never attach a quantitative unit to it.
            sample = volume.flat[::max(1, math.ceil(volume.size / 150_000))]
            positive = sample[np.isfinite(sample) & (sample > 0)]
            high = max(0.01, float(np.percentile(positive, 99.5))) if positive.size else 1.0
            self._presets = {"标准窗": (high, high / 2), "窄窗": (high / 2, high / 4),
                             "宽窗": (high * 2, high)}
        else:
            self._presets = {"软组织": (400, 40), "肺窗": (1500, -600), "骨窗": (2000, 500)}
        with QSignalBlocker(self._preset):
            self._preset.clear()
            self._preset.addItems([*self._presets, "自定义"])
            self._preset.setCurrentIndex(0)
        previous = self._index
        self._index = volume.shape[0] // 2
        self._toolbar.setEnabled(True)
        with QSignalBlocker(self._slider):
            self._slider.setRange(0, volume.shape[0] - 1)
            self._slider.setValue(self._index)
        self._slider.setEnabled(volume.shape[0] > 1)
        self._update_counter()
        self._apply_preset()
        if previous != self._index:
            self.slice_changed.emit(self._index)

    def _apply_preset(self):
        preset = self._presets.get(self._preset.currentText())
        if preset:
            with QSignalBlocker(self._width), QSignalBlocker(self._level):
                self._width.setValue(preset[0])
                self._level.setValue(preset[1])
                step = max(self._width.minimum(), round(preset[0] / 100, self._width.decimals()))
                self._width.setSingleStep(step)
                self._level.setSingleStep(step)
            self._render_slice()

    def _manual_window(self):
        with QSignalBlocker(self._preset):
            self._preset.setCurrentText("自定义")
        self._render_slice()

    def _render_slice(self):
        if self._volume is None:
            return
        width = self._width.value()
        lower = self._level.value() - width / 2
        plane = self._volume[self._index]
        levels = np.clip((plane - lower) * (255 / width), 0, 255)
        pixels = np.ascontiguousarray(np.nan_to_num(levels, copy=False).astype(np.uint8))
        if self._inverted:
            np.subtract(255, pixels, out=pixels)
        fmt = QImage.Format.Format_Indexed8 if self.modality == "PET" else QImage.Format.Format_Grayscale8
        image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], fmt).copy()
        if self.modality == "PET":
            image.setColorTable(_PET_PALETTE)
        self._canvas.image = image
        self._canvas.update()

    def _update_counter(self):
        count = self._volume.shape[0]
        digits = len(str(count))
        self._counter.setText(f"{self._index + 1:0{digits}d} / {count}")

    def set_index(self, index: int):
        if self._volume is None:
            return
        index = max(0, min(int(index), self._volume.shape[0] - 1))
        if index == self._index:
            return
        self._index = index
        self._canvas.outline = QPainterPath()
        with QSignalBlocker(self._slider):
            self._slider.setValue(index)
        self._update_counter()
        self._render_slice()
        self.slice_changed.emit(index)

    def set_mask(self, mask: np.ndarray | None):
        """Display only the boundary of the mask for the currently visible slice."""
        if mask is not None:
            mask = np.asarray(mask, dtype=bool)
            if self._volume is None or mask.shape != self._volume.shape[1:]:
                raise ValueError("ROI 掩膜大小须与当前层一致")
        self._canvas.outline = _outline(mask) if mask is not None else QPainterPath()
        self._canvas.update()

    def set_tool_tip(self, text: str):
        self._canvas.setToolTip(text)
