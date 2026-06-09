import sys
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QToolBar,
    QMessageBox,
    QStackedWidget,
    QPushButton,
    QSizePolicy,
    QLabel,
    QFileDialog,
)
from PySide6.QtGui import QFont, QAction
from PySide6.QtCore import Qt

from formatter import Formatter
from diff_view import DiffView
from transcript_pipeline import (
    ReviewSession,
    export_txt,
    generate_suggestions,
    parse_zoom_transcript,
    render_segments,
    sync_document_source_text,
)
from ui.inline_suggestion_review import InlineSuggestionReviewView

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_FILE = os.path.join(BASE_DIR, "original.txt")
INCOMING_FILE = os.path.join(BASE_DIR, "incoming.txt")
SAMPLES_DIR = Path(BASE_DIR) / "samples"
DEFAULT_SPEAKERS = "\n".join(
    [
        "THE COURT",
        "MR. SMITH",
        "MS. JOHNSON",
        "THE WITNESS",
    ]
)


class TranscriptEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BABABUI")
        self.resize(1000, 800)

        self.formatter = Formatter()
        self.review_session: ReviewSession | None = None
        self._suppress_mirror = False

        toolbar = QToolBar("Formatting")
        self.addToolBar(toolbar)

        strip_action = QAction("Strip Formatting", self)
        strip_action.setStatusTip("Remove line numbers (keeps text indentation)")
        strip_action.triggered.connect(self.strip_formatting)
        toolbar.addAction(strip_action)

        format_action = QAction("Apply Standards", self)
        format_action.setStatusTip("Apply 1-25 numbering with specific spacing")
        format_action.triggered.connect(self.apply_formatting)
        toolbar.addAction(format_action)

        sample_action = QAction("Insert Sample", self)
        sample_action.triggered.connect(self.insert_sample_text)
        toolbar.addAction(sample_action)

        batch_strip_action = QAction("Batch Strip (original → stripped)", self)
        batch_strip_action.setStatusTip("Process all .txt files in 'original' folder")
        batch_strip_action.triggered.connect(self.batch_strip_formatting)
        toolbar.addAction(batch_strip_action)

        toolbar.addSeparator()

        analyze_action = QAction("Analyze Suggestions", self)
        analyze_action.setStatusTip("Parse Zoom transcript and generate edit suggestions")
        analyze_action.triggered.connect(self.analyze_suggestions)
        toolbar.addAction(analyze_action)

        accept_all_action = QAction("Accept All", self)
        accept_all_action.triggered.connect(self.accept_all_suggestions)
        toolbar.addAction(accept_all_action)

        reject_all_action = QAction("Reject All", self)
        reject_all_action.triggered.connect(self.reject_all_suggestions)
        toolbar.addAction(reject_all_action)

        apply_action = QAction("Copy to Court Editor", self)
        apply_action.setStatusTip("Copy the current Zoom transcript into the court editor")
        apply_action.triggered.connect(self.copy_to_court_editor)
        toolbar.addAction(apply_action)

        self.edit_raw_action = QAction("Edit Raw Transcript", self)
        self.edit_raw_action.triggered.connect(self.switch_to_raw_transcript)
        toolbar.addAction(self.edit_raw_action)

        export_action = QAction("Export .txt", self)
        export_action.triggered.connect(self.export_transcript)
        toolbar.addAction(export_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self.review_view_btn = QPushButton("Review Suggestions \u25b8")
        self.review_view_btn.clicked.connect(self.toggle_review_view)
        toolbar.addWidget(self.review_view_btn)

        self.toggle_view_btn = QPushButton("Show Incoming \u25b8")
        self.toggle_view_btn.clicked.connect(self.toggle_incoming_view)
        toolbar.addWidget(self.toggle_view_btn)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._build_original_view()
        self._build_incoming_view()
        self._build_review_view()

        self._load_files()

    def _build_original_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.original_stack = QStackedWidget()

        self.editor = QPlainTextEdit()
        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.textChanged.connect(self._on_editor_changed)

        self.diff_view = DiffView()
        self.diff_view.resolved.connect(self._on_diff_resolved)
        self.diff_view.autosaved.connect(self._on_diff_autosaved)

        self.original_stack.addWidget(self.editor)
        self.original_stack.addWidget(self.diff_view)

        layout.addWidget(self.original_stack)
        self.stack.addWidget(page)

    def _build_incoming_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.incoming_editor = QPlainTextEdit()
        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        self.incoming_editor.setFont(font)
        self.incoming_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.incoming_editor.textChanged.connect(self._on_incoming_changed)
        layout.addWidget(self.incoming_editor)

        self.stack.addWidget(page)

    def _build_review_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Zoom Transcript"))
        header_row.addStretch(1)

        zoom_font = QFont("Courier New", 12)
        zoom_font.setStyleHint(QFont.Monospace)

        speakers_panel = QVBoxLayout()
        speakers_panel.addWidget(QLabel("Official Speakers (one per line)"))
        self.speakers_input = QPlainTextEdit()
        self.speakers_input.setPlainText(DEFAULT_SPEAKERS)
        self.speakers_input.setFont(zoom_font)
        self.speakers_input.setMaximumHeight(100)
        speakers_panel.addWidget(self.speakers_input)
        header_row.addLayout(speakers_panel, stretch=1)
        layout.addLayout(header_row)

        self.transcript_stack = QStackedWidget()

        self.zoom_input = QPlainTextEdit()
        self.zoom_input.setPlaceholderText("Paste a Zoom transcript here…")
        self.zoom_input.setFont(zoom_font)
        self.zoom_input.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.transcript_stack.addWidget(self.zoom_input)

        self.suggestion_review = InlineSuggestionReviewView()
        self.suggestion_review.counts_changed.connect(self._update_review_status)
        self.suggestion_review.transcript_changed.connect(self._on_canonical_transcript_changed)
        self.transcript_stack.addWidget(self.suggestion_review)

        layout.addWidget(self.transcript_stack, stretch=1)
        self.stack.addWidget(page)

    def _read_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def _write_file(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _load_files(self):
        original = self._read_file(ORIGINAL_FILE)
        incoming = self._read_file(INCOMING_FILE)

        if incoming == "" and original != "":
            incoming = original
            self._write_file(INCOMING_FILE, incoming)

        self._suppress_mirror = True
        self.editor.setPlainText(original)
        self.incoming_editor.setPlainText(incoming)
        self._suppress_mirror = False

        sample_path = SAMPLES_DIR / "zoom_sample.txt"
        if sample_path.exists() and not self.zoom_input.toPlainText().strip():
            self.zoom_input.setPlainText(sample_path.read_text(encoding="utf-8"))

        self._refresh_original_view()

    def _on_editor_changed(self):
        if self._suppress_mirror:
            return
        text = self.editor.toPlainText()
        self._write_file(ORIGINAL_FILE, text)
        self._write_file(INCOMING_FILE, text)

    def _on_incoming_changed(self):
        if self._suppress_mirror:
            return
        self._write_file(INCOMING_FILE, self.incoming_editor.toPlainText())

    def toggle_incoming_view(self):
        if self.stack.currentIndex() == 1:
            self.stack.setCurrentIndex(0)
            self.toggle_view_btn.setText("Show Incoming \u25b8")
            self._refresh_original_view()
            return

        self._suppress_mirror = True
        self.incoming_editor.setPlainText(self._read_file(INCOMING_FILE))
        self._suppress_mirror = False
        self.stack.setCurrentIndex(1)
        self.toggle_view_btn.setText("\u25c2 Back to Original")

    def toggle_review_view(self):
        if self.stack.currentIndex() == 2:
            self.stack.setCurrentIndex(0)
            self.review_view_btn.setText("Review Suggestions \u25b8")
            self._refresh_original_view()
            return

        self.stack.setCurrentIndex(2)
        self.review_view_btn.setText("\u25c2 Back to Editor")

    def _refresh_original_view(self):
        original = self._read_file(ORIGINAL_FILE)
        incoming = self._read_file(INCOMING_FILE)

        if original == incoming:
            self._suppress_mirror = True
            self.editor.setPlainText(original)
            self._suppress_mirror = False
            self.original_stack.setCurrentWidget(self.editor)
        else:
            self.diff_view.set_texts(original, incoming)
            self.original_stack.setCurrentWidget(self.diff_view)

    def _on_diff_autosaved(self, new_original, new_incoming):
        self._write_file(ORIGINAL_FILE, new_original)
        self._write_file(INCOMING_FILE, new_incoming)
        self._suppress_mirror = True
        self.incoming_editor.setPlainText(new_incoming)
        self._suppress_mirror = False

    def _on_diff_resolved(self, new_original, new_incoming):
        self._write_file(ORIGINAL_FILE, new_original)
        self._write_file(INCOMING_FILE, new_incoming)

        if new_original == new_incoming:
            self._suppress_mirror = True
            self.editor.setPlainText(new_original)
            self.incoming_editor.setPlainText(new_incoming)
            self._suppress_mirror = False
            self.original_stack.setCurrentWidget(self.editor)

    def _active_editor(self):
        if self.stack.currentIndex() == 1:
            return self.incoming_editor
        if self.stack.currentIndex() == 0 and self.original_stack.currentWidget() is self.editor:
            return self.editor
        return None

    def _official_speakers(self) -> list[str]:
        return [
            line.strip()
            for line in self.speakers_input.toPlainText().splitlines()
            if line.strip()
        ]

    def analyze_suggestions(self):
        raw_text = self.zoom_input.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Analyze Suggestions", "Paste a Zoom transcript first.")
            return

        speakers = self._official_speakers()
        if not speakers:
            QMessageBox.warning(self, "Analyze Suggestions", "Enter at least one official speaker.")
            return

        try:
            document = parse_zoom_transcript(
                raw_text,
                metadata={"official_speakers": speakers},
            )
            suggestions = generate_suggestions(
                document,
                context={"official_speakers": speakers},
            )
            self.review_session = ReviewSession(document=document, suggestions=suggestions)
            sync_document_source_text(document)
            self.suggestion_review.set_session(self.review_session)
            self.transcript_stack.setCurrentIndex(1)
            self.edit_raw_action.setEnabled(True)
            self.stack.setCurrentIndex(2)
            self.review_view_btn.setText("\u25c2 Back to Editor")
            self._update_review_status(self.review_session.summary())
        except Exception as exc:
            QMessageBox.critical(self, "Analyze Suggestions", str(exc))
            self.statusBar().showMessage("Suggestion analysis failed.")

    def accept_all_suggestions(self):
        if self.review_session is None:
            self.statusBar().showMessage("Analyze a transcript first.")
            return
        self.suggestion_review.accept_all_pending()
        self._update_review_status(self.review_session.summary())

    def reject_all_suggestions(self):
        if self.review_session is None:
            self.statusBar().showMessage("Analyze a transcript first.")
            return
        self.suggestion_review.reject_all_pending()
        self._update_review_status(self.review_session.summary())

    def _on_canonical_transcript_changed(self, text: str):
        self.statusBar().showMessage("Transcript updated.")

    def switch_to_raw_transcript(self):
        if self.review_session is not None:
            self.zoom_input.setPlainText(self.review_session.document.source_text)
        self.transcript_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Editing raw Zoom transcript.")

    def _current_zoom_transcript(self) -> str:
        if self.transcript_stack.currentIndex() == 1 and self.review_session is not None:
            return self.review_session.document.source_text
        return self.zoom_input.toPlainText()

    def _update_review_status(self, summary: dict):
        pending = summary.get("pending", 0)
        accepted = summary.get("accepted", 0)
        rejected = summary.get("rejected", 0)
        self.statusBar().showMessage(
            f"Suggestions: {accepted} accepted, {rejected} rejected, {pending} pending"
        )

    def _confirm_pending_suggestions(self, action_name: str) -> bool:
        if self.review_session is None or self.review_session.pending_count() == 0:
            return True

        pending = self.review_session.pending_count()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Pending Suggestions")
        box.setText(
            f"{pending} suggestion(s) are still pending.\n"
            f"Continuing with {action_name} will use only accepted edits."
        )
        box.addButton("Go Back", QMessageBox.ButtonRole.RejectRole)
        continue_btn = box.addButton("Continue Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        return box.clickedButton() == continue_btn

    def copy_to_court_editor(self):
        if self.review_session is None:
            QMessageBox.warning(self, "Copy to Court Editor", "Analyze a transcript first.")
            return

        if not self._confirm_pending_suggestions("Copy to Court Editor"):
            return

        text = render_segments(self.review_session.document)
        self._suppress_mirror = True
        self.editor.setPlainText(text)
        self.incoming_editor.setPlainText(text)
        self._suppress_mirror = False
        self._write_file(ORIGINAL_FILE, text)
        self._write_file(INCOMING_FILE, text)

        self.stack.setCurrentIndex(0)
        self.review_view_btn.setText("Review Suggestions \u25b8")
        self.original_stack.setCurrentWidget(self.editor)
        self.statusBar().showMessage("Copied Zoom transcript into court editor.")

    def export_transcript(self):
        if self.stack.currentIndex() == 2:
            if self.review_session is None:
                text = self.zoom_input.toPlainText()
            else:
                if not self._confirm_pending_suggestions("Export"):
                    return
                text = self.review_session.document.source_text
        else:
            editor = self._active_editor()
            if editor is None:
                self.statusBar().showMessage("Open the editor to export.")
                return
            text = editor.toPlainText()

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Transcript",
            "",
            "Text Files (*.txt)",
        )
        if not path:
            return

        if not path.endswith(".txt"):
            path += ".txt"

        try:
            export_txt(path, text)
        except Exception as exc:
            QMessageBox.critical(self, "Export .txt", str(exc))
            return

        self.statusBar().showMessage(f"Exported transcript to {path}")

    def insert_sample_text(self):
        sample = """




          1                           EXAMINATION

          2    BY MS. MADSEN:

          3         Q    And good morning, everybody.  My name is

          4    Stacey Madsen.  I'm with LMLA, and I represent the

          5    defendants here.

          6              Are we ready to proceed right now?

          7         A    I'm good.

          8         MS. MADSEN:  Counsel?

          9         MR. SIMMONS:  Fired up.

         10    BY MS. MADSEN:

         11         Q    All right, Doctor, how would you like me to

         12    refer to you?

         13         A    Jordan is fine.

         14         Q    Is that the only name you've used?

         15         A    Yes.

         16         Q    Approximately how many times have you been in

         17    a deposition or a cross examination?

         18         A    Over 50.

         19         Q    Okay.

         20         MS. MADSEN:  Counsel, do you stipulate to waive the

         21    admonitions?

         22         THE WITNESS:  I'm fine to waive.

         23    BY MS. MADSEN:

         24         Q    I feel uncomfortable asking you without him

         25    here, I'm just going to go over the basics, your


                                                                       1"""
        editor = self._active_editor()
        if editor is None:
            self.statusBar().showMessage("Resolve the incoming changes first.")
            return
        editor.setPlainText(sample)

    def strip_formatting(self):
        editor = self._active_editor()
        if editor is None:
            self.statusBar().showMessage("Resolve the incoming changes first.")
            return
        raw_text = editor.toPlainText()
        cleaned_text = self.formatter.strip_formatting(raw_text)
        editor.setPlainText(cleaned_text)
        self.statusBar().showMessage("Formatting stripped.")

    def apply_formatting(self):
        if not self._confirm_pending_suggestions("Apply Standards"):
            return

        editor = self._active_editor()
        if editor is None:
            self.statusBar().showMessage("Resolve the incoming changes first.")
            return
        raw_text = editor.toPlainText()
        formatted_text, page_count = self.formatter.apply_formatting(raw_text)
        editor.setPlainText(formatted_text)
        self.statusBar().showMessage(f"Applied standards: {page_count} pages generated.")

    def batch_strip_formatting(self):
        try:
            results = self.formatter.batch_strip_formatting("original", "stripped")

            message_parts = []

            if results["processed"]:
                message_parts.append(f"Successfully processed {len(results['processed'])} file(s):")
                for item in results["processed"]:
                    filename = item["input"].split("\\")[-1].split("/")[-1]
                    message_parts.append(f"  ✓ {filename}")

            if results["failed"]:
                message_parts.append(f"\nFailed to process {len(results['failed'])} file(s):")
                for item in results["failed"]:
                    filename = item["file"].split("\\")[-1].split("/")[-1]
                    message_parts.append(f"  ✗ {filename}: {item['error']}")

            if results["skipped"]:
                message_parts.append("\n" + "\n".join(results["skipped"]))

            message = "\n".join(message_parts)

            if results["failed"]:
                QMessageBox.warning(self, "Batch Strip - Partial Success", message)
            else:
                QMessageBox.information(self, "Batch Strip - Complete", message)

            self.statusBar().showMessage(
                f"Batch strip complete: {len(results['processed'])} processed, "
                f"{len(results['failed'])} failed"
            )

        except FileNotFoundError as e:
            QMessageBox.critical(self, "Error", str(e))
            self.statusBar().showMessage("Batch strip failed: folder not found")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")
            self.statusBar().showMessage("Batch strip failed")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriptEditor()
    window.show()
    sys.exit(app.exec())
