import re
import os
from pathlib import Path


class Formatter:
    """Handles formatting and stripping of transcript text."""
    
    def __init__(self):
        self.LINES_PER_PAGE = 25
    
    def strip_formatting(self, text):
        """
        Removes line numbers 1-25 and page numbering.
        Ignores the 5-line headers during the strip process.
        
        Args:
            text (str): Raw text with formatting
            
        Returns:
            str: Cleaned text without formatting
        """
        lines = text.split('\n')
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
                # Group 1 is the text AFTER the 4 spaces.
                # This preserves internal spacing (like indentation for Q/A).
                content = match.group(1) 
                cleaned_lines.append(content)
            
            elif page_footer_pattern.match(line):
                continue
            
            else:
                # Keep lines that appear to be raw text already
                cleaned_lines.append(line)

        # Join with single newline for clean editing
        return "\n".join(cleaned_lines)
    
    def apply_formatting(self, text):
        """
        Applies:
        1. 5 Newlines at the start of every page.
        2. Numbers 1-25 with strict alignment.
        3. Double spacing between text lines.
        4. Pagination footer.
        
        Args:
            text (str): Raw text without formatting
            
        Returns:
            tuple: (formatted_text, page_count)
        """
        lines = text.split('\n')
        
        # We build the string manually to handle distinct header vs text spacing
        final_output = ""
        
        line_counter = 1
        page_counter = 1

        # Initial Header for Page 1
        final_output += "\n" * 5

        for line in lines:
            if not line.strip():
                continue

            # Format line with right-aligned number (11 chars) + 4 spaces + content + double spacing
            final_output += f"{line_counter:>11}    {line}\n\n"

            if line_counter == self.LINES_PER_PAGE:
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
        if line_counter > 1 and line_counter <= self.LINES_PER_PAGE:
            while line_counter <= self.LINES_PER_PAGE:
                final_output += f"{line_counter:>11}\n\n"
                line_counter += 1
            
            # After filling the page, add the final footer
            final_output += f"\n{page_counter:>72}"

        return final_output, page_counter
    
    def batch_strip_formatting(self, input_folder, output_folder):
        """
        Batch processes all text files in the input folder,
        strips formatting, and saves to output folder.
        
        Args:
            input_folder (str): Path to folder containing formatted text files
            output_folder (str): Path to folder where stripped files will be saved
            
        Returns:
            dict: Summary of processed files with status
        """
        input_path = Path(input_folder)
        output_path = Path(output_folder)
        
        # Create output folder if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)
        
        results = {
            'processed': [],
            'failed': [],
            'skipped': []
        }
        
        # Check if input folder exists
        if not input_path.exists():
            raise FileNotFoundError(f"Input folder '{input_folder}' does not exist")
        
        # Process all .txt files in the input folder
        text_files = list(input_path.glob('*.txt'))
        
        if not text_files:
            results['skipped'].append('No .txt files found in input folder')
            return results
        
        for file_path in text_files:
            try:
                # Read the file
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Strip formatting
                stripped_content = self.strip_formatting(content)
                
                # Write to output folder with same filename
                output_file = output_path / file_path.name
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(stripped_content)
                
                results['processed'].append({
                    'input': str(file_path),
                    'output': str(output_file),
                    'status': 'success'
                })
                
            except Exception as e:
                results['failed'].append({
                    'file': str(file_path),
                    'error': str(e)
                })
        
        return results
