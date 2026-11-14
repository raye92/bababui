"""Content alignment for transcripts, independent of their printed page layout."""
from dataclasses import dataclass
import re

from shared.transcript_formatting import TranscriptFormatter


@dataclass
class Block:
    text: str
    kind: str
    source_start: int = 0
    source_end: int = 0
    indent: str = ''
    paragraph_start: bool = False


_formatter = TranscriptFormatter()


def is_formatted(text):
    # Only recognize the app's printed number column, not numeric testimony.
    return any(re.match(r'^ {9,10}\d{1,2} {4}', line) for line in text.split('\n'))


def _kind(text):
    if re.match(r'^Q(?:\.|\s|$)', text):
        return 'question'
    if re.match(r'^A(?:\.|\s|$)', text):
        return 'answer'
    if _formatter.examiner_line.fullmatch(text):
        return 'examiner'
    if _formatter.structural_line.fullmatch(text):
        return 'heading'
    if _formatter.colloquy_label.match(text):
        return 'speaker'
    if text.startswith(('(', '[')):
        return 'note'
    return 'text'


def parse_transcript(text):
    """Remove generated layout, preserving content and physical scroll locations."""
    numbered = is_formatted(text)
    blocks = []
    previous = ''
    for index, raw in enumerate(text.replace('\r\n', '\n').replace('\r', '\n').split('\n')):
        line = raw.replace('\f', '').rstrip()
        match = _formatter.numbered_line.match(line) if numbered else None
        if match:
            line = match.group(1)
            if line.strip() == '///':  # generated end-of-page padding
                continue
        elif numbered and line.strip().isdecimal() and line.startswith(' ' * 9):
            continue  # empty numbered lines and page numbers
        content = ' '.join(line.split())
        if not content:
            continue
        kind = _kind(content)
        indent = line[:len(line)-len(line.lstrip())]
        explicit = bool(indent) and kind == 'text'
        numeric = _formatter.numeric_answer.fullmatch(content)
        printed_wrap = (numbered and blocks and not line[0].isspace()
                        and len(previous) <= _formatter.LINE_WIDTH
                        and len(previous) + 1 + len(content.split()[0]) > _formatter.LINE_WIDTH
                        and blocks[-1].kind in ('question', 'answer', 'speaker', 'note', 'text')
                        and kind == 'text')
        # Wraps within a turn are presentation, regardless of column width.
        # Explicit numeric answers and structural boundaries remain separate.
        wrapped_text = (blocks and blocks[-1].kind == 'text'
                        and not _formatter.numeric_answer.fullmatch(blocks[-1].text)
                        and len(previous) <= _formatter.LINE_WIDTH
                        and len(previous) + 1 + len(content.split()[0]) > _formatter.LINE_WIDTH)
        continuation = printed_wrap or (blocks and kind == 'text' and not numeric
                        and (blocks[-1].kind in ('question', 'answer', 'speaker', 'note') or wrapped_text)
                        and not explicit)
        if continuation:
            blocks[-1].text += ' ' + content
            blocks[-1].source_end = index + 1
        else:
            blocks.append(Block(content, kind, index, index + 1, indent, explicit))
        previous = line
    return blocks


def render_blocks(blocks, formatted=False):
    if not formatted:
        return '\n'.join(b.indent + b.text for b in blocks)
    paragraphs = []
    for block in blocks:
        text = block.indent + block.text
        if block.kind in ('question', 'answer'):
            label, _, body = block.text.partition(' ')
            text = '     ' + label + ('    ' + body if body else '')
        paragraphs.append(text)
    return _formatter.apply_formatting('\n'.join(paragraphs))[0]


def align_blocks(left, right):
    """Align normalized question turns with the advanced diff engine."""
    if equivalent_content(left, right):
        return [('equal', 0, len(left), 0, len(right))]
    from app.src.advanced_diff import paragraph_ops
    direct = paragraph_ops([block.text for block in left], [block.text for block in right])
    # Pure insertions/deletions already preserve every surviving source block.
    if {op[0] for op in direct} <= {'equal', 'insert'} or {op[0] for op in direct} <= {'equal', 'delete'}:
        return direct

    def units(blocks):
        result = []
        for index, block in enumerate(blocks):
            if result and result[-1].kind == 'question' and block.kind in ('answer', 'text'):
                result[-1].source_end = index+1
            else:
                result.append(Block(block.text, block.kind, index, index+1))
        return result

    a, b = units(left), units(right)
    result = []
    for tag, i, end, j, stop in paragraph_ops([unit.text for unit in a], [unit.text for unit in b]):
        i1 = a[i].source_start if i < len(a) else len(left)
        i2 = a[end-1].source_end if end > i else i1
        j1 = b[j].source_start if j < len(b) else len(right)
        j2 = b[stop-1].source_end if stop > j else j1
        if tag in ('insert', 'delete'):
            result.append((tag, i1, i2, j1, j2))
            continue
        if end-i == stop-j == 1 and a[i].kind == b[j].kind == 'question':
            result.append(('equal' if left[i1].text == right[j1].text else 'replace', i1, i1+1, j1, j1+1))
            i1 += 1
            j1 += 1
        result.extend((op, x+i1, y+i1, z+j1, w+j1) for op, x, y, z, w in paragraph_ops(
            [block.text for block in left[i1:i2]], [block.text for block in right[j1:j2]]))
    return result


def word_spans(left, right):
    """Expose advanced diff's inner changes with exact source character offsets."""
    from app.src.advanced_diff import text_edits
    changes = text_edits(left, right)
    return ([(a, b) for a, b, _, _ in changes if a != b],
            [(c, d) for _, _, c, d in changes if c != d])


def equivalent_content(left, right):
    def signature(blocks):
        return ' '.join(('\x00 ' if b.paragraph_start else '') + b.text for b in blocks)
    return bool(left and right) and signature(left) == signature(right)
