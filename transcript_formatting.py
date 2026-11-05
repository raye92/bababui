"""Transcript page and line formatting shared by the editor and evaluator."""
import re


class TranscriptFormatter:
    """Convert between plain transcript text and numbered, 25-line pages."""

    LINES_PER_PAGE = 25
    numbered_line = re.compile(r"^[ \t]*(?:[1-9]|1[0-9]|2[0-5]) {4}(.*)$")

    def strip_formatting(self, text):
        lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").split("\n")
        if not any(self.numbered_line.match(line) for line in lines):
            # Keep numeric testimony when there are no numbered transcript lines.
            return "\n".join(line for line in lines if line.strip())

        cleaned = []
        for line in lines:
            numbered = self.numbered_line.match(line)
            if numbered:
                content = numbered.group(1)
                if content.strip():
                    cleaned.append(content)
            elif line.strip() and not line.strip().isdecimal():
                cleaned.append(line)
        return "\n".join(cleaned)

    def apply_formatting(self, text):
        lines = [line for line in text.split("\n") if line.strip()]
        if not lines:
            return "\n" * 5, 1

        pages = []
        for offset in range(0, len(lines), self.LINES_PER_PAGE):
            page_lines = lines[offset:offset + self.LINES_PER_PAGE]
            page = ["\n" * 5]
            for number, line in enumerate(page_lines, 1):
                page.append(f"{number:>11}    {line}\n\n")
            for number in range(len(page_lines) + 1, self.LINES_PER_PAGE + 1):
                page.append(f"{number:>11}\n\n")
            page.append(f"\n{len(pages) + 1:>72}")
            pages.append("".join(page))
        return "\n\f".join(pages), len(pages)
