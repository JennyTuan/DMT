"""Build a local, inspectable gate report from the workstation's active study."""
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from quality_gate import BANNER, contains_banned_term, evaluate_bundle
from report_draft import report_text
from roi_store import _local_path, _read_json, _write_json


class QualityReview:
    def __init__(self, pairing):
        self.pairing = pairing
        self.store = pairing.store

    def capture(self, *, recheck=True):
        evidence = self.store.refresh_quality() if recheck else self.store.quality_evidence()
        self.roi_validity, self.field_errors = evidence
        self.current, self.prior, self.skipped = self.pairing.quality_snapshot()
        self.checked_at = datetime.now(timezone.utc).isoformat()
        return self.current, self.prior

    def saved_text(self):
        path = _local_path(self.store.root, Path("data/reports") / (self.store.exam_id + ".json"))
        if not path.exists():
            return None
        draft = _read_json(path)
        if (not isinstance(draft, dict) or draft.get("exam_id") != self.store.exam_id
                or not isinstance(draft.get("generated"), str) or not isinstance(draft.get("description"), str)):
            raise ValueError("已保存的草稿格式与检查不符，请核对草稿文件。")
        return report_text(draft["generated"], draft["description"])

    def record(self, text=None, *, stage="报告检查"):
        results = evaluate_bundle(self.current, self.prior, roi_validity=self.roi_validity,
                                  field_errors=self.field_errors, skipped=self.skipped, text=text)
        path = _local_path(self.store.root, Path("data/gates") / (self.store.exam_id + ".json"))
        _write_json(path, {"version": 1, "exam_id": self.store.exam_id, "checked_at": self.checked_at,
                           "stage": stage, "text_checked": text is not None, "results": results})
        return results


def show_quality(parent, results, exam_id, *, text_checked):
    dialog = QDialog(parent)
    dialog.setWindowTitle("淋巴瘤 PET 随访原型 · 质量门")
    dialog.resize(960, 520)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(BANNER, objectName="dialogBanner"))
    by_level = {"block": "阻断", "review": "需复核", "warn": "提醒", "not_checked": "未检查", "pass": "符合"}
    counts = [f"{name} {sum(r['level'] == level for r in results)}" for level, name in by_level.items()]
    scope = "已核对保存的草稿正文" if text_checked else "尚无已保存草稿，正文将于报告窗口核对"
    exam_display = exam_id if not contains_banned_term(exam_id) else "本次检查"
    layout.addWidget(QLabel(f"当前检查   {exam_display}   ·   {scope}\n" + "    ·    ".join(counts)))
    table = QTableWidget(len(results), 4, objectName="qualityGateTable")
    table.setHorizontalHeaderLabels(["状态", "门控编号", "目标", "原因与操作"])
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    priority = {name: index for index, name in enumerate(by_level)}
    ordered = sorted(results, key=lambda r: priority[r["level"]])
    for index, result in enumerate(ordered):
        target = result["target_id"] if not contains_banned_term(result["target_id"]) else "本条记录"
        short = target if len(target) <= 20 else target[:6] + "…" + target[-8:]
        cells = [by_level[result["level"]], result["gate_id"], short, result["message"] + " · " + result["action"]]
        for column, value in enumerate(cells):
            item = QTableWidgetItem(value)
            item.setToolTip(target if column == 2 else value)
            if result["level"] == "block":
                item.setForeground(QColor("#ff9893"))
            elif column == 0 and result["level"] in ("warn", "review"):
                item.setForeground(QColor("#ebc278"))
            table.setItem(index, column, item)
    layout.addWidget(table, 1)
    detail = QLabel()
    detail.setTextFormat(Qt.TextFormat.PlainText)
    detail.setWordWrap(True)
    detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    def select_result():
        index = table.currentRow()
        if index >= 0:
            row = ordered[index]
            target = table.item(index, 2).toolTip()
            detail.setText(f"{row['gate_id']}    {target}\n{row['message']}   {row['action']}")
    table.itemSelectionChanged.connect(select_result)
    layout.addWidget(detail)
    if results:
        table.selectRow(0)
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    dialog.exec()
    dialog.deleteLater()
