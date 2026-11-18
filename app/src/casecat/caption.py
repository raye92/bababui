"""The single-row title-page table used by CATalyst caption include files."""
import re
import struct


def table_record(payload):
    return b'\x15\x04' + struct.pack('<I', len(payload)) + payload


# A native table header (version 20, one row), its two-column row, and end.
# Each cell stores the left and right edges in absolute page twips.
TABLE_START = table_record(struct.pack('<BHHB', 1, 20, 1, 0)) + table_record(b'\x03\x02\x00')
TABLE_END = table_record(b'\x02')
CAPTION_NAMES = ('PLAINTIFF', 'DEFENDANT')
BODY_DIVIDER = bytes.fromhex('1608001503030000000c0000')


def cell(left, right):
    return table_record(struct.pack('<B6H', 4, 0, left, right, 0, 0, 0))


def is_cell(raw):
    return len(raw) == 19 and raw.startswith(b'\x15\x04\x0d\x00\x00\x00\x04')


def has_captions(native):
    return TABLE_START in native[1024:2048] and b"WORKERS' COMPENSATION APPEALS BOARD" in native[1024:1280]


def cover_end(native):
    if not has_captions(native):
        return None
    spoken = native.find(b'Stating a license number', 1024, 26024)
    end = native.find(BODY_DIVIDER, spoken, spoken + 1300) if spoken >= 0 else -1
    return end + len(BODY_DIVIDER) if end >= 0 else None


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
