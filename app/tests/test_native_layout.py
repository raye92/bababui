"""Synthetic embedded layouts with no reporter material."""
import struct

import pytest

from app.src.casecat import layout


def layout_bytes(first=2160, *, name='Byline', lines=25):
    header = bytearray(1024)
    struct.pack_into('<I', header, 4, 1)
    struct.pack_into('<I', header, 12, 1)
    struct.pack_into('<5H', header, 42, 12240, 15840, 1440, 14400, lines)
    paragraph = bytearray(512)
    paragraph[:len(name)] = name.encode()
    struct.pack_into('<H', paragraph, 28, 2)
    struct.pack_into('<i', paragraph, 32, -240)
    paragraph[60:71] = b'Courier New'
    struct.pack_into('<5H', paragraph, 170, 2160, 10368, first, 2160, 255)
    footer = bytearray(68)
    struct.pack_into('<H', footer, 28, 6)
    return bytes(header + paragraph + footer + b'Footer')


def test_multiple_embedded_layouts_use_their_record_counts():
    assert hasattr(layout, 'read_layouts'), 'Embedded native layout reader is missing.'
    native = bytearray(1024)
    payload = layout_bytes() + layout_bytes(2880, lines=28)
    struct.pack_into('<II', native, 540, 1024, len(payload))
    struct.pack_into('<I', native, 624, 2)
    native += payload
    values = layout.read_layouts(native)
    assert len(values) == 2
    assert values[0].lines_per_page == 25
    assert values[1].lines_per_page == 28
    assert values[0].paragraphs[0].first == 2160
    assert values[1].paragraphs[0].first == 2880
    assert values[0].paragraphs[0].font_family == 'Courier New'
    assert values[0].paragraphs[0].font_twips == 240
    assert values[0].raw == layout_bytes()


def test_layout_truncation_is_reported_before_presentation():
    assert hasattr(layout, 'read_layouts'), 'Embedded native layout reader is missing.'
    native = bytearray(1024)
    payload = layout_bytes()[:-1]
    struct.pack_into('<II', native, 540, 1024, len(payload))
    struct.pack_into('<I', native, 624, 1)
    native += payload
    with pytest.raises(ValueError, match='layout'):
        layout.read_layouts(native)


def test_inline_first_indent_delta_uses_native_twips():
    assert hasattr(layout, 'read_deltas'), 'Native paragraph delta reader is missing.'
    assert list(layout.read_deltas(b'\x0a\x40\x0b')) == [(10, b'\x40\x0b')]
    with pytest.raises(ValueError, match='delta'):
        list(layout.read_deltas(b'\x0a\x40'))


def test_embedded_number_positions_and_footer_font_are_read():
    payload = bytearray(layout_bytes())
    struct.pack_into('<H', payload, 54, 1626)
    footer = bytearray(68)
    struct.pack_into('<I', footer, 0, 0x200)
    struct.pack_into('<I', footer, 4, 14759)
    struct.pack_into('<I', footer, 24, 10)
    struct.pack_into('<H', footer, 28, 10)
    struct.pack_into('<I', payload, 12, 8)
    payload[1536:] = bytes(68 * 7) + footer + bytes.fromhex('150704000000bb3c5149')
    native = bytearray(1024)
    struct.pack_into('<II', native, 540, 1024, len(payload))
    struct.pack_into('<I', native, 624, 1)
    value = layout.read_layouts(native + payload)[0]
    assert value.line_number_right == 1626
    assert value.page_number_top == 14759
    assert value.page_number_font_twips == 200


def test_job_loading_validates_layout_before_document_replacement():
    from app.tests.test_native_casecat import job_files, zip_bytes
    from app.src.casecat.archive import inspect_archive
    from app.src.casecat.codec import load_job
    files = job_files()
    native = bytearray(files['jobs/example.sgngl'])
    struct.pack_into('<II', native, 540, len(native), 4)
    struct.pack_into('<I', native, 624, 1)
    files['jobs/example.sgngl'] = bytes(native) + b'BAD!'
    bundle = inspect_archive(zip_bytes(files))
    with pytest.raises(ValueError, match='layout'):
        load_job(bundle, bundle.jobs[0])
