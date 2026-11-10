import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow,
                               QVBoxLayout, QWidget, QToolBar, QMessageBox,
                               QStackedWidget, QPushButton, QSizePolicy, QToolButton, QMenu, QHBoxLayout, QGridLayout, QPlainTextEdit)
from PySide6.QtGui import QFont, QAction, QActionGroup
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from formatter import Formatter
from diff_view import DiffView, LineNumberedEditor
from pathlib import Path
from processing import ProcessingClient, load_config, MODELS, DEFAULT_MODEL, PROMPT_FILE, APP_DIR
from audio_pipeline import AudioPipeline, AUDIO_MODEL
from wav_input import WavInput

# Both files live in src, next to this script.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_FILE = os.path.join(BASE_DIR, "original.txt")
INCOMING_FILE = os.path.join(BASE_DIR, "incoming.txt")


class _BababuiWorker(QThread):
    succeeded = Signal(str, list)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, path, model, config):
        super().__init__()
        self.path, self.model, self.config = path, model, config

    def run(self):
        try:
            client = ProcessingClient(self.config, self.model)
            client.check_ready()
            prompt = PROMPT_FILE.read_text(encoding='utf-8')
            if not prompt.strip():
                raise ValueError('Fill in app/src/bababui_prompt.md before processing.')
            pipeline = AudioPipeline(self.config.get('gemini_api_key', ''), APP_DIR / 'data' / 'transcriptions')
            text, warnings = pipeline.run(self.path, self.progress.emit)
            self.progress.emit('Formatting transcript...')
            result = client.complete(text, prompt)
            self.succeeded.emit(result, warnings)
        except Exception as exc:
            # SDK exceptions can include request details; do not display them.
            message = str(exc) if isinstance(exc, (ValueError, OSError)) else 'API request failed. Check credentials, model access, or quota, then retry.'
            self.failed.emit(message)


class TranscriptEditor(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle("BABABUI")
        self.resize(1000, 800)
        
        # Initialize formatter
        self.formatter = Formatter()

        self.settings = settings if settings is not None else QSettings('BABABUI', 'TranscriptEditor')
        self.processing_model = self.settings.value('processing_model', DEFAULT_MODEL)
        if self.processing_model not in MODELS:
            self.processing_model = DEFAULT_MODEL
        self._busy = False
        self._worker = None
        self._suppress_mirror = False
        self._build_toolbar()

        # --- Views ---
        # The central area swaps wholesale between the original view and the
        # hidden incoming view (no tabs).
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self._build_original_view()   # main stack index 0
        self._build_incoming_view()   # main stack index 1

        self._load_files()

    def _build_toolbar(self):
        self.toolbar = QToolBar('BABABUI', self)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QGridLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setColumnStretch(1, 1)
        left, right = QWidget(), QWidget()
        left_layout, right_layout = QHBoxLayout(left), QHBoxLayout(right)
        for row in (left_layout, right_layout):
            row.setContentsMargins(0, 0, 0, 0)
        self.manual_btn = QToolButton()
        self.manual_btn.setText('Manual')
        self.manual_btn.setPopupMode(QToolButton.InstantPopup)
        manual = QMenu(self.manual_btn)
        for title, callback in [('Strip Formatting', self.strip_formatting),
                                ('Apply Standards', self.apply_formatting),
                                ('Insert Sample', self.insert_sample_text),
                                ('Batch Strip', self.batch_strip_formatting)]:
            manual.addAction(title, callback)
        self.manual_btn.setMenu(manual)
        self.settings_btn = QToolButton()
        self.settings_btn.setText('Settings')
        self.settings_btn.setPopupMode(QToolButton.InstantPopup)
        settings_menu = QMenu(self.settings_btn)
        processing_menu = settings_menu.addMenu('LLM processing model')
        group = QActionGroup(self)
        group.setExclusive(True)
        for model, label in MODELS.items():
            action = processing_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(model == self.processing_model)
            action.triggered.connect(lambda checked, m=model: self.set_processing_model(m))
            group.addAction(action)
        transcription = settings_menu.addMenu('AI transcription model')
        action = transcription.addAction('Gemini 3.5 Transcribe')
        action.setCheckable(True)
        action.setChecked(True)
        action.triggered.connect(lambda: action.setChecked(True))
        self.settings.setValue('transcription_model', AUDIO_MODEL)
        self.settings_btn.setMenu(settings_menu)
        left_layout.addWidget(self.manual_btn)
        left_layout.addWidget(self.settings_btn)
        left_layout.addStretch()
        self.wav_input = WavInput()
        self.bababui_btn = QPushButton('BABABUI')
        self.bababui_btn.clicked.connect(self.run_bababui)
        self.toggle_view_btn = QPushButton('Show Incoming \u25b8')
        self.toggle_view_btn.setMinimumWidth(max(self.toggle_view_btn.fontMetrics().horizontalAdvance(t)
            for t in ('Show Incoming \u25b8', '\u25c2 Back to Original')) + 28)
        self.bababui_btn.setMinimumWidth(max(self.bababui_btn.fontMetrics().horizontalAdvance(t)
            for t in ('BABABUI', 'Working...')) + 28)
        self.toggle_view_btn.clicked.connect(self.toggle_view)
        right_layout.addStretch()
        right_layout.addWidget(self.bababui_btn)
        right_layout.addWidget(self.toggle_view_btn)
        # Equal side columns keep the WAV input centered on the entire window.
        side_width = max(left.sizeHint().width(), right.sizeHint().width())
        left.setFixedWidth(side_width)
        right.setFixedWidth(side_width)
        layout.setColumnMinimumWidth(0, side_width)
        layout.setColumnMinimumWidth(2, side_width)
        layout.addWidget(left, 0, 0)
        layout.addWidget(self.wav_input, 0, 1)
        layout.addWidget(right, 0, 2)
        self.toolbar.addWidget(container)
        self.setMinimumWidth(780)

    def set_processing_model(self, model):
        self.processing_model = model
        self.settings.setValue('processing_model', model)

    def _build_original_view(self):
        """Original view: the transcript editor, which flips to an inline diff
        whenever the incoming text differs from the original."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.original_stack = QStackedWidget()

        # --- Text Editor ---
        # Monospace font is critical for alignment
        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        # Line-numbered editor so the plain view matches the diff view exactly.
        self.editor = LineNumberedEditor(font)
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

        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        # Identical line-numbered editor to the original view.
        self.incoming_editor = LineNumberedEditor(font)
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

    def _view_center_line(self, view):
        """Best-effort 0-based line at the vertical center of a view."""
        getter = getattr(view, 'center_line', None)
        return getter() if getter else 0

    def _apply_center_line(self, view, line):
        """Scroll `view` so `line` is centered, after layout has settled."""
        setter = getattr(view, 'scroll_to_center_line', None)
        if setter:
            # Defer: child geometry / scrollbar range aren't final until the
            # freshly shown view has been laid out.
            QTimer.singleShot(0, lambda: setter(line))

    def toggle_view(self):
        if self.stack.currentIndex() == 0:
            # Remember where we were so the incoming view opens on the same line.
            line = self._view_center_line(self.original_stack.currentWidget())
            # Reveal the hidden incoming text, loaded fresh from disk.
            self._suppress_mirror = True
            self.incoming_editor.setPlainText(self._read_file(INCOMING_FILE))
            self._suppress_mirror = False
            self.stack.setCurrentIndex(1)
            self.toggle_view_btn.setText("\u25c2 Back to Original")
            self._apply_center_line(self.incoming_editor, line)
        else:
            line = self._view_center_line(self.incoming_editor)
            self.stack.setCurrentIndex(0)
            self.toggle_view_btn.setText("Show Incoming \u25b8")
            self._refresh_original_view()
            self._apply_center_line(self.original_stack.currentWidget(), line)

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
            self._set_diff_busy(self._busy)
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
    
    def set_busy(self, busy):
        self._busy = busy
        for control in (self.manual_btn, self.settings_btn, self.wav_input, self.bababui_btn):
            control.setEnabled(not busy)
        self.editor.setReadOnly(busy)
        self.incoming_editor.setReadOnly(busy)
        self._set_diff_busy(busy)
        self.bababui_btn.setText('Working...' if busy else 'BABABUI')

    def _set_diff_busy(self, busy):
        # Keep the scroll area usable while preventing edits and accept/deny.
        for editor in self.diff_view.findChildren(QPlainTextEdit):
            editor.setReadOnly(busy)
        for button in self.diff_view.findChildren(QPushButton):
            button.setEnabled(not busy)

    def run_bababui(self):
        if self._busy:
            return
        if self.wav_input.path is None:
            self.statusBar().showMessage('Choose or drop a WAV file first.')
            return
        self.set_busy(True)
        self._worker = _BababuiWorker(str(self.wav_input.path), self.processing_model, load_config())
        self._worker.progress.connect(self.statusBar().showMessage)
        self._worker.succeeded.connect(self._on_bababui_succeeded)
        self._worker.failed.connect(self._on_bababui_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_bababui_succeeded(self, response, warnings):
        try:
            # Atomic publication prevents a partial incoming file on write failure.
            destination = Path(INCOMING_FILE)
            temporary = destination.with_suffix('.tmp')
            temporary.write_text(response, encoding='utf-8')
            temporary.replace(destination)
            self._suppress_mirror = True
            self.incoming_editor.setPlainText(response)
            self._suppress_mirror = False
            if self.stack.currentIndex() == 0:
                self._refresh_original_view()
            self.statusBar().showMessage('Incoming updated. Review the suggested revisions.' +
                                         (' ' + ' '.join(warnings) if warnings else ''))
            if warnings:
                QMessageBox.warning(self, 'Transcription review notes', '\n\n'.join(warnings))
        except OSError as exc:
            self._on_bababui_failed(f'Could not save Incoming: {exc}')
        finally:
            self._suppress_mirror = False

    def _on_bababui_failed(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, 'BABABUI could not finish', message)

    def _on_worker_finished(self):
        self.set_busy(False)
        self._worker.deleteLater()
        self._worker = None

    def closeEvent(self, event):
        if self._busy:
            self.statusBar().showMessage('Wait for BABABUI to finish before closing the editor.')
            event.ignore()
        else:
            super().closeEvent(event)

    def batch_strip_formatting(self):
        """
        Batch processes all .txt files from 'original' folder
        and saves stripped versions to 'stripped' folder.
        """
        try:
            results = self.formatter.batch_strip_formatting(
                os.path.join(BASE_DIR, 'original'),
                os.path.join(BASE_DIR, 'stripped'),
            )
            
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
