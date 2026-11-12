"""CaseCAT 22.1 layout and position records, independent of the native app.

Widths come from the native section writers; field meanings are checked with
controlled edits. Opaque fields remain in their original byte representation.
"""
import struct
from dataclasses import dataclass


DELTA_WIDTHS = (0, 4, 60, 6, 2, 60, 4, 1, 2, 2, 2, 2, 2, 2, 60, 4,
                1, 4, 20, 0, 0, 2, 2, 2, 2, 1, 2, 2, 1, 1, 60, 4,
                2, 1, 1, 60, 4, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1,
                1, 1, 4, 1, 0, 2)


def _u32(data, offset):
    if offset < 0 or offset + 4 > len(data):
        raise ValueError('Truncated native layout field.')
    return struct.unpack_from('<I', data, offset)[0]


def index_positions(native):
    """Yield absolute offsets of every stream position, including attachments."""
    cursor, size, count = (_u32(native, n) for n in (588, 592, 604))
    end = cursor + size
    if count > size // 32 or end > len(native):
        raise ValueError('Invalid native position index size.')
    for _ in range(count):
        if cursor + 32 > end:
            raise ValueError('Truncated native position index.')
        yield cursor, True
        attachments = native[cursor + 21]
        cursor += 32
        for _ in range(attachments):
            if cursor + 5 > end:
                raise ValueError('Truncated native position attachment.')
            kind = native[cursor + 4]
            if kind >= len(DELTA_WIDTHS):
                raise ValueError(f'Unknown native position delta kind {kind}.')
            width = 5 + DELTA_WIDTHS[kind]
            if cursor + width > end:
                raise ValueError('Truncated native format delta.')
            yield cursor, False
            cursor += width
    if cursor != end:
        raise ValueError('Unaccounted native position index bytes.')


def read_deltas(payload):
    cursor = 0
    while cursor < len(payload):
        kind = payload[cursor]
        if kind >= len(DELTA_WIDTHS):
            raise ValueError(f'Unknown native format delta kind {kind}.')
        end = cursor + 1 + DELTA_WIDTHS[kind]
        if end > len(payload):
            raise ValueError('Truncated native format delta.')
        yield kind, payload[cursor + 1:end]
        cursor = end


@dataclass(frozen=True)
class ParagraphStyle:
    name: str
    spacing: int
    font_family: str
    font_twips: int
    font_weight: int
    italic: bool
    underline: bool
    left: int
    right: int
    first: int
    continuation: int
    alignment: int
    raw: bytes


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    top: int
    bottom: int
    lines_per_page: int
    paragraphs: tuple[ParagraphStyle, ...]
    raw: bytes
    line_number_right: int = 0
    page_number_top: int | None = None
    page_number_font_twips: int = 200


def read_layouts(native):
    cursor, size, count = (_u32(native, n) for n in (540, 544, 624))
    end = cursor + size
    if not count and not size:
        return ()
    if not count or count > size // 1024 or cursor < 1024 or end > len(native):
        raise ValueError('Invalid native layout section.')
    result = []
    for _ in range(count):
        start = cursor
        if cursor + 1024 > end:
            raise ValueError('Truncated native layout header.')
        paragraph_count = _u32(native, cursor + 4)
        footer_count = _u32(native, cursor + 12)
        geometry = struct.unpack_from('<5H', native, cursor + 42)
        if not geometry[0] or not geometry[1] or not 1 <= geometry[4] <= 200:
            raise ValueError('Invalid native layout dimensions.')
        cursor += 1024
        if cursor + paragraph_count * 512 + footer_count * 68 > end:
            raise ValueError('Truncated native layout records.')
        paragraphs = []
        for _ in range(paragraph_count):
            raw = bytes(native[cursor:cursor + 512])
            font_height = abs(struct.unpack_from('<i', raw, 32)[0])
            if not 20 <= font_height <= 2880:
                raise ValueError('Unsupported native layout font size.')
            paragraphs.append(ParagraphStyle(
                raw[:28].split(b'\0')[0].decode('cp1252'),
                struct.unpack_from('<H', raw, 28)[0],
                raw[60:92].split(b'\0')[0].decode('cp1252'), font_height,
                _u32(raw, 48), bool(raw[52]), bool(raw[53]),
                *struct.unpack_from('<5H', raw, 170), raw))
            cursor += 512
        footer_start = cursor
        text_lengths = [struct.unpack_from('<H', native, cursor + i * 68 + 28)[0]
                        for i in range(footer_count)]
        cursor += footer_count * 68 + sum(text_lengths)
        if cursor > end:
            raise ValueError('Truncated native layout header/footer text.')
        page_number_top, page_number_font = None, 200
        text_start = footer_start + footer_count * 68
        for index, length in enumerate(text_lengths):
            record = footer_start + index * 68
            content = native[text_start:text_start + length]
            # Verified right-footer page-number token in CaseCAT 22.1. Other
            # footer content stays opaque and is preserved by the native writer.
            if (index == 7 and _u32(native, record) == 0x200
                    and content == bytes.fromhex('150704000000bb3c5149')):
                page_number_top = _u32(native, record + 4)
                points = _u32(native, record + 24)
                if not 1 <= points <= 144 or not 0 <= page_number_top < geometry[1]:
                    raise ValueError('Invalid native page-number geometry.')
                page_number_font = points * 20
            text_start += length
        result.append(Layout(*geometry, tuple(paragraphs), bytes(native[start:cursor]),
                             struct.unpack_from('<H', native, start + 54)[0],
                             page_number_top, page_number_font))
    if cursor != end:
        raise ValueError('Unaccounted native layout bytes.')
    return tuple(result)
