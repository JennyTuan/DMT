"""本机 PET/CT 阅片与单层 ROI 编辑入口。"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from imaging import load_study
from roi_store import StudyStore, grow_region
from viewport import SliceView

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parents[1]
sys.path.insert(0, str(ROOT))
from fixtures.make_demo import make_demo

TITLE = "淋巴瘤 PET 随访原型"
BANNER = "原型·不可用于临床诊疗决策"


class ImportTask(QThread):
    def __init__(self, root, directory, parent):
        super().__init__(parent)
        self.root = root
        self.directory = directory
        self.error = ""

    def run(self):
        try:
            if self.directory is None:
                fixtures = self.root / "data" / "fixtures"
                self.directory = fixtures / "petfollow-demo-v1"
                if not self.directory.exists():
                    make_demo(fixtures)
            self.study = load_study(self.directory)
            self.store = StudyStore(self.root, self.study.exam)
        except Exception as exc:
            self.error = str(exc) or type(exc).__name__


def row(*widgets):
    layout = QHBoxLayout()
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def caption(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class MainWindow(QMainWindow):
    def __init__(self, data_root=ROOT):
        super().__init__()
        self.data_root = Path(data_root)
        self.source_dir = self.study = self.store = self.import_task = None
        self.mask = self.seed = self.roi_slice = self.lesion_id = None
        self.dirty = self.edited = False
        self.setWindowTitle(TITLE)
        self.resize(1380, 800)
        self.setMinimumSize(980, 610)
        self.setStyleSheet((APP_DIR / "workstation.qss").read_text(encoding="utf-8"))
        central = QWidget()
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        strip = QFrame(objectName="bannerStrip")
        bar = QHBoxLayout(strip)
        bar.setContentsMargins(14, 4, 14, 4)
        self.banner = caption(BANNER, "banner")
        bar.addWidget(self.banner)
        bar.addStretch()
        bar.addWidget(caption("院内试用   /   本机工作站", "bannerNote"))
        shell.addWidget(strip)

        actions = QFrame(objectName="commandBar")
        bar = QHBoxLayout(actions)
        bar.setContentsMargins(14, 8, 14, 8)
        bar.addWidget(caption("PET / CT", "modalityTag"))
        bar.addSpacing(5)
        bar.addWidget(caption(TITLE, "title"))
        bar.addStretch()
        self.demo_button = QPushButton("载入示意数据")
        self.import_button = QPushButton("导入 DICOM 目录", objectName="primary")
        self.demo_button.clicked.connect(lambda: self.open_directory(None))
        self.import_button.clicked.connect(self.choose_directory)
        bar.addWidget(self.demo_button)
        bar.addWidget(self.import_button)
        shell.addWidget(actions)

        context = QFrame(objectName="contextBar")
        bar = QHBoxLayout(context)
        bar.setContentsMargins(14, 6, 14, 6)
        self.exam_info = caption("尚未载入检查", "contextValue")
        self.correction = caption("衰减校正   —", "muted")
        self.synthetic_badge = caption("示意数据", "synthetic")
        self.synthetic_badge.hide()
        bar.addWidget(self.exam_info)
        bar.addSpacing(14)
        bar.addWidget(self.correction)
        bar.addStretch()
        bar.addWidget(self.synthetic_badge)
        shell.addWidget(context)

        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.setHandleWidth(2)
        self.pet, self.ct = SliceView("PET"), SliceView("CT")
        self.workspace.addWidget(self.pet)
        self.workspace.addWidget(self.ct)
        self.workspace.addWidget(self.build_sidebar())
        self.workspace.setStretchFactor(0, 1)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setSizes([510, 510, 300])
        shell.addWidget(self.workspace, 1)
        self.message = caption("选择含同次 PET 和 CT 的目录，或载入示意数据。", "footer")
        self.message.setWordWrap(True)
        shell.addWidget(self.message)
        self.pet.pixel_clicked.connect(self.pet_click)
        self.pet.pixel_dragged.connect(self.brush)
        self.pet.slice_changed.connect(self.show_outline)
        self.update_controls()

    def build_sidebar(self):
        side = QFrame(objectName="sidebar")
        side.setMinimumWidth(262)
        side.setMaximumWidth(380)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 11, 12, 10)
        layout.setSpacing(8)
        self.count = caption("00", "count")
        self.new_button = QPushButton("＋ 新病灶")
        self.new_button.clicked.connect(self.new_lesion)
        heading = row(caption("病灶列表", "section"), self.count)
        heading.addStretch()
        heading.addWidget(self.new_button)
        layout.addLayout(heading)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["序号", "部位", "状态"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.select_lesion)
        layout.addWidget(self.table, 1)

        layout.addWidget(caption("ROI 工具", "section"))
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("例如：纵隔淋巴结")
        self.label_edit.setMaxLength(80)
        self.label_edit.textEdited.connect(self.label_changed)
        layout.addLayout(row(caption("部位", "field"), self.label_edit))
        self.fraction = QSpinBox()
        self.fraction.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self.fraction.setRange(1, 100)
        self.fraction.setSuffix(" %")
        self.fraction.setValue(65)
        self.fraction.setKeyboardTracking(False)
        self.fraction.valueChanged.connect(self.threshold_changed)
        threshold = row(caption("种子相对阈值", "field"))
        threshold.addStretch()
        threshold.addWidget(self.fraction)
        layout.addLayout(threshold)
        self.modes = QButtonGroup(self)
        self.seed_button = QPushButton("点种子")
        self.add_button = QPushButton("涂入")
        self.erase_button = QPushButton("擦除")
        for button in (self.seed_button, self.add_button, self.erase_button):
            button.setCheckable(True)
            self.modes.addButton(button)
        self.seed_button.setChecked(True)
        layout.addLayout(row(self.seed_button, self.add_button, self.erase_button))
        tip = caption("在 PET 层面点种子生成轮廓。涂入或擦除可逐笔修订。", "muted")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.save_button = QPushButton("保存 ROI", objectName="primary")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        metrics = QFrame(objectName="metrics")
        fields = QVBoxLayout(metrics)
        fields.setContentsMargins(9, 6, 9, 6)
        fields.addWidget(caption("SUVmax    —       最长径    — mm", "numeric"))
        self.audit_info = caption("尚无已保存的 ROI", "muted")
        self.audit_info.setWordWrap(True)
        fields.addWidget(self.audit_info)
        layout.addWidget(metrics)
        return side

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择同次检查的 PET 和 CT 目录")
        if path:
            self.open_directory(Path(path))

    def can_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "轮廓尚未保存", "放弃当前未保存的 ROI 修改？",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def open_directory(self, directory):
        if self.import_task is not None or not self.can_discard():
            return
        self.import_task = ImportTask(self.data_root, directory, self)
        self.import_task.finished.connect(self.import_finished)
        self.message.setText("正在本机读取 DICOM 序列…")
        self.workspace.setEnabled(False)
        self.import_button.setEnabled(False)
        self.demo_button.setEnabled(False)
        self.import_task.start()

    def import_finished(self):
        task = self.import_task
        self.import_task = None
        self.workspace.setEnabled(True)
        self.import_button.setEnabled(True)
        self.demo_button.setEnabled(True)
        task.deleteLater()
        if task.error:
            self.message.setText("导入失败 · " + task.error)
            return
        self.study, self.store, self.source_dir = task.study, task.store, task.directory
        exam = self.study.exam
        self.clear_editor()
        self.pet.set_volume(self.study.pet, self.study.pet_spacing, inverted=self.study.pet_inverted)
        self.ct.set_volume(self.study.ct, self.study.ct_spacing, inverted=self.study.ct_inverted)
        self.synthetic_badge.setVisible(exam.get("is_synthetic", False))
        patient_code = exam["patient_pseudo_id"]
        when = datetime.fromisoformat(exam["study_datetime"]).strftime("%Y-%m-%d %H:%M")
        self.exam_info.setText(f"患者代号   {patient_code[-10:].upper()}      检查时间   {when}")
        self.exam_info.setToolTip(f"{patient_code}\n{exam['exam_id']}")
        correction = self.study.correction_label
        if not exam["attenuation_corrected"]:
            correction += " · 后续量测需复核（needs_review）"
        self.correction.setText("衰减校正   " + correction)
        self.refresh_list()
        self.message.setText("检查已载入 · PET 与 CT 独立切层。在 PET 视口点种子，或从右侧选择已有病灶。")

    def refresh_list(self):
        lesions = self.store.bundle["lesions"]
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(lesions))
            for index, lesion in enumerate(lesions):
                values = (f"{index + 1:02}", lesion["label"], lesion["status"])
                for col, value in enumerate(values):
                    self.table.setItem(index, col, QTableWidgetItem(value))
                if self.lesion_id == lesion["lesion_id"]:
                    self.table.selectRow(index)
        self.count.setText(f"{len(lesions):02}")
        self.update_controls()

    def clear_editor(self):
        self.lesion_id = self.mask = self.roi_slice = self.seed = None
        self.dirty = self.edited = False
        self.label_edit.clear()
        self.seed_button.setChecked(True)
        self.audit_info.setText("尚无已选病灶")
        self.pet.set_mask(None)
        with QSignalBlocker(self.table):
            self.table.clearSelection()
        self.update_controls()

    def new_lesion(self):
        if self.can_discard():
            self.clear_editor()
            self.message.setText("新病灶 · 在 PET 视口选择层面并点种子。")

    def select_lesion(self):
        index = self.table.currentRow()
        if index < 0 or not self.store or not self.table.selectedItems():
            return
        lesions = self.store.bundle["lesions"]
        lesion = lesions[index]
        if lesion["lesion_id"] == self.lesion_id:
            return
        old = self.lesion_id
        if self.can_discard():
            try:
                mask, meta = self.store.load_roi(lesion["lesion_id"])
                layer = meta["slice_index"]
                if (not 0 <= layer < len(self.study.pet_uids)
                        or self.study.pet_uids[layer] != meta["sop_uid"]
                        or mask.shape != self.study.pet[layer].shape):
                    raise ValueError("已保存的 ROI 与当前 PET 层面不匹配")
            except (ValueError, KeyError, OSError) as exc:
                self.message.setText("无法打开 ROI · " + str(exc))
            else:
                self.lesion_id, self.mask, self.roi_slice = lesion["lesion_id"], mask, layer
                self.seed = tuple(meta["seed"])
                self.dirty = self.edited = False
                self.label_edit.setText(lesion["label"])
                with QSignalBlocker(self.fraction):
                    self.fraction.setValue(round(meta["fraction"] * 100))
                self.pet.set_index(layer)
                self.show_outline()
                self.show_audit(lesion, meta)
                self.update_controls()
                self.message.setText(f"已定位病灶 · PET 第 {layer + 1} 层")
                return
        with QSignalBlocker(self.table):
            self.table.clearSelection()
            for i, item in enumerate(lesions):
                if item["lesion_id"] == old:
                    self.table.selectRow(i)

    def show_audit(self, lesion, revision):
        entry = lesion["audit"][-1]
        saved = datetime.fromisoformat(revision["at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        action = "人工修订" if revision["edited"] else "种子生长"
        self.audit_info.setText(f"{entry['from']} → {entry['to']}\n最近保存  {action}  ·  {saved}")

    def show_outline(self, *_):
        self.pet.set_mask(self.mask if self.pet.index == self.roi_slice else None)

    def update_controls(self):
        ready = self.store is not None
        for control in (self.new_button, self.label_edit, self.fraction, self.seed_button):
            control.setEnabled(ready)
        for control in (self.add_button, self.erase_button):
            control.setEnabled(ready and self.mask is not None)
        self.save_button.setEnabled(ready and self.mask is not None and self.dirty)

    def label_changed(self):
        if self.mask is not None:
            self.dirty = True
            self.update_controls()

    def threshold_changed(self):
        if self.seed is not None:
            self.regrow(self.roi_slice, *self.seed)

    def pet_click(self, x, y):
        if self.study is None:
            return
        if not self.seed_button.isChecked():
            self.brush(x, y)
        elif self.lesion_id is not None and self.roi_slice != self.pet.index:
            self.message.setText("当前病灶属于另一 PET 层。请选择「新病灶」或返回原层面。")
        else:
            self.regrow(self.pet.index, x, y)

    def regrow(self, layer, x, y):
        try:
            mask = grow_region(self.study.pet[layer], x, y, self.fraction.value() / 100)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.mask, self.roi_slice, self.seed = mask, layer, (x, y)
        self.dirty = True
        self.edited = self.lesion_id is not None
        self.show_outline()
        self.update_controls()
        self.message.setText(f"轮廓待保存 · PET 第 {layer + 1} 层，种子 ({x}, {y})。可调整阈值、涂入或擦除。")

    def brush(self, x, y):
        if self.mask is None or self.pet.index != self.roi_slice or self.seed_button.isChecked():
            return
        height, width = self.mask.shape
        area = self.mask[max(0, y-2):min(height, y+3), max(0, x-2):min(width, x+3)]
        value = self.add_button.isChecked()
        if np.any(area != value):
            area[:] = value
            self.dirty = self.edited = True
            self.show_outline()
            self.update_controls()
            self.message.setText("轮廓已人工修订 · 保存后可重新打开。")

    def save(self):
        if not self.dirty or self.mask is None:
            return
        label = self.label_edit.text().strip()
        if not label and self.lesion_id is None:
            label = f"病灶 {len(self.store.bundle['lesions']) + 1:02}"
        try:
            self.lesion_id = self.store.save_roi(
                self.mask, slice_index=self.roi_slice, sop_uid=self.study.pet_uids[self.roi_slice],
                seed=self.seed, fraction=self.fraction.value() / 100, label=label,
                lesion_id=self.lesion_id, edited=self.edited,
            )
        except (ValueError, OSError) as exc:
            self.message.setText("保存失败 · " + str(exc))
            return
        self.dirty = self.edited = False
        self.label_edit.setText(label)
        self.refresh_list()
        lesion = next(item for item in self.store.bundle["lesions"] if item["lesion_id"] == self.lesion_id)
        _, revision = self.store.load_roi(self.lesion_id)
        self.show_audit(lesion, revision)
        self.message.setText(f"ROI 已保存 · {label} · proposed")

    def closeEvent(self, event):
        if self.import_task is not None:
            self.message.setText("导入中，请在读取结束后关闭窗口。")
            event.ignore()
        elif self.can_discard():
            event.accept()
        else:
            event.ignore()


def main():
    parser = argparse.ArgumentParser(description=TITLE)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dicom", type=Path, help="含同检 PET、CT 的本地目录")
    source.add_argument("--demo", action="store_true", help="直接载入合成示意数据")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    if args.demo or args.dicom:
        QTimer.singleShot(0, lambda: window.open_directory(args.dicom))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
