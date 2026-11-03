"""本机 PET/CT 阅片与单层 ROI 编辑入口。"""

import argparse
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QScrollArea, QSlider, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from diameter import diameter_for_roi
from imaging import load_study
from measurement_ui import FIELDS, display_value, edit_value_dialog, show_history
from pairing import Pairing
from pairing_ui import ComparisonPanel, choose_prior
from quality_gate import BANNER
from quality_review import QualityReview, show_quality
from report_ui import ReportDialog
from roi_store import StudyStore, grow_region
from suv import suv_for_roi
from viewport import SliceView
from visuals import apply_window_chrome, configure_application, icon

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parents[1]
sys.path.insert(0, str(ROOT))
from fixtures.make_demo import make_demo_pair

TITLE = "淋巴瘤 PET 随访原型"


def check_roi_source(study, mask, slice_index, sop_uid):
    if (not 0 <= slice_index < len(study.pet_uids) or study.pet_uids[slice_index] != sop_uid
            or mask.shape != study.pet[slice_index].shape):
        raise ValueError("ROI 与本次载入的 PET 实例或图像尺寸不符")


def measure_roi(study, mask, slice_index, sop_uid):
    check_roi_source(study, mask, slice_index, sop_uid)
    suv, suv_note = suv_for_roi(study, mask, slice_index)
    diameter, diameter_note = diameter_for_roi(study, mask, slice_index)
    return ({"suv_max": suv, "longest_diameter_mm": diameter},
            {"suv_max": suv_note, "longest_diameter_mm": diameter_note})


class ImportTask(QThread):
    def __init__(self, root, directory, parent):
        super().__init__(parent)
        self.root = root
        self.directory = directory
        self.error = ""
        self.demo_paths = None

    def open_study(self, directory, *, seed_demo=False):
        study = load_study(directory)
        store = StudyStore(self.root, study.exam, measure=partial(measure_roi, study))
        if seed_demo and not store.bundle["lesions"]:
            mask = grow_region(study.pet[10], 104, 90, .65)
            store.save_roi(mask, slice_index=10, sop_uid=study.pet_uids[10], seed=(104, 90),
                           fraction=.65, label="纵隔示意病灶")
        return study, store

    def open_demo(self):
        base_dir, follow_dir = make_demo_pair(self.root / "data" / "fixtures")
        self.demo_paths = (base_dir, follow_dir)
        _, baseline = self.open_study(base_dir, seed_demo=True)
        self.study, self.store = self.open_study(follow_dir, seed_demo=True)
        Pairing(self.store).ensure_demo_prior(baseline.exam_id)
        self.directory = follow_dir

    def run(self):
        try:
            if self.directory is None:
                self.open_demo()
            else:
                self.study, self.store = self.open_study(self.directory)
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


def action_button(text, glyph, *, primary=False):
    button = QPushButton(text, objectName="primary" if primary else "action")
    button.setIcon(icon(glyph, "#102d30" if primary else "#b8cbd6"))
    button.setIconSize(QSize(16, 16))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def context_field(text, value, parent_layout):
    column = QVBoxLayout()
    column.setSpacing(1)
    column.addWidget(caption(text, "eyebrow"))
    label = caption(value, "contextValue")
    column.addWidget(label)
    parent_layout.addLayout(column)
    return label


class MainWindow(QMainWindow):
    def __init__(self, data_root=ROOT):
        super().__init__()
        self.data_root = Path(data_root)
        self.source_dir = self.study = self.store = self.import_task = None
        self.demo_paths = self.pairing = None
        self.mask = self.seed = self.roi_slice = self.lesion_id = None
        self.measurements = {}
        self.dirty = self.edited = False
        self.setWindowTitle(TITLE)
        self.setMinimumSize(980, 610)
        self.setWindowIcon(icon("brand", size=64))
        apply_window_chrome(self)
        available = self.screen().availableGeometry()
        self.resize(min(1450, max(980, available.width() - 48)),
                    min(860, max(610, available.height() - 72)))
        self.setStyleSheet((APP_DIR / "workstation.qss").read_text(encoding="utf-8"))
        central = QWidget(objectName="workstation")
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        strip = QFrame(objectName="bannerStrip")
        bar = QHBoxLayout(strip)
        bar.setContentsMargins(20, 4, 20, 4)
        bar.setSpacing(8)
        warning = QLabel()
        warning.setPixmap(icon("warning", "#e8bc76").pixmap(15, 15))
        bar.addWidget(warning)
        self.banner = caption(BANNER, "banner")
        bar.addWidget(self.banner)
        bar.addStretch()
        bar.addWidget(caption("院内试用   /   本地工作站", "bannerNote"))
        shell.addWidget(strip)

        actions = QFrame(objectName="commandBar")
        bar = QHBoxLayout(actions)
        bar.setContentsMargins(20, 9, 20, 9)
        bar.setSpacing(7)
        mark = QLabel()
        mark.setPixmap(icon("brand", size=40).pixmap(40, 40))
        bar.addWidget(mark)
        bar.addSpacing(3)
        identity = QVBoxLayout()
        identity.setSpacing(0)
        identity.addWidget(caption(TITLE, "title"))
        identity.addWidget(caption("FDG PET/CT    ·    代谢随访工作站", "subtitle"))
        bar.addLayout(identity)
        bar.addStretch()
        self.demo_button = action_button("载入示意数据", "layers")
        self.import_button = action_button("导入 DICOM", "folder", primary=True)
        self.import_button.setToolTip("选择含同次 PET 和 CT 的本地目录")
        self.prior_button = action_button("关联上次", "link")
        self.report_button = action_button("报告草稿", "report")
        self.quality_button = action_button("质量门", "checklist")
        self.quality_button.clicked.connect(self.open_quality)
        self.quality_button.setEnabled(False)
        self.prior_button.clicked.connect(self.choose_prior)
        self.report_button.clicked.connect(self.open_report)
        self.prior_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.demo_button.clicked.connect(lambda: self.open_directory(None))
        self.import_button.clicked.connect(self.choose_directory)
        bar.addWidget(self.prior_button)
        bar.addWidget(self.quality_button)
        bar.addWidget(self.report_button)
        divider = QFrame(objectName="verticalDivider")
        divider.setFixedSize(1, 23)
        bar.addWidget(divider)
        bar.addWidget(self.demo_button)
        bar.addWidget(self.import_button)
        shell.addWidget(actions)

        context = QFrame(objectName="contextBar")
        bar = QHBoxLayout(context)
        bar.setContentsMargins(21, 6, 20, 7)
        bar.setSpacing(24)
        self.exam_info = context_field("患者代号", "尚未载入", bar)
        self.exam_time = context_field("检查时间", "—", bar)
        self.correction = context_field("PET 衰减校正", "—", bar)
        self.synthetic_badge = caption("示意数据", "synthetic")
        self.synthetic_badge.hide()
        self.source_badge = caption("本地 DICOM", "sourceBadge")
        self.source_badge.hide()
        self.switch_demo_button = action_button("", "switch")
        self.switch_demo_button.hide()
        self.switch_demo_button.clicked.connect(self.switch_demo)
        bar.addStretch()
        bar.addWidget(self.source_badge)
        bar.addWidget(self.synthetic_badge)
        bar.addWidget(self.switch_demo_button)
        shell.addWidget(context)

        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.setHandleWidth(7)
        self.pet, self.ct = SliceView("PET"), SliceView("CT")
        self.workspace.addWidget(self.pet)
        self.workspace.addWidget(self.ct)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("inspectorTabs")
        self.tabs.setMinimumWidth(320)
        self.tabs.setMaximumWidth(485)
        self.tabs.addTab(self.build_sidebar(), icon("crosshair", size=16), "本次病灶")
        self.comparison = ComparisonPanel()
        self.comparison.action_requested.connect(self.change_pair)
        self.comparison.lesion_selected.connect(self.focus_comparison_lesion)
        self.tabs.addTab(self.comparison, icon("link", size=16), "前后对照")
        self.tabs.setIconSize(QSize(15, 15))
        self.tabs.currentChanged.connect(self.refresh_comparison)
        self.workspace.addWidget(self.tabs)
        self.workspace.setStretchFactor(0, 1)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setSizes([510, 510, 380])
        stage = QVBoxLayout()
        stage.setContentsMargins(10, 9, 10, 8)
        stage.addWidget(self.workspace)
        shell.addLayout(stage, 1)
        self.message = caption("选择含同次 PET 和 CT 的目录，或载入示意数据。", "footer")
        self.message.setWordWrap(True)
        status = QFrame(objectName="statusBar")
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(18, 5, 18, 5)
        status_row.addWidget(self.message, 1)
        status_row.addWidget(caption("本地运行", "statusTag"))
        shell.addWidget(status)
        self.pet.pixel_clicked.connect(self.pet_click)
        self.pet.pixel_dragged.connect(self.brush)
        self.pet.slice_changed.connect(self.show_outline)
        self.update_controls()

    def build_sidebar(self):
        scroll = QScrollArea(objectName="inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side = QFrame(objectName="sidebar")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        self.count = caption("00", "count")
        self.new_button = action_button("新病灶", "add")
        self.new_button.setObjectName("smallAction")
        self.new_button.clicked.connect(self.new_lesion)
        heading = row(caption("病灶列表", "section"), self.count)
        heading.addStretch()
        heading.addWidget(self.new_button)
        layout.addLayout(heading)
        self.table = QTableWidget(0, 4, objectName="lesionsTable")
        self.table.setHorizontalHeaderLabels(["部位", "SUVmax", "最长径 mm", "量测状态"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.select_lesion)
        self.table.cellActivated.connect(self.edit_measurement)
        self.table.hide()
        layout.addWidget(self.table)
        self.empty_list = caption("尚无病灶记录\n在 PET 视口点选种子后保存 ROI。", "emptyList")
        self.empty_list.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_list)
        tools = row(caption("双击量测数值可修改", "muted"))
        tools.addStretch()
        self.history_button = action_button("数值留痕", "history")
        self.history_button.setObjectName("quietAction")
        self.history_button.setEnabled(False)
        self.history_button.clicked.connect(self.view_history)
        tools.addWidget(self.history_button)
        layout.addLayout(tools)
        self.review_reason = caption("", "reviewReason")
        self.review_reason.setWordWrap(True)
        self.review_reason.hide()
        layout.addWidget(self.review_reason)

        self.metric_strip = QFrame(objectName="metricStrip")
        meter = QHBoxLayout(self.metric_strip)
        meter.setContentsMargins(12, 7, 12, 7)
        meter.setSpacing(15)
        self.readouts = []
        for col, title in ((1, "SUVmax"), (2, "CT 最长径  /  mm")):
            numbers = QVBoxLayout()
            numbers.setSpacing(0)
            numbers.addWidget(caption(title, "eyebrow"))
            readout = QPushButton("—", objectName="readout")
            readout.setCursor(Qt.CursorShape.PointingHandCursor)
            readout.setAccessibleName("修改" + title)
            readout.setToolTip("点击修改量测值")
            readout.clicked.connect(lambda _, c=col: self.edit_measurement(self.table.currentRow(), c))
            numbers.addWidget(readout)
            meter.addLayout(numbers, 1)
            self.readouts.append(readout)
        self.metric_strip.hide()
        layout.addWidget(self.metric_strip)
        layout.addSpacing(4)
        rule = QFrame(objectName="sectionRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        label = row(caption("ROI 轮廓工具", "section"))
        label.addStretch()
        self.edit_badge = caption("待选种子", "editMode")
        label.addWidget(self.edit_badge)
        layout.addLayout(label)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("例如：纵隔淋巴结")
        self.label_edit.setMaxLength(80)
        self.label_edit.textEdited.connect(self.label_changed)
        self.label_edit.setAccessibleName("病灶部位")
        layout.addLayout(row(caption("部位", "field"), self.label_edit))
        self.fraction = QSpinBox()
        self.fraction.setObjectName("thresholdValue")
        self.fraction.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        self.fraction.setFixedWidth(83)
        self.fraction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fraction.setRange(1, 100)
        self.fraction.setSuffix(" %")
        self.fraction.setValue(65)
        self.fraction.setKeyboardTracking(False)
        self.fraction.valueChanged.connect(self.threshold_changed)
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal, objectName="roiThreshold")
        self.threshold_slider.setAccessibleName("种子相对阈值")
        self.threshold_slider.setRange(1, 100)
        self.threshold_slider.setValue(self.fraction.value())
        self.threshold_slider.setTracking(False)
        self.threshold_slider.valueChanged.connect(self.fraction.setValue)
        self.fraction.valueChanged.connect(self.threshold_slider.setValue)
        threshold = row(caption("相对阈值", "field"))
        threshold.addWidget(self.threshold_slider, 1)
        threshold.addWidget(self.fraction)
        layout.addLayout(threshold)
        self.modes = QButtonGroup(self)
        self.seed_button = action_button("点种子", "seed")
        self.add_button = action_button("涂入", "paint")
        self.erase_button = action_button("擦除", "eraser")
        segments = QFrame(objectName="segments")
        modes = QHBoxLayout(segments)
        modes.setContentsMargins(3, 3, 3, 3)
        modes.setSpacing(2)
        for button in (self.seed_button, self.add_button, self.erase_button):
            button.setObjectName("segment")
            button.setCheckable(True)
            self.modes.addButton(button)
            modes.addWidget(button, 1)
        self.seed_button.setChecked(True)
        layout.addWidget(segments)
        tip = caption("在 PET 图像中点选种子，或按住鼠标修订轮廓。", "muted")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        self.save_button = action_button("保存 ROI", "save", primary=True)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        layout.addStretch(1)
        self.audit_info = caption("尚无已保存的 ROI", "audit")
        self.audit_info.setWordWrap(True)
        layout.addWidget(self.audit_info)
        scroll.setWidget(side)
        return scroll

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, BANNER + " · 选择同次检查的 PET 和 CT 目录")
        if path:
            self.open_directory(Path(path))

    def can_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, BANNER, "放弃当前未保存的 ROI 修改？",
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
        self.prior_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.switch_demo_button.setEnabled(False)
        self.quality_button.setEnabled(False)
        self.import_task.start()

    def import_finished(self):
        task = self.import_task
        self.import_task = None
        self.workspace.setEnabled(True)
        self.import_button.setEnabled(True)
        self.demo_button.setEnabled(True)
        self.prior_button.setEnabled(self.store is not None or not task.error)
        self.report_button.setEnabled(self.prior_button.isEnabled())
        self.quality_button.setEnabled(self.prior_button.isEnabled())
        self.switch_demo_button.setEnabled(True)
        task.deleteLater()
        if task.error:
            self.message.setText("导入失败 · " + task.error)
            return
        self.study, self.store, self.source_dir = task.study, task.store, task.directory
        self.pairing = Pairing(self.store)
        self.quality = QualityReview(self.pairing)
        if task.demo_paths is not None:
            self.demo_paths = task.demo_paths
        demo_visit = self.demo_paths is not None and self.source_dir in self.demo_paths
        if demo_visit:
            is_baseline = self.source_dir == self.demo_paths[0]
            self.switch_demo_button.setText("切至示意随访" if is_baseline else "切至示意基线")
            self.synthetic_badge.setText("示意数据 · 基线" if is_baseline else "示意数据 · 随访")
        else:
            self.synthetic_badge.setText("示意数据")
        self.switch_demo_button.setVisible(demo_visit)
        exam = self.store.bundle["exam"]
        self.clear_editor()
        self.pet.set_volume(self.study.pet, self.study.pet_spacing, inverted=self.study.pet_inverted)
        self.ct.set_volume(self.study.ct, self.study.ct_spacing, inverted=self.study.ct_inverted)
        self.synthetic_badge.setVisible(exam.get("is_synthetic", False))
        patient_code = exam["patient_pseudo_id"]
        when = datetime.fromisoformat(exam["study_datetime"]).strftime("%Y-%m-%d %H:%M")
        self.exam_info.setText(patient_code[-10:].upper())
        self.exam_time.setText(when)
        self.exam_info.setToolTip(f"{patient_code}\n{exam['exam_id']}")
        correction = self.study.correction_label
        if not exam["attenuation_corrected"]:
            correction += " · 量测需复核"
        self.correction.setText(correction)
        self.source_badge.setVisible(not exam.get("is_synthetic", False))
        self.refresh_list()
        self.message.setText("检查已载入 · PET 与 CT 独立切层。在 PET 视口点种子，或从右侧选择已有病灶。")
        self.record_checks("载入检查")

    def switch_demo(self):
        if self.demo_paths:
            base, follow = self.demo_paths
            self.open_directory(follow if self.source_dir == base else base)

    def choose_prior(self):
        if self.dirty:
            self.message.setText("请先保存 ROI 修改，再关联上次检查。")
            return
        try:
            accepted, prior_id = choose_prior(self, self.store.bundle["exam"], self.pairing.candidates())
            if accepted:
                self.pairing.set_prior(prior_id)
                self.tabs.setCurrentWidget(self.comparison)
                self.refresh_comparison()
                self.message.setText("已保存先验关联。" if prior_id else "当前检查已解除先验关联。")
                self.record_checks("关联先验")
        except (ValueError, OSError) as exc:
            self.message.setText("关联未完成 · " + str(exc))

    def refresh_comparison(self, *_):
        if not self.pairing or self.tabs.currentWidget() != self.comparison:
            return
        if self.dirty:
            self.tabs.setCurrentIndex(0)
            self.message.setText("请先保存 ROI 修改，再查看前后对照。")
            return
        try:
            current, prior, skipped = self.pairing.quality_snapshot(strict=True)
            self.comparison.populate(current, prior, focused_id=self.lesion_id, skipped=skipped)
        except (ValueError, OSError) as exc:
            self.comparison.clear(str(exc))
            self.message.setText("无法读取对照 · " + str(exc))

    def focus_comparison_lesion(self, lesion_id):
        if lesion_id is None:
            self.clear_editor()
        elif lesion_id != self.lesion_id:
            for index, lesion in enumerate(self.store.bundle["lesions"]):
                if lesion["lesion_id"] == lesion_id:
                    self.table.selectRow(index)
                    break

    def change_pair(self, operation, current_id, prior_id):
        try:
            if operation == "pair":
                self.pairing.pair(current_id, prior_id)
            elif operation == "unpair":
                self.pairing.unpair(current_id)
            elif operation == "new_track":
                self.pairing.new_track(current_id)
            elif operation in ("skip", "unskip"):
                self.pairing.set_skip(current_id, operation == "skip")
            self.refresh_list()
            self.message.setText("配对决定已保存并留痕。")
            self.record_checks("病灶配对")
        except (ValueError, OSError) as exc:
            self.message.setText("配对未完成 · " + str(exc))

    def record_checks(self, stage):
        # A failed sidecar write must not report an already committed operation as failed.
        try:
            before = self.store.bundle
            self.quality.capture(recheck=stage != "载入检查")
            rows = self.quality.record(self.quality.saved_text(), stage=stage)
            self.update_gate_count(rows)
            if before is not self.store.bundle:
                self.refresh_list()
        except (OSError, ValueError) as exc:
            self.quality_button.setText("质量门 · 待核对")
            self.message.setText(f"{stage}已完成，质量门快照未更新 · {exc}")

    def update_gate_count(self, rows):
        count = sum(r["level"] in ("block", "review", "warn") for r in rows)
        self.quality_button.setText(f"质量门 · {count}" if count else "质量门")

    def open_quality(self):
        try:
            self.quality.capture()
            text = self.quality.saved_text()
            results = self.quality.record(text, stage="查看质量门")
            self.update_gate_count(results)
            self.refresh_list()
            show_quality(self, results, self.store.exam_id, text_checked=text is not None)
        except (OSError, ValueError) as exc:
            self.message.setText("无法核对质量门 · " + str(exc))

    def open_report(self):
        if self.dirty:
            self.message.setText("请先保存 ROI 修改，再从已保存量测生成报告草稿。")
            return
        try:
            dialog = ReportDialog(self, self.data_root, self.quality.capture, gate_provider=self.quality.record)
            dialog.exec()
            dialog.deleteLater()
            self.refresh_list()
        except (ValueError, OSError) as exc:
            self.message.setText("无法打开报告草稿 · " + str(exc))

    def refresh_list(self):
        lesions = self.store.bundle["lesions"]
        self.measurements = {m["lesion_id"]: m for m in self.store.bundle["measurements"]}
        with QSignalBlocker(self.table):
            self.table.setRowCount(len(lesions))
            for index, lesion in enumerate(lesions):
                measurement = self.measurements.get(lesion["lesion_id"])
                state = measurement["state"] if measurement else "—"
                status = {"proposed": "待确认", "needs_review": "需复核"}.get(state, state)
                numbers = [display_value(measurement[field] if measurement else None) for field in FIELDS]
                values = [lesion["label"], *numbers, status]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    if col in (1, 2):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        number = measurement[FIELDS[col - 1]] if measurement else None
                        item.setToolTip(f"{number if number is not None else '未测'} · 双击修改")
                    if col == 3 and measurement:
                        note = measurement["audit"][-1]["note"] if measurement["audit"] else ""
                        item.setToolTip(f"{state} · {note}")
                    self.table.setItem(index, col, item)
                if self.lesion_id == lesion["lesion_id"]:
                    self.table.selectRow(index)
        self.count.setText(f"{len(lesions):02}")
        self.table.setVisible(bool(lesions))
        self.empty_list.setVisible(not lesions)
        self.table.setFixedHeight(self.table.horizontalHeader().height()
                                  + min(len(lesions), 5) * self.table.verticalHeader().defaultSectionSize() + 3)
        self.refresh_comparison()
        self.update_measurement_details()
        self.update_controls()

    def selected_lesion(self):
        row_index = self.table.currentRow()
        if self.store and row_index >= 0 and self.table.selectedItems():
            return self.store.bundle["lesions"][row_index]
        return None

    def edit_measurement(self, index, column):
        lesion = self.selected_lesion()
        if column not in (1, 2) or not lesion or index != self.table.currentRow():
            return
        if self.dirty:
            self.message.setText("请先保存 ROI 修改，再编辑该版本的量测数值。")
            return
        measurement = self.measurements.get(lesion["lesion_id"])
        if not measurement or measurement["state"] not in ("proposed", "needs_review"):
            self.message.setText("当前量测状态不允许改数。")
            return
        field = FIELDS[column - 1]
        change = edit_value_dialog(self, lesion["label"], field, measurement[field])
        if change is not None:
            try:
                self.store.edit_value(lesion["lesion_id"], field, *change)
            except (ValueError, OSError) as exc:
                self.message.setText("改数失败 · " + str(exc))
                return
            self.refresh_list()
            self.message.setText("人工修改已保存，可在「数值留痕」查看前值和修改依据。")
            self.record_checks("人工改数")

    def view_history(self):
        lesion = self.selected_lesion()
        if lesion:
            try:
                events = self.store.value_history(lesion["lesion_id"])
                show_history(self, lesion["label"], events)
            except (ValueError, OSError) as exc:
                self.message.setText("读取数值留痕失败 · " + str(exc))

    def clear_editor(self):
        self.lesion_id = self.mask = self.roi_slice = self.seed = None
        self.dirty = self.edited = False
        self.label_edit.clear()
        self.seed_button.setChecked(True)
        self.audit_info.setText("尚无已选病灶")
        self.pet.set_mask(None)
        with QSignalBlocker(self.table):
            self.table.clearSelection()
        self.update_measurement_details()
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
                check_roi_source(self.study, mask, layer, meta["sop_uid"])
            except (ValueError, KeyError, OSError) as exc:
                self.clear_editor()
                with QSignalBlocker(self.table):
                    self.table.selectRow(index)
                self.update_measurement_details()
                self.update_controls()
                self.message.setText("无法打开 ROI · " + str(exc))
                return
            else:
                self.lesion_id, self.mask, self.roi_slice = lesion["lesion_id"], mask, layer
                self.seed = tuple(meta["seed"])
                self.dirty = self.edited = False
                self.label_edit.setText(lesion["label"])
                with QSignalBlocker(self.fraction):
                    self.fraction.setValue(round(meta["fraction"] * 100))
                with QSignalBlocker(self.threshold_slider):
                    self.threshold_slider.setValue(self.fraction.value())
                self.pet.set_index(layer)
                self.show_outline()
                self.show_audit(lesion, meta)
                self.update_measurement_details()
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
        for control in (self.new_button, self.label_edit, self.fraction, self.threshold_slider, self.seed_button):
            control.setEnabled(ready)
        for control in (self.add_button, self.erase_button):
            control.setEnabled(ready and self.mask is not None)
        self.save_button.setEnabled(ready and self.mask is not None and self.dirty)
        self.edit_badge.setText("待保存" if self.dirty else ("已载入轮廓" if self.mask is not None else "待选种子"))

    def update_measurement_details(self):
        selection = self.selected_lesion()
        measurement = self.measurements.get(selection["lesion_id"]) if selection else None
        self.history_button.setEnabled(measurement is not None)
        self.metric_strip.setVisible(measurement is not None)
        if measurement is not None:
            for field, readout in zip(FIELDS, self.readouts):
                readout.setText(display_value(measurement[field]))
                readout.setEnabled(measurement["state"] in ("proposed", "needs_review"))
        review = measurement is not None and measurement["state"] == "needs_review"
        if review:
            events = self.store.value_history(selection["lesion_id"])
            latest_auto = {e["field"]: e for e in events if
                           e["actor"] == "system" and e["roi_ref"] == measurement["roi_ref"]}
            reasons = list(dict.fromkeys(e.get("source_error") or e["note"] for e in latest_auto.values()
                                         if e.get("source_error") or e["to"] is None))
            reason = " / ".join(reasons) or measurement["audit"][-1]["note"]
            self.review_reason.setText("量测需复核 · " + reason)
        self.review_reason.setVisible(review)

    def label_changed(self):
        if self.mask is not None:
            self.dirty = True
            self.update_controls()

    def threshold_changed(self):
        if self.seed is not None:
            self.regrow(self.roi_slice, *self.seed)

    def pet_click(self, x, y):
        if self.study is None or self.tabs.currentWidget() == self.comparison:
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
        if (self.mask is None or self.pet.index != self.roi_slice or self.seed_button.isChecked()
                or self.tabs.currentWidget() == self.comparison):
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
        state = self.measurements[self.lesion_id]["state"]
        self.message.setText(f"ROI 与量测已保存 · {label} · {state}")
        self.record_checks("保存量测")

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
    configure_application(app)
    window = MainWindow()
    window.show()
    if args.demo or args.dicom:
        QTimer.singleShot(0, lambda: window.open_directory(args.dicom))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
