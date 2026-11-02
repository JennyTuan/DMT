"""Manual prior selection and the workstation's two-visit comparison list."""

from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from measurement_ui import display_value
from report_draft import comparison_rows


def visit_caption(exam):
    when = datetime.fromisoformat(exam["study_datetime"]).strftime("%Y-%m-%d %H:%M")
    return f"{when}  ·  {exam['exam_id'][-10:]}"


def choose_prior(parent, exam, candidates):
    dialog = QDialog(parent)
    dialog.setWindowTitle("关联上次检查")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(parent.banner.text(), objectName="dialogBanner"))
    layout.addWidget(QLabel("当前检查   " + visit_caption(exam)))
    layout.addWidget(QLabel("同一患者 · 早于本次的检查"))
    choice = QComboBox()
    choice.addItem("不关联上次检查", None)
    for earlier in candidates:
        choice.addItem(visit_caption(earlier), earlier["exam_id"])
    choice.setCurrentIndex(max(0, choice.findData(exam["prior_exam_id"])))
    layout.addWidget(choice)
    hint = QLabel("更换或解除先验时，已有病灶配对会同时解除。" if candidates else
                  "暂无可关联的既有检查。请先导入同一患者更早的 PET-CT。")
    hint.setWordWrap(True)
    layout.addWidget(hint)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存关联")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.setMinimumWidth(370)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = choice.currentData()
    dialog.deleteLater()
    return accepted, result


def delta_text(value):
    if value is None or value == 0:
        return display_value(value)
    return f"{value:+.5g}"


class ComparisonPanel(QWidget):
    action_requested = Signal(str, str, object)
    lesion_selected = Signal(object)

    def __init__(self):
        super().__init__()
        self.rows = []
        self.exam_id = None
        self.prior_id = None
        self.skipped = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.source = QLabel("尚未载入检查", objectName="section")
        self.source.setWordWrap(True)
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.source)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["病灶 / 量测", "本次", "上次", "差值"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("差值 = 本次 − 上次", objectName="muted"))
        layout.addWidget(QLabel("人工配对", objectName="section"))
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        self.candidates = QComboBox()
        self.candidates.setAccessibleName("上次病灶候选")
        self.candidates.currentIndexChanged.connect(self.update_buttons)
        layout.addWidget(self.candidates)
        controls = QHBoxLayout()
        self.pair_button = QPushButton("指定配对", objectName="primary")
        self.unpair_button = QPushButton("解除配对")
        self.track_button = QPushButton("新建跟踪号")
        for button, operation in ((self.pair_button, "pair"), (self.unpair_button, "unpair"),
                                  (self.track_button, "new_track")):
            controls.addWidget(button)
            button.clicked.connect(lambda _, op=operation: self.request_action(op))
        layout.addLayout(controls)
        self.skip_button = QPushButton("跳过本次配对")
        self.skip_button.clicked.connect(self.toggle_skip)
        layout.addWidget(self.skip_button)
        self.update_buttons()

    def selection(self):
        if self.table.selectedItems():
            return self.rows[self.table.currentRow() // 4]
        return None

    def clear(self, message):
        self.source.setText("对照不可用")
        with QSignalBlocker(self.table):
            self.table.clearSpans()
            self.table.setRowCount(0)
            self.rows = []
        self.candidates.clear()
        self.detail.setText(message)
        self.update_buttons()

    def populate(self, current, prior, focused_id=None, skipped=()):
        selected = self.selection() if self.exam_id == current["exam"]["exam_id"] else None
        self.exam_id = current["exam"]["exam_id"]
        self.prior_id = prior["exam"]["exam_id"] if prior else None
        self.skipped = set(skipped)
        selected_id = focused_id or (selected["lesion_id"] if selected else None)
        rows = comparison_rows(current, prior)
        self.source.setText("上次   " + visit_caption(prior["exam"]) if prior else "尚未关联上次检查")
        with QSignalBlocker(self.candidates):
            self.candidates.clear()
            self.candidates.addItem("选择上次病灶…", None)
            for lesion in prior["lesions"] if prior else []:
                self.candidates.addItem(f"{lesion['label']}  ·  {lesion['lesion_id'][-8:]}", lesion["lesion_id"])
        with QSignalBlocker(self.table):
            self.table.clearSpans()
            self.table.clearContents()
            self.table.setRowCount(len(rows) * 4)
            self.rows = rows
            active = 0
            for index, item in enumerate(rows):
                start = index * 4
                paired = item["lesion_id"] and item["prior_lesion_id"]
                kind = "已配对" if paired else ("本次未配对" if item["lesion_id"] else "上次未配对")
                if item["lesion_id"] in self.skipped and not paired:
                    kind = "已跳过配对"
                label = item["label"]
                if paired and item["prior_label"] != label:
                    label += " / " + item["prior_label"]
                title = QTableWidgetItem(f"{label}   ·   {kind}")
                title.setToolTip(f"{label}\n跟踪号  {item['track_id'] or '—'}")
                self.table.setItem(start, 0, title)
                self.table.setSpan(start, 0, 1, 4)
                values = [
                    ["SUVmax", display_value(item["current_suv"]), display_value(item["prior_suv"]),
                     delta_text(item["delta_suv"])],
                    ["最长径 mm", display_value(item["current_mm"]), display_value(item["prior_mm"]),
                     delta_text(item["delta_mm"])],
                    ["量测状态", item["status"] or "—", item["prior_status"] or "—", "—"],
                ]
                for offset, line in enumerate(values, start=1):
                    for column, value in enumerate(line):
                        self.table.setItem(start + offset, column, QTableWidgetItem(value))
                if selected_id is not None and item["lesion_id"] == selected_id:
                    active = start
            if rows:
                self.table.selectRow(active)
        self.selection_changed()

    def selection_changed(self):
        item = self.selection()
        if item:
            prefix = "本次" if item["lesion_id"] else "仅上次"
            self.detail.setText(f"{prefix}  {item['label']}   ·   跟踪号  {item['track_id'] or '—'}")
        else:
            self.detail.setText("暂无病灶条目")
        candidate = item["prior_lesion_id"] if item and item["lesion_id"] else None
        with QSignalBlocker(self.candidates):
            self.candidates.setCurrentIndex(max(0, self.candidates.findData(candidate)))
        self.update_buttons()
        self.lesion_selected.emit(item["lesion_id"] if item else None)

    def update_buttons(self):
        item = self.selection()
        current = bool(item and item["lesion_id"])
        target = self.candidates.currentData()
        self.candidates.setEnabled(current and self.candidates.count() > 1)
        self.pair_button.setEnabled(bool(current and target and item["prior_lesion_id"] != target))
        self.unpair_button.setEnabled(bool(current and item["prior_lesion_id"]))
        self.track_button.setEnabled(bool(current and not item["track_id"]))
        self.skip_button.setEnabled(bool(self.prior_id and current and not item["prior_lesion_id"]))
        is_skipped = bool(current and item["lesion_id"] in self.skipped)
        self.skip_button.setText("取消跳过" if is_skipped else "跳过本次配对")

    def toggle_skip(self):
        item = self.selection()
        if item and item["lesion_id"]:
            self.request_action("unskip" if item["lesion_id"] in self.skipped else "skip")

    def request_action(self, operation):
        item = self.selection()
        if item and item["lesion_id"]:
            self.action_requested.emit(operation, item["lesion_id"], self.candidates.currentData())
