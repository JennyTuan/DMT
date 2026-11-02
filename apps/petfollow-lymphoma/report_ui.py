"""Local review, editing and export of a single exam's descriptive report."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from report_draft import BANNER, ReportDraft


class ReportDialog(QDialog):
    def __init__(self, parent, data_root, bundle_provider):
        super().__init__(parent)
        self.bundle_provider = bundle_provider
        current, prior = bundle_provider()
        self.draft = ReportDraft(data_root, current, prior)
        self.setWindowTitle("淋巴瘤 PET 随访原型 · 描述性报告草稿")
        self.setStyleSheet(
            "QTextBrowser, QPlainTextEdit { background: #191f23; color: #e0e5e7; "
            "border: 1px solid #39434a; padding: 5px; selection-background-color: #344d54; }"
        )
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
        self.generated.setMarkdown(self.draft.generated)
        layout.addWidget(self.generated, 3)
        layout.addWidget(QLabel("描述", objectName="section"))
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("可在此补充部位、层面及量测描述。重新生成时保留此段。")
        self.description.setPlainText(self.draft.description)
        self.description.textChanged.connect(self.edit_description)
        layout.addWidget(self.description, 1)

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
            self.draft.check_current(current, prior)
            self.message.setText("量测区只读。保存草稿会同时保存量测快照与描述。")
        except ValueError as exc:
            self.message.setText(str(exc))

    def edit_description(self):
        self.draft.description = self.description.toPlainText()
        self.message.setText("描述已修改，等待保存。" if self.draft.dirty else "")

    def regenerate(self):
        try:
            self.draft.regenerate(*self.bundle_provider())
            self.generated.setMarkdown(self.draft.generated)
            self.message.setText("已按当前量测重新生成，描述已保留。")
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))

    def save(self):
        try:
            self.draft.save(*self.bundle_provider())
            self.message.setText(f"草稿已保存　{self.draft.path.name}")
            return True
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))
            return False

    def export(self):
        name = f"{self.draft.exam_id}-草稿-{datetime.now():%Y%m%d-%H%M%S}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "将草稿导出为新文件", name, "Markdown (*.md)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".md")
        try:
            self.draft.export(target, *self.bundle_provider())
            self.message.setText(f"已导出　{target}")
        except (OSError, ValueError) as exc:
            self.message.setText(str(exc))

    def reject(self):
        if self.draft.dirty:
            buttons = QMessageBox.StandardButton
            choice = QMessageBox.question(self, BANNER, "是否保存草稿的更改？",
                                          buttons.Save | buttons.Discard | buttons.Cancel,
                                          buttons.Cancel)
            if choice == buttons.Cancel or (choice == buttons.Save and not self.save()):
                return
        super().reject()
