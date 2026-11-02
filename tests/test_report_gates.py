import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_report_draft import example
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QFileDialog
from quality_gate import prior_gates, report_gates
from report_draft import ReportDraft, generated_section
from report_ui import ReportDialog


class ReportGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.current = example("followup")
        self.prior = example("baseline")
        self.target = self.root / "草稿.md"

    def test_direct_export_checks_exam_banner_and_linked_prior(self):
        draft = ReportDraft(self.root, self.current, self.prior)
        self.current["exam"]["prototype_banner"] += " "
        with self.assertRaisesRegex(ValueError, "PROTOTYPE_BANNER"):
            draft.export(self.target, self.current, self.prior)
        with self.assertRaisesRegex(ValueError, "PROTOTYPE_BANNER"):
            generated_section(self.current, self.prior)
        self.assertFalse(self.target.exists())
        self.current["exam"]["prototype_banner"] = self.prior["exam"]["prototype_banner"]
        self.prior["exam"]["patient_pseudo_id"] = "another"
        for invalid in (None, self.prior):
            with self.subTest(invalid=invalid is None):
                with self.assertRaisesRegex(ValueError, "PRIOR_BROKEN"):
                    draft.export(self.target, self.current, invalid)
                self.assertFalse(self.target.exists())

    def test_reopen_repair_and_preserve_a_legacy_draft(self):
        first = ReportDraft(self.root, self.current, self.prior)
        first.description = "核对过的层面。"
        first.save(self.current, self.prior)
        saved = json.loads(first.path.read_text(encoding="utf-8"))
        saved["generated"] = "失去文首声明\n" + saved["generated"]
        first.path.write_text(json.dumps(saved), encoding="utf-8")
        original = first.path.read_bytes()

        draft = ReportDraft(self.root, self.current, self.prior)
        with self.assertRaisesRegex(ValueError, "PROTOTYPE_BANNER"):
            draft.save(self.current, self.prior)
        self.assertEqual(first.path.read_bytes(), original)
        draft.regenerate(self.current, self.prior)
        self.assertEqual(draft.description, first.description)
        draft.export(self.target, self.current, self.prior)
        self.assertEqual(self.target.read_bytes(), draft.render_text().encode("utf-8"))

    def test_generated_prior_label_and_edited_text_have_safe_block_messages(self):
        self.prior["lesions"][0]["label"] = "Deauville"
        dialog = ReportDialog(None, self.root, lambda: (self.current, self.prior))
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.assertTrue(dialog.gates.isVisible())
        self.assertEqual(dialog.gates.palette().color(QPalette.ColorRole.Text).name(), "#ff9292")
        self.assertIn("BANNED_TERMS", dialog.gates.toPlainText())
        self.assertNotIn("Deauville", dialog.gates.toPlainText() + dialog.generated.toPlainText())
        self.prior["lesions"][0]["label"] = "纵隔"
        dialog.description.setPlainText("核对层面。")
        dialog.regenerate()
        self.assertNotIn("BANNED_TERMS", dialog.gates.toPlainText())
        dialog.description.setPlainText("Deauville")
        self.assertIn("BANNED_TERMS", dialog.gates.toPlainText())
        self.assertNotIn("Deauville", dialog.gates.toPlainText())
        with patch.object(QFileDialog, "getSaveFileName") as choose:
            dialog.export()
            choose.assert_not_called()
        self.assertFalse(dialog.save())
        self.assertFalse(dialog.draft.path.exists())
        self.assertEqual(dialog.description.toPlainText(), "Deauville")
        dialog.description.setPlainText("核对层面。")
        self.assertTrue(dialog.save())

    def test_track_warning_before_chooser_and_recheck_after_chooser(self):
        self.current["lesions"][0]["lesion_track_id"] = None
        dialog = ReportDialog(None, self.root, lambda: (self.current, self.prior))
        self.addCleanup(dialog.deleteLater)

        def choose(*args, **kwargs):
            self.assertIn("TRACK_INCOMPLETE", dialog.gates.toPlainText())
            self.assertIn("尚无唯一的先验配对", args[1])
            self.prior = None
            return str(self.target), ""

        with patch.object(QFileDialog, "getSaveFileName", side_effect=choose) as chooser:
            dialog.export()
            chooser.assert_called_once()
        self.assertIn("PRIOR_BROKEN", dialog.gates.toPlainText())
        self.assertFalse(self.target.exists())

    def test_provider_honors_skip_checks_written_text_and_avoids_io_on_typing(self):
        self.current["lesions"][0]["lesion_track_id"] = None
        skipped = [self.current["lesions"][0]["lesion_id"]]
        validated = []

        def gates(text=None):
            validated.append(text)
            return (prior_gates(self.current, self.prior, skipped=skipped)
                    + report_gates(self.current, text))

        dialog = ReportDialog(None, self.root, lambda: (self.current, self.prior), gate_provider=gates)
        self.addCleanup(dialog.deleteLater)
        count = len(validated)
        dialog.description.setPlainText("逐层核对。")
        self.assertEqual(len(validated), count)
        self.assertNotIn("TRACK_INCOMPLETE", dialog.gates.toPlainText())
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.target), "")):
            dialog.export()
        self.assertEqual(self.target.read_bytes(), validated[-1].encode("utf-8"))
        self.assertIn("逐层核对。", validated[-1])
