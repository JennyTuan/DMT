"""Local review, editing and export of a single exam's descriptive report."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from report_draft import BANNER, ReportDraft, gate_line


class ReportDialog(QDialog):
    def __init__(self, parent, data_root, bundle_provider, *, gate_provider=None):
        super().__init__(parent)
        self.bundle_provider = bundle_provider
        current, prior = bundle_provider()
        self.draft = ReportDraft(data_root, current, prior, gate_provider=gate_provider)
        self.setWindowTitle("淋巴瘤 PET 随访原型 · 描述性报告草稿")
        self.resize(900, 660)
        layout = QVBoxLayout(self)
        self.banner = QLabel(BANNER, objectName="dialogBanner")
        layout.addWidget(self.banner)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("检查与病灶对照", objectName="section"))
        heading.addStretch()
        self.regenerate_button = QPushButton("从当前量测重新生成")
        self.regenerate_button.clicked.connect(self.regenerate)
        heading.addWidget(self.regenerate_button)
        layout.addLayout(heading)

        self.generated = QTextBrowser()
        self.generated.setOpenLinks(False)
        self._displayed_section = None
        layout.addWidget(self.generated, 3)
        layout.addWidget(QLabel("描述", objectName="section"))
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("可在此补充部位、层面及量测描述。重新生成时保留此段。")
        self.description.setPlainText(self.draft.description)
        self.description.textChanged.connect(self.edit_description)
        layout.addWidget(self.description, 1)

        self.gates = QPlainTextEdit(objectName="reportGates")
        self.gates.setReadOnly(True)
        self.gates.setAccessibleName("报告质量门")
        self.gates.setMaximumHeight(92)
        layout.addWidget(self.gates)
        self.message = QLabel(objectName="muted")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        footer = QHBoxLayout()
        footer.addStretch()
        self.save_button = QPushButton("保存草稿", objectName="primary")
        self.save_button.clicked.connect(self.save)
        self.export_button = QPushButton("导出 Markdown…")
        self.export_button.clicked.connect(self.export)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        for button in (self.save_button, self.export_button, close):
            footer.addWidget(button)
        layout.addLayout(footer)
        try:
            self.draft.check_fresh(current, prior)
            self.show_status("量测区只读。保存草稿会同时保存量测快照与描述。")
        except ValueError as exc:
            self.show_status(str(exc))

    def show_status(self, message):
        levels = {"block": "阻断", "review": "待复核", "warn": "导出提醒", "not_checked": "未核对"}
        priority = ("block", "warn", "review", "not_checked")
        issues = sorted((r for r in self.draft.gate_results if r["level"] != "pass"),
                        key=lambda r: priority.index(r["level"]))
        blocked = any(r["level"] == "block" for r in issues)
        color = "#ff9292" if blocked else "#e5ba76"
        self.gates.setStyleSheet(f"QPlainTextEdit#reportGates {{color: {color};}}")
        self.gates.setPlainText("\n".join(f"{levels[r['level']]}　{gate_line(r)}" for r in issues))
        self.gates.setVisible(bool(issues))
        # A blocked saved or imported section may contain excluded text or prior data.
        # Keep the author's editable description available for correction.
        section = "" if blocked else self.draft.generated
        if section != self._displayed_section:
            if blocked:
                self.generated.setPlainText("预览已阻断。请核对质量门提示后重新生成。")
            else:
                self.generated.setMarkdown(section)
            self._displayed_section = section
        self.message.setText(message)

    def edit_description(self):
        self.draft.description = self.description.toPlainText()
        self.draft.refresh_text_gates()
        self.show_status("描述已修改，等待保存。" if self.draft.dirty else "")

    def regenerate(self):
        try:
            self.draft.regenerate(*self.bundle_provider())
            self.show_status("已按当前量测重新生成，描述已保留。")
        except (OSError, ValueError) as exc:
            self.show_status(str(exc))

    def save(self):
        try:
            self.draft.save(*self.bundle_provider())
            self.show_status(f"草稿已保存　{self.draft.path.name}")
            return True
        except (OSError, ValueError) as exc:
            self.show_status(str(exc))
            return False

    def export(self):
        try:
            self.draft.check_current(*self.bundle_provider())
            self.show_status("已核对本次导出草稿。")
        except (OSError, ValueError) as exc:
            self.show_status(str(exc))
            return
        name = f"{self.draft.exam_id}-草稿-{datetime.now():%Y%m%d-%H%M%S}.md"
        title = BANNER + " · 将草稿导出为新文件"
        if any(r["gate_id"] == "TRACK_INCOMPLETE" and r["level"] == "warn" for r in self.draft.gate_results):
            title += "（部分病灶尚无唯一的先验配对）"
        path, _ = QFileDialog.getSaveFileName(
            self, title, name, "Markdown (*.md)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        try:
            self.draft.export(target, *self.bundle_provider())
            self.show_status(f"已导出　{target}")
        except (OSError, ValueError) as exc:
            self.show_status(str(exc))

    def reject(self):
        if self.draft.dirty:
            buttons = QMessageBox.StandardButton
            choice = QMessageBox.question(self, BANNER, "是否保存草稿的更改？",
                                          buttons.Save | buttons.Discard | buttons.Cancel,
                                          buttons.Cancel)
            if choice == buttons.Cancel or (choice == buttons.Save and not self.save()):
                return
        super().reject()
