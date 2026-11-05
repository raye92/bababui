from pathlib import Path
import sys

# The desktop editor also runs directly as python app/src/main.py.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transcript_formatting import TranscriptFormatter


class Formatter(TranscriptFormatter):
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
