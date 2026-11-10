"""Content alignment for transcripts, independent of their printed page layout."""
from collections import Counter
from bisect import bisect_left
from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from transcript_formatting import TranscriptFormatter


@dataclass
class Block:
    text: str
    kind: str
    source_start: int = 0
    source_end: int = 0
    indent: str = ''
    paragraph_start: bool = False


_formatter = TranscriptFormatter()
_tokens = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)


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


def _align_gap(left, right, oi, oj):
    """Ordered edit-distance alignment; similar turns cost less than delete+insert."""
    n, m = len(left), len(right)
    bags_a = [Counter(_tokens.findall(b.text.casefold())) for b in left]
    bags_b = [Counter(_tokens.findall(b.text.casefold())) for b in right]
    sizes_a = [sum(b.values()) for b in bags_a]
    sizes_b = [sum(b.values()) for b in bags_b]
    if n * m > 10000:
        anchors = _rare_anchors(left, right, bags_a, bags_b)
        if anchors:
            ops, i, j = [], 0, 0
            for ai, bj in anchors + [(n, m)]:
                ops.extend(_align_gap(left[i:ai], right[j:bj], oi+i, oj+j))
                if ai < n:
                    tag = 'equal' if left[ai].text == right[bj].text else 'replace'
                    ops.append((tag, oi+ai, oi+ai+1, oj+bj, oj+bj+1))
                i, j = ai+1, bj+1
            return ops
    costs = [[0.] * (m + 1) for _ in range(n + 1)]
    steps = {}
    for i in range(n + 1):
        costs[i][0] = i
    for j in range(m + 1):
        costs[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            a, b = left[i-1], right[j-1]
            options = [(costs[i-1][j] + 1, 1, 0, 'delete'),
                       (costs[i][j-1] + 1, 0, 1, 'insert')]
            if a.kind == b.kind:
                similarity = 2 * sum((bags_a[i-1] & bags_b[j-1]).values()) / max(1, sizes_a[i-1] + sizes_b[j-1])
                equal = a.text == b.text
                # A low-similarity pair is still a replacement when it occupies
                # the same structural position, but stronger pairs win globally.
                options.insert(0, (costs[i-1][j-1] + (0 if equal else 1.9 - 1.8 * similarity),
                                   1, 1, 'equal' if equal else 'replace'))
            # Unlabeled paragraph splits/joins do not constitute content edits.
            if a.kind == b.kind == 'text':
                for count in _joined_counts(left, i, b.text):
                    options.insert(0, (costs[i-count][j-1], count, 1, 'equal'))
                for count in _joined_counts(right, j, a.text):
                    options.insert(0, (costs[i-1][j-count], 1, count, 'equal'))
            best = min(options, key=lambda option: option[0])
            costs[i][j], di, dj, tag = best
            steps[i, j] = (di, dj, tag)
    ops = []
    i, j = n, m
    while i or j:
        di, dj, tag = steps.get((i, j), (1, 0, 'delete') if i else (0, 1, 'insert'))
        ops.append((tag, oi+i-di, oi+i, oj+j-dj, oj+j))
        i, j = i-di, j-dj
    return list(reversed(ops))


def _rare_anchors(left, right, bags_a, bags_b):
    """Partition large changed ranges at strong, unambiguous shared-word matches."""
    locations = []
    for bags in (bags_a, bags_b):
        where = {}
        for index, bag in enumerate(bags):
            for token in bag:
                where[token] = index if token not in where else None
        locations.append(where)
    pairs = {(i, locations[1][token]) for token, i in locations[0].items()
             if i is not None and locations[1].get(token) is not None}
    by_left, by_right = Counter(i for i, _ in pairs), Counter(j for _, j in pairs)
    candidates = []
    for i, j in sorted(pairs):
        if by_left[i] != 1 or by_right[j] != 1 or left[i].kind != right[j].kind:
            continue
        score = 2 * sum((bags_a[i] & bags_b[j]).values()) / (sum(bags_a[i].values()) + sum(bags_b[j].values()))
        if score >= .7:
            candidates.append((i, j))
    # Keep only an increasing chain: matching must never reorder testimony.
    tails, tail_indices, previous = [], [], []
    for index, (_, j) in enumerate(candidates):
        position = bisect_left(tails, j)
        previous.append(tail_indices[position-1] if position else -1)
        if position == len(tails):
            tails.append(j)
            tail_indices.append(index)
        else:
            tails[position], tail_indices[position] = j, index
    result = []
    index = tail_indices[-1] if tail_indices else -1
    while index != -1:
        result.append(candidates[index])
        index = previous[index]
    return list(reversed(result))


def _joined_counts(blocks, end, target):
    joined = ''
    for index in range(end-1, -1, -1):
        if blocks[index].kind != 'text' or (index > 0 and blocks[index].paragraph_start):
            break
        joined = blocks[index].text + (' ' + joined if joined else '')
        if not target.endswith(joined):
            break
        if end-index > 1 and joined == target:
            yield end-index
            break


def _align_blocks(left, right):
    """Anchor unique unchanged blocks, then align intervening content in order."""
    a, b = [x.text for x in left], [x.text for x in right]
    counts_a, counts_b = Counter(a), Counter(b)
    unique = {s for s in a if counts_a[s] == counts_b[s] == 1}
    # Repeated short answers cannot become anchors independently of questions.
    aa = [(i, s) for i, s in enumerate(a) if s in unique]
    bb = [(j, s) for j, s in enumerate(b) if s in unique]
    matcher = SequenceMatcher(None, [s for _, s in aa], [s for _, s in bb], autojunk=False)
    anchors = [(aa[match.a+k][0], bb[match.b+k][0])
               for match in matcher.get_matching_blocks() for k in range(match.size)]
    ops = []
    i = j = 0
    for ai, bj in anchors + [(len(a), len(b))]:
        ops.extend(_align_gap(left[i:ai], right[j:bj], i, j))
        if ai < len(a):
            ops.append(('equal', ai, ai+1, bj, bj+1))
        i, j = ai+1, bj+1
    return ops


def _units(blocks):
    """Use questions as the context for their answers, including short Yes/No."""
    units = []
    for index, block in enumerate(blocks):
        if (units and units[-1].kind == 'question'
                and block.kind in ('answer', 'text')):
            units[-1].source_end = index + 1
        else:
            units.append(Block(block.text, block.kind, index, index+1))
    return units


def align_blocks(left, right):
    """Align questions with their answer context, then expose individual edits."""
    if equivalent_content(left, right):
        return [('equal', 0, len(left), 0, len(right))]
    deletion = _subsequence_edits(left, right)
    if deletion is not None:
        return deletion
    insertion = _subsequence_edits(right, left)
    if insertion is not None:
        return [('insert' if tag == 'delete' else tag, j, stop, i, end)
                for tag, i, end, j, stop in insertion]
    a, b = _units(left), _units(right)
    ops = []
    for tag, i, end, j, stop in _align_blocks(a, b):
        i1 = a[i].source_start if i < len(a) else len(left)
        i2 = a[end-1].source_end if end > i else i1
        j1 = b[j].source_start if j < len(b) else len(right)
        j2 = b[stop-1].source_end if stop > j else j1
        if tag in ('insert', 'delete'):
            ops.append((tag, i1, i2, j1, j2))
        elif (end-i == stop-j == 1 and a[i].kind == b[j].kind == 'question'):
            if equivalent_content(left[i1:i2], right[j1:j2]):
                ops.append(('equal', i1, i2, j1, j2))
            else:
                ops.append(('equal' if left[i1].text == right[j1].text else 'replace',
                            i1, i1+1, j1, j1+1))
                ops.extend(_align_gap(left[i1+1:i2], right[j1+1:j2], i1+1, j1+1))
        else:
            ops.extend(_align_gap(left[i1:i2], right[j1:j2], i1, j1))
    return _refine_regions(left, right, ops)


def word_spans(left, right):
    """Changed character spans, retaining punctuation and original text offsets."""
    a, b = list(_tokens.finditer(left)), list(_tokens.finditer(right))
    matcher = SequenceMatcher(None, [m.group() for m in a], [m.group() for m in b], autojunk=False)
    spans_a, spans_b = [], []
    for tag, i, end, j, stop in matcher.get_opcodes():
        if tag != 'equal':
            if i < end:
                spans_a.append((a[i].start(), a[end-1].end()))
            if j < stop:
                spans_b.append((b[j].start(), b[stop-1].end()))
    return spans_a, spans_b


def equivalent_content(left, right):
    def signature(blocks):
        return ' '.join(('\x00 ' if b.paragraph_start else '') + b.text for b in blocks)
    return bool(left and right) and signature(left) == signature(right)


def _refine_regions(left, right, ops):
    """Recover surviving blocks across deleted/inserted question boundaries.

    Only refine pure subsequence edits; ambiguous replacements retain the
    question-context alignment rather than anchoring on repeated short answers.
    """
    result, index = [], 0
    while index < len(ops):
        if ops[index][0] == 'equal':
            result.append(ops[index]); index += 1; continue
        stop = index + 1
        while stop < len(ops) and ops[stop][0] != 'equal':
            stop += 1
        group = ops[index:stop]
        i, end, j, finish = group[0][1], group[-1][2], group[0][3], group[-1][4]
        refined = _align_gap(left[i:end], right[j:finish], i, j)
        tags = {op[0] for op in refined}
        if 'equal' in tags and (tags <= {'equal', 'delete'} or tags <= {'equal', 'insert'}):
            result.extend(refined)
        else:
            result.extend(group)
        index = stop
    return result


def _subsequence_edits(longer, shorter):
    """Linear pure-deletion path, before Q/A grouping can move answers."""
    if len(longer) <= len(shorter):
        return None
    result, j = [], 0
    for i, block in enumerate(longer):
        if (j < len(shorter) and block.text == shorter[j].text
                and block.kind == shorter[j].kind
                and block.paragraph_start == shorter[j].paragraph_start):
            result.append(('equal', i, i+1, j, j+1))
            j += 1
        else:
            result.append(('delete', i, i+1, j, j))
    return result if j == len(shorter) else None
