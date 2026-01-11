import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit, 
                               QVBoxLayout, QWidget, QToolBar, QMessageBox)
from PySide6.QtGui import QFont, QAction
from formatter import Formatter

class TranscriptEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BABABUI")
        self.resize(1000, 800)
        
        # Initialize formatter
        self.formatter = Formatter()

        # Main Layout container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

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

        # --- Text Editor ---
        self.editor = QPlainTextEdit()
        
        # Monospace font is critical for alignment
        font = QFont("Courier New", 12)
        font.setStyleHint(QFont.Monospace)
        self.editor.setFont(font)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap) 
        
        layout.addWidget(self.editor)

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
        self.editor.setPlainText(sample)

    def strip_formatting(self):
        """
        Removes line numbers 1-25 and page numbering.
        Ignores the 5-line headers during the strip process.
        """
        raw_text = self.editor.toPlainText()
        cleaned_text = self.formatter.strip_formatting(raw_text)
        self.editor.setPlainText(cleaned_text)
        self.statusBar().showMessage("Formatting stripped.")

    def apply_formatting(self):
        """
        Applies:
        1. 5 Newlines at the start of every page.
        2. Numbers 1-25 with strict alignment.
        3. Double spacing between text lines.
        4. Pagination footer.
        """
        raw_text = self.editor.toPlainText()
        formatted_text, page_count = self.formatter.apply_formatting(raw_text)
        self.editor.setPlainText(formatted_text)
        self.statusBar().showMessage(f"Applied standards: {page_count} pages generated.")
    
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