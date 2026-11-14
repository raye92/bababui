"""Transcript page and line formatting shared by the editor and evaluator."""
import re
import textwrap


class TranscriptFormatter:
    """Convert logical transcript paragraphs to wrapped, numbered pages."""

    LINES_PER_PAGE = 25
    LINE_WIDTH = 56
    numbered_line = re.compile(r"^[ \t]*(?:[1-9]|1[0-9]|2[0-5]) {4}(.*)$")
    qa_label = re.compile(r"^[QA](?:\.)?(?:[ \t]+|$)")
    colloquy_label = re.compile(
        r"^(?:SPEAKER \d+|(?:MR|MS|MRS|DR)\. [\w .'-]+|THE [\w .'-]+):",
        re.IGNORECASE,
    )
    structural_line = re.compile(r"^(?:[A-Z -]*EXAMINATION|BY .+:|/{3,})$")
    examination_heading = re.compile(r"^(?:FURTHER )?EXAMINATION$")
    examiner_line = re.compile(r"^BY .+:$")
    numeric_answer = re.compile(r"^[+-]?\d[\d,./:%-]*$")

    def _content_lines(self, text):
        lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").split("\n")
        if not any(self.numbered_line.match(line) for line in lines):
            # Keep numeric testimony when there are no numbered transcript lines.
            return [line for line in lines if line.strip()]

        cleaned = []
        for line in lines:
            numbered = self.numbered_line.match(line)
            if numbered:
                content = numbered.group(1)
                if content.strip():
                    cleaned.append(content)
            elif line.strip() and not line.strip().isdecimal():
                cleaned.append(line)
        return cleaned

    def _starts_paragraph(self, line):
        content = line.lstrip()
        if self.structural_line.fullmatch(content):
            return False
        return bool(
            self.qa_label.match(content)
            or self.colloquy_label.match(content)
            or content.startswith(("(", "["))
            or len(line) - len(content) == 10
        )

    def strip_formatting(self, text):
        """Remove numbering and join only recognizable 56-column continuations."""
        paragraphs = []
        active = False
        previous = ""
        for line in self._content_lines(text):
            starts_paragraph = self._starts_paragraph(line)
            # An unlabeled line is a continuation only when its first word
            # could not fit on the preceding physical line. Other breaks stay.
            continuation = (
                active
                # A reconstructed logical paragraph can exceed the width.
                # It must not absorb the next line on a second strip pass.
                and (len(previous.rstrip()) <= self.LINE_WIDTH or len(previous.split()) == 1)
                and not line[0].isspace()
                and not starts_paragraph
                and not self.structural_line.fullmatch(line.rstrip())
                and not self.numeric_answer.fullmatch(line.strip())
                and len(previous.rstrip()) + 1 + len(line.split()[0]) > self.LINE_WIDTH
            )
            if continuation:
                paragraphs[-1] = paragraphs[-1].rstrip() + " " + line
            else:
                paragraphs.append(line)
                active = starts_paragraph
            previous = line
        return "\n".join(paragraphs)

    def _wrap_paragraph(self, paragraph):
        if self.examination_heading.fullmatch(paragraph.strip()):
            return [paragraph.strip().center(self.LINE_WIDTH).rstrip()]
        content = paragraph.lstrip(" \t")
        indentation = paragraph[:len(paragraph) - len(content)]
        return textwrap.wrap(
            content, width=self.LINE_WIDTH, initial_indent=indentation,
            subsequent_indent="", expand_tabs=False, replace_whitespace=False,
            break_long_words=False, break_on_hyphens=False,
        )

    def apply_formatting(self, text):
        wrapped = [
            line
            for paragraph in self.strip_formatting(text).split("\n") if paragraph.strip()
            for line in self._wrap_paragraph(paragraph)
        ]
        lines = []
        for index, line in enumerate(wrapped):
            # Keep the heading, examiner, and start of the question together.
            if (
                self.examination_heading.fullmatch(line.strip())
                and index + 2 < len(wrapped)
                and self.examiner_line.fullmatch(wrapped[index + 1].strip())
                and self.qa_label.match(wrapped[index + 2].lstrip())
                and wrapped[index + 2].lstrip().startswith("Q")
            ):
                remaining = self.LINES_PER_PAGE - len(lines) % self.LINES_PER_PAGE
                if remaining < 3:
                    lines.extend(["///"] * remaining)
            lines.append(line)
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
