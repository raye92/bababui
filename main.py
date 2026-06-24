import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit,
                               QVBoxLayout, QWidget, QToolBar, QMessageBox,
                               QStackedWidget, QPushButton, QSizePolicy)
from PySide6.QtGui import QFont, QAction
from PySide6.QtCore import Qt, QThread, Signal
from formatter import Formatter
from diff_view import DiffView
from deepseek import DeepSeekClient

# Both files live in the repo root, next to this script.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_FILE = os.path.join(BASE_DIR, "original.txt")
INCOMING_FILE = os.path.join(BASE_DIR, "incoming.txt")


class _DeepSeekWorker(QThread):
    """Runs a DeepSeek completion off the UI thread."""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, client, prompt):
        super().__init__()
        self._client = client
        self._prompt = prompt

    def run(self):
        try:
            self.succeeded.emit(self._client.complete(self._prompt))
        except Exception as exc:
            self.failed.emit(str(exc))


class TranscriptEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BABABUI")
        self.resize(1000, 800)
        
        # Initialize formatter
        self.formatter = Formatter()

        # DeepSeek client (reads credentials from .env). Created up front but
        # only used when the DEEPSEEK action is triggered.
        self.deepseek = DeepSeekClient()

        # Guards textChanged handlers while we set text programmatically.
        self._suppress_mirror = False

        # --- Toolbar ---
        toolbar = QToolBar("Formatting")
        self.addToolBar(toolbar)

        # Action: Strip Formatting
        strip_action = QAction("Strip Formatting", self)
        strip_action.setStatusTip("Remove line numbers (keeps text indentation)")
        strip_action.triggered.connect(self.strip_formatting)
        toolbar.addAction(strip_action)

        # Action: Apply Formatting
        format_action = QAction("Apply Standards", self)
        format_action.setStatusTip("Apply 1-25 numbering with specific spacing")
        format_action.triggered.connect(self.apply_formatting)
        toolbar.addAction(format_action)

        # Action: Insert Sample
        sample_action = QAction("Insert Sample", self)
        sample_action.triggered.connect(self.insert_sample_text)
        toolbar.addAction(sample_action)
        
        # Action: Batch Strip Formatting
        batch_strip_action = QAction("Batch Strip (original → stripped)", self)
        batch_strip_action.setStatusTip("Process all .txt files in 'original' folder")
        batch_strip_action.triggered.connect(self.batch_strip_formatting)
        toolbar.addAction(batch_strip_action)

        # Button: DEEPSEEK — sends original.txt to DeepSeek and writes the
        # response into incoming.txt. Progress/errors print to the console.
        self.deepseek_btn = QPushButton("DEEPSEEK")
        self.deepseek_btn.clicked.connect(self.run_deepseek)
        toolbar.addWidget(self.deepseek_btn)

        # Spacer pushes the reveal button to the far right of the toolbar.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        # Top-right button: reveals the hidden incoming view (full-window swap).
        self.toggle_view_btn = QPushButton("Show Incoming \u25b8")
        self.toggle_view_btn.clicked.connect(self.toggle_view)
        toolbar.addWidget(self.toggle_view_btn)

        # --- Views ---
        # The central area swaps wholesale between the original view and the
        # hidden incoming view (no tabs).
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._build_original_view()   # main stack index 0
        self._build_incoming_view()   # main stack index 1

        self._load_files()

    def _build_original_view(self):
        """Original view: the transcript editor, which flips to an inline diff
        whenever the incoming text differs from the original."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.original_stack = QStackedWidget()

        # --- Text Editor ---
        self.editor = QPlainTextEdit()
        
        # Monospace font is critical for alignment
        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap) 
        self.editor.textChanged.connect(self._on_editor_changed)

        # Inline diff display (green = added, red = removed) with accept/deny.
        self.diff_view = DiffView()
        self.diff_view.resolved.connect(self._on_diff_resolved)
        # Live edits in equal blocks: just persist, no view switch or re-render.
        self.diff_view.autosaved.connect(self._on_diff_autosaved)

        self.original_stack.addWidget(self.editor)      # index 0: edit mode
        self.original_stack.addWidget(self.diff_view)   # index 1: diff mode

        layout.addWidget(self.original_stack)
        self.stack.addWidget(page)

    def _build_incoming_view(self):
        """Hidden incoming view: editing here is what creates variance between
        the original and the incoming text."""
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

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------
    def _read_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def _write_file(self, path, text):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def _load_files(self):
        original = self._read_file(ORIGINAL_FILE)
        incoming = self._read_file(INCOMING_FILE)

        # Incoming starts as a mirror of the original until it is edited.
        if incoming == "" and original != "":
            incoming = original
            self._write_file(INCOMING_FILE, incoming)

        self._suppress_mirror = True
        self.editor.setPlainText(original)
        self.incoming_editor.setPlainText(incoming)
        self._suppress_mirror = False

        self._refresh_original_view()

    # ------------------------------------------------------------------
    # Mirroring and diffing
    # ------------------------------------------------------------------
    def _on_editor_changed(self):
        if self._suppress_mirror:
            return
        # Editing the transcript editor mirrors straight into incoming, so
        # ordinary edits never create a difference between the two.
        text = self.editor.toPlainText()
        self._write_file(ORIGINAL_FILE, text)
        self._write_file(INCOMING_FILE, text)

    def _on_incoming_changed(self):
        if self._suppress_mirror:
            return
        # Edits in the hidden view only touch incoming -> this is the variance.
        self._write_file(INCOMING_FILE, self.incoming_editor.toPlainText())

    def toggle_view(self):
        if self.stack.currentIndex() == 0:
            # Reveal the hidden incoming text, loaded fresh from disk.
            self._suppress_mirror = True
            self.incoming_editor.setPlainText(self._read_file(INCOMING_FILE))
            self._suppress_mirror = False
            self.stack.setCurrentIndex(1)
            self.toggle_view_btn.setText("\u25c2 Back to Original")
        else:
            self.stack.setCurrentIndex(0)
            self.toggle_view_btn.setText("Show Incoming \u25b8")
            self._refresh_original_view()

    def _refresh_original_view(self):
        """Show the plain editor when the two sides match, otherwise show the
        inline diff with accept/deny controls."""
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
        # Equal-block edit in the diff view: persist both files and keep the
        # hidden incoming editor in sync, but don't switch views or re-render.
        self._write_file(ORIGINAL_FILE, new_original)
        self._write_file(INCOMING_FILE, new_incoming)
        self._suppress_mirror = True
        self.incoming_editor.setPlainText(new_incoming)
        self._suppress_mirror = False

    def _on_diff_resolved(self, new_original, new_incoming):
        # An accept/deny was applied: persist both sides.
        self._write_file(ORIGINAL_FILE, new_original)
        self._write_file(INCOMING_FILE, new_incoming)

        if new_original == new_incoming:
            # Everything reconciled -> hand control back to the editor.
            self._suppress_mirror = True
            self.editor.setPlainText(new_original)
            self.incoming_editor.setPlainText(new_incoming)
            self._suppress_mirror = False
            self.original_stack.setCurrentWidget(self.editor)

    def _active_editor(self):
        """Return the editor the toolbar actions should operate on, or None
        when the original view is currently showing an unresolved diff."""
        if self.stack.currentIndex() == 1:
            return self.incoming_editor
        if self.original_stack.currentWidget() is self.editor:
            return self.editor
        return None

    def insert_sample_text(self):
        """Inserts the sample text provided in your prompt."""
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
        """
        Removes line numbers 1-25 and page numbering.
        Ignores the 5-line headers during the strip process.
        """
        editor = self._active_editor()
        if editor is None:
            self.statusBar().showMessage("Resolve the incoming changes first.")
            return
        raw_text = editor.toPlainText()
        cleaned_text = self.formatter.strip_formatting(raw_text)
        editor.setPlainText(cleaned_text)
        self.statusBar().showMessage("Formatting stripped.")

    def apply_formatting(self):
        """
        Applies:
        1. 5 Newlines at the start of every page.
        2. Numbers 1-25 with strict alignment.
        3. Double spacing between text lines.
        4. Pagination footer.
        """
        editor = self._active_editor()
        if editor is None:
            self.statusBar().showMessage("Resolve the incoming changes first.")
            return
        raw_text = editor.toPlainText()
        formatted_text, page_count = self.formatter.apply_formatting(raw_text)
        editor.setPlainText(formatted_text)
        self.statusBar().showMessage(f"Applied standards: {page_count} pages generated.")
    
    def run_deepseek(self):
        """Send original.txt to DeepSeek and put the response into incoming.txt,
        surfacing it as a diff to review."""
        original = self._read_file(ORIGINAL_FILE)
        if not original.strip():
            print("DeepSeek: original.txt is empty — nothing to send.")
            return
        if not self.deepseek.is_ready():
            print("DeepSeek: not configured — set DEEPSEEK_API_KEY in .env")
            return

        self.deepseek_btn.setEnabled(False)
        self._deepseek_worker = _DeepSeekWorker(self.deepseek, original)
        self._deepseek_worker.succeeded.connect(self._on_deepseek_succeeded)
        self._deepseek_worker.failed.connect(self._on_deepseek_failed)
        self._deepseek_worker.start()

    def _on_deepseek_succeeded(self, response):
        # DeepSeek's reply becomes the proposed incoming version.
        self.deepseek_btn.setEnabled(True)
        self._write_file(INCOMING_FILE, response)
        self._suppress_mirror = True
        self.incoming_editor.setPlainText(response)
        self._suppress_mirror = False
        # Refresh so the original view shows the new diff straight away.
        if self.stack.currentIndex() == 0:
            self._refresh_original_view()
        print(f"DeepSeek: incoming.txt updated ({len(response)} chars).")

    def _on_deepseek_failed(self, message):
        self.deepseek_btn.setEnabled(True)
        print(f"DeepSeek failed: {message}")

    def batch_strip_formatting(self):
        """
        Batch processes all .txt files from 'original' folder
        and saves stripped versions to 'stripped' folder.
        """
        try:
            results = self.formatter.batch_strip_formatting('original', 'stripped')
            
            # Build summary message
            message_parts = []
            
            if results['processed']:
                message_parts.append(f"Successfully processed {len(results['processed'])} file(s):")
                for item in results['processed']:
                    filename = item['input'].split('\\')[-1].split('/')[-1]
                    message_parts.append(f"  ✓ {filename}")
            
            if results['failed']:
                message_parts.append(f"\nFailed to process {len(results['failed'])} file(s):")
                for item in results['failed']:
                    filename = item['file'].split('\\')[-1].split('/')[-1]
                    message_parts.append(f"  ✗ {filename}: {item['error']}")
            
            if results['skipped']:
                message_parts.append("\n" + "\n".join(results['skipped']))
            
            message = "\n".join(message_parts)
            
            # Show results in message box
            if results['failed']:
                QMessageBox.warning(self, "Batch Strip - Partial Success", message)
            else:
                QMessageBox.information(self, "Batch Strip - Complete", message)
            
            self.statusBar().showMessage(f"Batch strip complete: {len(results['processed'])} processed, {len(results['failed'])} failed")
            
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
