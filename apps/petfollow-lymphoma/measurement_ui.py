"""Pack 03 numeric edits and the read-only value history."""

from datetime import datetime
from math import isfinite

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


FIELDS = ("suv_max", "longest_diameter_mm")
FIELD_NAMES = {"suv_max": "SUVmax", "longest_diameter_mm": "CT 最长径 (mm)"}


def display_value(value):
    return "—" if value is None else format(value, ".5g")


def _dialog(parent, title):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    banner = QLabel(parent.banner.text(), objectName="dialogBanner")
    layout.addWidget(banner)
    return dialog, layout


def edit_value_dialog(parent, label, field, previous):
    dialog, layout = _dialog(parent, f"{label} · 修改{FIELD_NAMES[field]}")
    form = QFormLayout()
    form.addRow("原值", QLabel("未测" if previous is None else str(previous)))
    number = QLineEdit(objectName="measurementValue")
    number.setPlaceholderText("输入非负数")
    if previous is not None:
        number.setText(str(previous))
        number.selectAll()
    form.addRow(FIELD_NAMES[field], number)
    note = QLineEdit(objectName="changeNote")
    note.setPlaceholderText("修改依据，例如：人工核对 CT 层面")
    form.addRow("变更说明", note)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    save.setText("保存修改")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")

    def check_input():
        try:
            value = float(number.text())
            valid = isfinite(value) and value >= 0 and value != previous
        except ValueError:
            valid = False
        save.setEnabled(valid and bool(note.text().strip()))

    number.textChanged.connect(check_input)
    note.textChanged.connect(check_input)
    check_input()
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.setMinimumWidth(360)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = (float(number.text()), note.text().strip()) if accepted else None
    dialog.deleteLater()
    return result


def show_history(parent, label, events):
    dialog, layout = _dialog(parent, f"{label} · 数值留痕")
    table = QTableWidget(len(events), 6)
    table.setHorizontalHeaderLabels(["时间（本机）", "操作方", "量测", "原值", "新值", "说明"])
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    ordered = list(reversed(events))
    for row, event in enumerate(ordered):
        time = datetime.fromisoformat(event["at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        actor = (event.get("operator") or "人工") if event["actor"] == "user" else "系统"
        before = "—" if event["from"] is None else str(event["from"])
        after = "—" if event["to"] is None else str(event["to"])
        values = (time, actor, FIELD_NAMES[event["field"]], before, after, event["note"])
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(row, col, item)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
    layout.addWidget(table, 1)
    source = QLabel()
    source.setTextFormat(Qt.TextFormat.PlainText)
    source.setWordWrap(True)
    source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    def show_source():
        index = table.currentRow()
        if index >= 0:
            event = ordered[index]
            source.setText(f"{event['note']}\nROI 版本  {event.get('roi_ref') or '—'}")
    table.itemSelectionChanged.connect(show_source)
    layout.addWidget(source)
    if ordered:
        table.selectRow(0)
    else:
        source.setText("该量测尚无数值变更记录。")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(850, 370)
    dialog.exec()
    dialog.deleteLater()
