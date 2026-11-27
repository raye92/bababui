"""The single-row title-page table used by CATalyst caption include files."""
import re
import struct


def table_record(payload):
    return b'\x15\x04' + struct.pack('<I', len(payload)) + payload


# A native table header (version 20, one row), its two-column row, and end.
# Each cell stores the left and right edges in absolute page twips.
TABLE_HEADER = table_record(struct.pack('<BHHB', 1, 20, 1, 0))
TABLE_START = TABLE_HEADER + table_record(b'\x03\x02\x00')
TABLE_END = table_record(b'\x02')
CAPTION_NAMES = ('PLAINTIFF', 'DEFENDANT')
LEFT_JUSTIFY = bytes.fromhex('1503030000000c0000')
BODY_DIVIDER = b'\x16\x08\x00' + LEFT_JUSTIFY


def cell(left, right):
    return table_record(struct.pack('<B6H', 4, 0, left, right, 0, 0, 0))


def is_cell(raw):
    return len(raw) == 19 and raw.startswith(b'\x15\x04\x0d\x00\x00\x00\x04')


def reporter_divider_end(native, start, end):
    """Recognize the original reporter declaration in older cover layouts."""
    spoken = native.find(b'Stating a license number', start, min(end, start + 25000))
    divider = native.find(BODY_DIVIDER, spoken, min(end, spoken + 1300)) if spoken >= 0 else -1
    return divider + len(BODY_DIVIDER) if divider >= 0 else None


def _paragraph_prefix(native, start, end, *, field_names=False):
    from .codec import records
    text = bytearray()
    for _, raw in records(native, start, end):
        if raw[0] == 0x16 or raw == b'\x0c':
            break
        if raw[:2] == b'\x15\x07':
            if not field_names:
                return ''
            from .field_table import field_texts
            name = raw[10:-1].decode('cp1252')
            text.extend(field_texts(native, display=True).get(name, name).encode('cp1252'))
        elif raw[0] >= 32:
            text += raw
        elif raw in (b'\x01', b'\x09'):
            text += b' '
        if raw == b':' or len(text) > 80:
            break
    return text.decode('cp1252', errors='replace')


def _oath_end(native, start, end):
    from .codec import records
    from .elements import CENTERED_STYLE, examination_style
    reset_end = first_turn = None
    for offset, raw in records(native, start, end):
        if raw == b'\x0c' or (raw[0] == 0x13 and (reset_end is not None or first_turn is not None)):
            break
        if raw == LEFT_JUSTIFY:
            reset_end = offset + len(raw)
        elif raw == b'\x16\x04\x00' and first_turn is None:
            speaker, colon, _ = _paragraph_prefix(native, offset + len(raw), end, field_names=True).partition(':')
            if colon and not re.search(r'\bREPORTER\b', speaker, re.I):
                first_turn = offset
        elif raw in (b'\x16\x02\x00', b'\x16\x03\x00', b'\x16\x05\x00') or (
                raw == b'\x16\x07\x00' and examination_style(_paragraph_prefix(native, offset + len(raw), end)) == CENTERED_STYLE):
            # The first Q/A, byline, or centered examination can take over
            # the final blank paragraph and supersede its alignment override.
            return reset_end or first_turn or offset
    return reset_end or first_turn


def _table_cover_end(native, start, end):
    from .codec import records
    # The five-page notice has caption tables on pages one and two. Its final
    # alignment reset survives when the reviewer removes the blank paragraph.
    page = 1
    in_table = linked_caption = False
    for offset, raw in records(native, start, end):
        if raw == b'\x0c':
            if page <= 2 and not linked_caption:
                break
            page += 1
            if page == 5:
                return _oath_end(native, offset + len(raw), end)
            in_table = linked_caption = False
        elif page <= 2:
            if raw == TABLE_HEADER:
                in_table = native.startswith(TABLE_START, offset, end)
            elif raw == TABLE_END:
                in_table = False
            elif in_table and raw[:2] == b'\x15\x07' and raw[10:] in (b'PLAINTIFF\0', b'DEFENDANT\0'):
                linked_caption = True
    return None


def _tabbed_cover_end(native, start, end):
    """Follow the date, index witness and oath fields in a reporter's scoped job."""
    from .codec import records
    date = b'CREATION DATE IN WORDS\0'
    deponent = b'DEPONENT\0'
    if native.find(date, start, end) < 0 or native.find(deponent, start, end) < 0:
        return None
    page = 0
    front_witnesses, dated = 0, False
    index_page = None
    for offset, raw in records(native, start, end):
        if raw == b'\x0c':
            page += 1
        elif raw[:2] == b'\x15\x07':
            if raw[10:] == date and front_witnesses >= 2:
                # The first two sheets each identify the deponent before the
                # date field in the recital. A witness list alone is ambiguous.
                dated = True
            elif raw[10:] == deponent and not dated:
                front_witnesses += 1
            elif raw[10:] == deponent and dated and page:
                if index_page is None:
                    index_page = page
                elif page > index_page:
                    return _oath_end(native, offset + len(raw), end)
    return None


def cover_bounds(native, *, legacy=False):
    """Return the first testimony byte and whether the caption fields wrap in a table."""
    if len(native) < 1024:
        return None, False
    start, size = struct.unpack_from('<II', native, 532)
    end = start + size
    table = native.find(TABLE_START, start, end)
    board = b"WORKERS' COMPENSATION APPEALS BOARD"
    board_heading = native.find(board, start, min(end, start + 256))
    old_table = start <= table < start + 1024 and board_heading >= 0
    if legacy:
        cut = reporter_divider_end(native, start, end) if old_table else None
        return cut, cut is not None
    if table >= 0:
        cut = _table_cover_end(native, start, end)
        if cut is not None:
            return cut, True
    cut = _tabbed_cover_end(native, start, end)
    if cut is not None:
        return cut, old_table
    if old_table or (board_heading >= 0 and native.find(board, board_heading + len(board), end) >= 0):
        cut = reporter_divider_end(native, start, end)
        return cut, old_table and cut is not None
    return None, False


def cover_end(native):
    return cover_bounds(native)[0]


def has_captions(native):
    return cover_bounds(native)[1]


def caption_value(name, value):
    """Keep one field. Its native New Line symbols wrap at the tilde rule.

    Keep original spaces in the payload so the field dialog can recover the
    exact confirmed value. A slash stays on its preceding line.
    """
    if name not in CAPTION_NAMES or not value:
        return value
    parts = []
    while len(value) + 1 > 30:  # The final comma sits outside the field.
        limit = min(30, len(value) - 1)
        boundaries = [m.end() for m in re.finditer(r' +|/', value[:limit])]
        end = boundaries[-1] if boundaries else limit
        parts.append(value[:end])
        value = value[end:]
    return '\n'.join((*parts, value)) if value else '\n'.join(parts)


def caption_display(value):
    return value.replace(' \n', '\n')


def caption_offsets(name, value):
    """Map displayed line boundaries to offsets in the source field value."""
    offsets = [0]
    parts = caption_value(name, value).split('\n')
    for i, part in enumerate(parts):
        for _ in part:
            offsets.append(offsets[-1] + 1)
        if i < len(parts) - 1 and not part.endswith(' '):
            offsets.append(offsets[-1])
    return offsets
