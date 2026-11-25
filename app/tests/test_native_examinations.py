"""Examination paragraphs in review and in the actual CaseCAT transcript stream."""
from pathlib import Path

import pytest

from app.src import documents
from app.src.casecat import codec
from app.src.casecat.archive import inspect_archive
from app.src.casecat.presentation import presentation
from app.src.notice_review import begin_document_review
from app.src.review_model import build_review
from app.src.suggestions import resolve_all
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import FIELD, ORPHAN, field_files, native_stream


def deposition(words):
    layout = (Path(__file__).parents[1] / 'assets' / 'notice_cover_layout.bin').read_bytes()
    files = field_files(words=words, layout=layout)
    del files['jobs/example.wav']
    return documents.import_casecat(inspect_archive(zip_bytes(files)))


@pytest.mark.parametrize('heading, gap', [('EXAMINATION', '\n'), ('FURTHER EXAMINATION', '\n\n')])
def test_review_exports_exam_with_one_blank_line_and_linked_byline(tmp_path, heading, gap):
    colloquy = b'\x16\x04\x00'
    doc = deposition((b'First. ', b'Back on the record.' + colloquy + b'WITNESS:  Fine.'
                      + colloquy + FIELD + b': ', b'Next question.'))
    proposal = f'First. Back on the record.\n{heading}{gap}BY MS. OLD:\n     Q    Next question?'
    expected = f'First. Back on the record.\n{heading}\n\nBY MS. OLD:\n     Q    Next question?'
    state = doc.native
    begin_document_review(state, proposal)

    assert state.incoming.text == expected
    _, styles, _ = presentation(state.job.with_revision(state.incoming), state.bundle)
    assert styles[expected.index(heading)].alignment == 2
    assert styles[expected.index('BY ')].name == 'Byline Paragraph Style'
    assert styles[expected.index('BY ')].first == styles[expected.index('BY ')].left
    review = build_review(state.original, state.incoming)
    state.original, state.incoming = resolve_all(state.original, state.incoming, review.ranges, True)
    target = tmp_path / 'reviewed.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target).native.job

    assert restored.text == expected
    stream = native_stream(restored)
    assert [raw[1] for _, raw in codec.records(stream, 0, len(stream)) if raw[0] == 0x16] == [7, 255, 5, 2]
    assert b'\x16\x05\x00' + ORPHAN + b'BY ' + FIELD in stream
    assert restored.stroke_clocks == state.job.stroke_clocks
    assert restored.notes_bytes == state.job.notes_bytes


def test_resumed_examination_uses_flush_byline_without_adding_a_heading_or_blank(tmp_path):
    doc = deposition((b'\x16\x04\x00MR. COUNSEL:  Go ahead.',))
    proposed = doc.original + '\nBY SPEAKER 1:\n     Q    What happened?'
    state = doc.native
    begin_document_review(state, proposed)
    assert state.incoming.text == proposed
    loc, = state.review['locations']
    assert proposed[loc['start']:loc['end']] == 'SPEAKER 1'
    state.original = state.incoming
    target = tmp_path / 'resumed.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target).native.job
    assert restored.text == proposed
    assert b'\x16\x05\x00' + ORPHAN + b'BY SPEAKER 1:' in native_stream(restored)


def test_heading_split_across_strokes_exports_as_one_centered_paragraph(tmp_path):
    doc = deposition((b'\x16\x01\x00EXAM', b'INATIONS', b'\x16\x02\x00Next?'))
    state = doc.native
    state.original = state.original.replace(11, 12, '')
    target = tmp_path / 'heading.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target).native.job
    assert restored.text == 'EXAMINATION\n     Q    Next?'
    assert [s.content for s in restored.baseline.spans] == ['EXAM', 'INATION', '\n     Q    Next?']
    assert b'\x16\x07\x00EXAM' in native_stream(restored)


def test_edit_elsewhere_preserves_imported_custom_paragraphs(tmp_path):
    doc = deposition((b'\x16\x0c\x00EXAMINATION', b'\x16\x0b\x00BY COUNSEL:', b'\x16\x03\x00Yes.'))
    state = doc.native
    state.original = state.original.revise(doc.original.replace('Yes.', 'Certainly.'))
    target = tmp_path / 'custom.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target).native.job
    stream = native_stream(restored)
    assert [raw[1] for _, raw in codec.records(stream, 0, len(stream)) if raw[0] == 0x16] == [12, 11, 3]


def test_generated_heading_uses_layout_even_if_replaced_paragraph_was_aligned_left(tmp_path):
    left_align = bytes.fromhex('1503030000000c0000')
    doc = deposition((b'\x16\x01\x00' + left_align + b'EXAMINATIONS', b'\x16\x02\x00Next?'))
    state = doc.native
    state.original = state.original.replace(11, 12, '')
    target = tmp_path / 'aligned.zip'
    doc.export_casecat(target)
    restored = documents.import_casecat(target).native
    _, styles, _ = presentation(restored.job, restored.bundle)
    assert styles[0].name == 'Centered Paragraph Style'
    assert styles[0].alignment == 2
    assert left_align not in native_stream(restored.job)


@pytest.mark.parametrize('style', [5, 7], ids=['byline', 'heading'])
def test_export_rejects_wrong_native_style_even_if_text_is_identical(tmp_path, monkeypatch, style):
    doc = deposition((b'Before.',))
    state = doc.native
    begin_document_review(state, 'Before.\nEXAMINATION\n\nBY COUNSEL:\n     Q    Next?')
    state.original = state.incoming
    serialize = codec.serialize_native

    def wrong_style(job, bundle):
        native = serialize(job, bundle)
        start, size = codec.u32(native, 532), codec.u32(native, 536)
        for offset, raw in codec.records(native, start, start + size):
            if raw == bytes((0x16, style, 0)):
                return native[:offset + 1] + b'\xff' + native[offset + 2:]
        return native

    monkeypatch.setattr(codec, 'serialize_native', wrong_style)
    target = tmp_path / 'checked.zip'
    target.write_bytes(b'previous export')
    with pytest.raises(ValueError, match='paragraph'):
        doc.export_casecat(target, overwrite=True)
    assert target.read_bytes() == b'previous export'
