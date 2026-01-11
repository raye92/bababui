import sys
import re
from PySide6.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit, 
                               QVBoxLayout, QWidget, QToolBar)
from PySide6.QtGui import QFont, QAction

class TranscriptEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BABABUI")
        self.resize(1000, 800)

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
        lines = raw_text.split('\n')
        cleaned_lines = []

        # Regex: Start + Whitespace + Digits + EXACTLY 4 spaces + Content
        # This catches "          1    Text" and "         10    Text"
        pattern = re.compile(r"^\s*\d+ {4}(.*)")
        
        # Regex: Page numbers (solitary digits)
        page_footer_pattern = re.compile(r"^\s*\d+\s*$")

        for line in lines:
            # Skip purely empty lines (this removes the 5-line headers and double spacing)
            if not line.strip():
                continue

            match = pattern.match(line)
            if match:
                # Group 2 is the text AFTER the 4 spaces.
                # This preserves internal spacing (like indentation for Q/A).
                content = match.group(1) 
                cleaned_lines.append(content)
            
            elif page_footer_pattern.match(line):
                continue
            
            else:
                # Keep lines that appear to be raw text already
                cleaned_lines.append(line)

        # Join with single newline for clean editing
        self.editor.setPlainText("\n".join(cleaned_lines))
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
        lines = raw_text.split('\n')
        
        # We build the string manually to handle distinct header vs text spacing
        final_output = ""
        
        line_counter = 1
        page_counter = 1
        LINES_PER_PAGE = 25

        # Initial Header for Page 1
        final_output += "\n" * 5

        for line in lines:
            if not line.strip():
                continue

            # Format line with right-aligned number (11 chars) + 4 spaces + content + double spacing
            final_output += f"{line_counter:>11}    {line}\n\n"

            if line_counter == LINES_PER_PAGE:
                # Page footer with form feed
                final_output += f"\n{page_counter:>72}\n\f"
                # Start next page with 5 newlines header
                final_output += "\n" * 5
                line_counter = 1
                page_counter += 1
            else:
                line_counter += 1

        # --- Ensure we have exactly 25 lines per page ---
        # If we finished the text but haven't reached line 25, fill the rest.
        if line_counter > 1 and line_counter <= LINES_PER_PAGE:
            while line_counter <= LINES_PER_PAGE:
                final_output += f"{line_counter:>11}\n\n"
                line_counter += 1
            
            # After filling the page, add the final footer
            final_output += f"\n{page_counter:>72}"

        self.editor.setPlainText(final_output)
        self.statusBar().showMessage(f"Applied standards: {page_counter} pages generated.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriptEditor()
    window.show()
    sys.exit(app.exec())