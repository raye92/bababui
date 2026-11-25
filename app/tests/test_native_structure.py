"""Synthetic tests for structural serialization, independent of private jobs."""
import io
import struct
import zipfile

import pytest

from app.src.casecat import codec
from app.src.casecat.archive import inspect_archive
from app.tests.test_native_casecat import job_files, zip_bytes
from app.tests.test_native_layout import layout_bytes


def container_files(words=('Hello ', 'world.'), *, layout=None):
    files = job_files(words=words)
    native = bytearray(files['jobs/example.sgngl'])
    # Three position entries and four opaque extended streams deliberately
    # differ from the two-entry/nine-stream private sample.
    length = len(native) - 1024
    layout = layout_bytes() if layout is None else layout
    struct.pack_into('<II', native, 540, len(native), len(layout))
    struct.pack_into('<I', native, 624, 1)
    native += layout
    index = len(native)
    struct.pack_into('<II', native, 588, index, 96)
    struct.pack_into('<I', native, 604, 3)
    for position in (0, length // 2, length):
        native += struct.pack('<8I', position, 0, 1, 1, 0, 0, 0, 0)
    directory = len(native)
    native += b'2XSTRMZ\0' + struct.pack('<I', 4) + bytes(20)
    cursor = directory + 32 + 4 * 8
    sections = (b'one', b'', b'three', b'four')
    for section in sections:
        native += struct.pack('<II', cursor, len(section))
        cursor += len(section)
    native += b''.join(sections)
    for field, section in ((564, b'preferences'), (632, b'extended'), (556, b'end')):
        struct.pack_into('<II', native, field, len(native), len(section))
        native += section
    files['jobs/example.sgngl'] = bytes(native)
    return files


def rewritten_job(files, revision):
    bundle = inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0])
    assert hasattr(codec, 'serialize_candidate'), 'Structural serializer is not implemented.'
    result = codec.serialize_candidate(job.with_revision(revision(job.baseline)), bundle)
    files = dict(files)
    files[bundle.member(job.key + '.sgngl')] = result
    after = inspect_archive(zip_bytes(files))
    loaded = codec.load_job(after, after.jobs[0])
    return job, loaded


@pytest.mark.parametrize('text', [
    'Hello wonderful world.', 'Café résumé “quoted”.\nSecond paragraph.',
    '', '     Q    New question?\n     A    Yes.', 'Large paste. ' * 12000,
], ids=['insertion', 'cp1252', 'empty', 'paragraphs', 'large'])
def test_structural_candidate_rebuilds_positions_and_preserves_steno(text):
    before, after = rewritten_job(container_files(), lambda revision: revision.replace(0, len(revision.text), text))
    assert after.text == text
    assert before.notes_bytes == after.notes_bytes
    def strokes(job):
        start, length = codec.u32(job.native_bytes, 532), codec.u32(job.native_bytes, 536)
        return b''.join(raw[3:] for _, raw in codec.records(job.native_bytes, start, start + length) if raw[0] == 0x13)
    assert strokes(before) == strokes(after)
    assert after.native_bytes.endswith(b'preferencesextendedend')


def test_native_candidate_keeps_each_unedited_duplicate_with_its_strokes():
    before, after = rewritten_job(container_files(), lambda r: r.replace(0, 5, 'World'))
    assert after.text == 'World world.'
    assert [(s.stroke_refs, s.content) for s in after.baseline.spans] == [
        ((0,), 'World '), ((1,), 'world.')]


def test_candidate_baseline_is_byte_identical():
    before, after = rewritten_job(container_files(), lambda r: r)
    assert before.native_bytes == after.native_bytes


def test_cross_anchor_replacement_uses_the_final_affected_source_group():
    # Controlled CATalyst 22.1 edits assign the inserted passage to the final
    # affected source clock. The unchanged suffix keeps that same clock.
    _, after = rewritten_job(container_files(), lambda r: r.replace(2, 9, 'changed '))
    assert [(s.stroke_refs, s.content) for s in after.baseline.spans] == [
        ((0,), 'He'), ((1,), 'changed ld.')]


def test_replacing_an_edited_passage_exports_despite_empty_edit_fragments(tmp_path):
    from app.src.casecat.archive import export_zip
    bundle = inspect_archive(zip_bytes(container_files(('First. ', 'Second. ', 'Third.'))))
    before = codec.load_job(bundle, bundle.jobs[0])
    revision = before.baseline.replace(0, 5, 'New').replace(0, 13, 'Joined. ')
    target = tmp_path / 'edited.zip'

    export_zip(bundle, before.with_revision(revision), target)

    exported = inspect_archive(target)
    after = codec.load_job(exported, before.key)
    assert after.text == 'Joined. Third.'
    assert [(s.stroke_refs, s.content) for s in after.baseline.spans] == [
        ((0,), ''), ((1,), 'Joined. '), ((2,), 'Third.')]
    assert after.notes_bytes == before.notes_bytes
    assert after.stroke_clocks == before.stroke_clocks
    for name in bundle.members:
        if name != bundle.member(before.key + '.sgngl'):
            assert exported.read(name) == bundle.read(name)


def test_nonempty_edit_fragment_cannot_move_back_to_an_earlier_anchor():
    from dataclasses import replace
    from app.src.casecat.anchors import AnchoredSpan

    def edit(r):
        misplaced = AnchoredSpan('misplaced', (0,), (), 'Extra ')
        return replace(r, spans=(*r.spans[:2], misplaced, *r.spans[2:]))

    with pytest.raises(ValueError, match='native anchor reordering'):
        rewritten_job(container_files(('First. ', 'Second. ', 'Third.')), edit)


def test_empty_source_anchor_still_locates_unassociated_insertion():
    from dataclasses import replace
    from app.src.casecat.anchors import AnchoredSpan

    def edit(r):
        inserted = AnchoredSpan('inserted', (), (), 'New. ')
        return replace(r, spans=(r.spans[0], replace(r.spans[1], content=''), inserted, r.spans[2]))

    _, after = rewritten_job(container_files(('First. ', 'Second. ', 'Third.')), edit)
    assert [(s.stroke_refs, s.content) for s in after.baseline.spans] == [
        ((0,), 'First. '), ((1,), 'New. '), ((2,), 'Third.')]


def test_inserted_paragraph_uses_the_observed_native_enter_control():
    _, after = rewritten_job(container_files(), lambda r: r.replace(0, len(r.text), 'First.\nSecond.'))
    start, length = codec.u32(after.native_bytes, 532), codec.u32(after.native_bytes, 536)
    paragraphs = [raw for _, raw in codec.records(after.native_bytes, start, start + length) if raw[0] == 0x16]
    assert paragraphs == [b'\x16\xff\x00']


@pytest.mark.parametrize('words, remaining, replacement, expected, styles', [
    (('Intro.', '\x16\xff\x00Keep.'), '\nKeep.', '', '\nKeep.', [255, 255]),
    (('Intro.', '\x16\xff\x00Keep.'), '', '\n\n', '\n\n', [255, 255, 255]),
    (('Intro.\x16\x02\x00Question?\x16\x03\x00Yes.\x16\x04\x00THE COURT: Done.',),
     'THE COURT:', '\n\n', '\n\nTHE COURT: Done.', [255, 255, 255]),
    (('Intro.', '\x16\x02\x00Question?', '\x16\x03\x00Yes.', '\x16\x04\x00THE COURT: Done.'),
     'THE COURT:', '\n', '\nTHE COURT: Done.', [255, 255]),
], ids=['retained-break', 'only-blank-lines', 'same-stroke', 'adjacent-strokes'])
def test_export_keeps_blank_lines_at_the_start(words, remaining, replacement, expected, styles, tmp_path):
    from app.src.casecat.archive import export_zip

    bundle = inspect_archive(zip_bytes(container_files(words)))
    job = codec.load_job(bundle, bundle.jobs[0])
    end = job.text.index(remaining) if remaining else len(job.text)
    revision = job.baseline.replace(0, end, replacement)
    target = tmp_path / 'opening.zip'

    export_zip(bundle, job.with_revision(revision), target)

    restored = codec.load_job(inspect_archive(target), job.key)
    assert restored.text == expected
    assert restored.stroke_clocks == job.stroke_clocks
    assert restored.notes_bytes == job.notes_bytes
    start, length = codec.u32(restored.native_bytes, 532), codec.u32(restored.native_bytes, 536)
    assert restored.native_bytes[start:start + 3] == b'\x16\xff\x00'
    paragraphs = [int.from_bytes(raw[1:], 'little') for _, raw in
                  codec.records(restored.native_bytes, start, start + length) if raw[0] == 0x16]
    assert paragraphs == styles


@pytest.mark.parametrize('words, expected', [
    (('\x16\x08\x00Keep.',), 'Keep.'),
    (('\x16\xff\x00', '\x16\x08\x00Keep.'), '\nKeep.'),
], ids=['opening-style', 'native-enter-before-opening-style'])
def test_import_only_counts_paragraphs_after_the_opening_record(words, expected):
    bundle = inspect_archive(zip_bytes(container_files(words)))
    job = codec.load_job(bundle, bundle.jobs[0])

    assert job.text == expected


def test_position_index_attached_format_delta_is_relocated():
    files = container_files()
    raw = bytearray(files['jobs/example.sgngl'])
    index, size = codec.u32(raw, 588), codec.u32(raw, 592)
    old_length = codec.u32(raw, 536)
    # Index byte 21 counts attached position/kind/value records. Kind 10 is
    # the measured two-byte first-line indent, not another fixed index entry.
    raw[index + 21] = 1
    extra = struct.pack('<IBH', old_length, 10, 2880)
    directory = index + size
    for field in (556, 564, 632):
        struct.pack_into('<I', raw, field, codec.u32(raw, field) + len(extra))
    for field in range(directory + 32, directory + 64, 8):
        struct.pack_into('<I', raw, field, codec.u32(raw, field) + len(extra))
    struct.pack_into('<I', raw, 592, size + len(extra))
    raw[index + 32:index + 32] = extra
    files['jobs/example.sgngl'] = bytes(raw)
    _, after = rewritten_job(files, lambda r: r.replace(len(r.text), len(r.text), ' Added.'))
    updated_index = codec.u32(after.native_bytes, 588)
    assert codec.u32(after.native_bytes, updated_index + 32) == codec.u32(after.native_bytes, 536)
    assert after.native_bytes[updated_index+36:updated_index+39] == b'\x0a\x40\x0b'


@pytest.mark.parametrize('text', ['lowercase. another sentence.', 'Hello. world.', '     Q    lowercase?'])
def test_edited_wording_retains_requested_case(text):
    _, after = rewritten_job(container_files(), lambda r: r.replace(0, len(r.text), text))
    assert after.text == text


def test_joining_question_paragraph_keeps_its_label_as_literal_text():
    files = container_files()
    # Use the existing source containers and replace wording first to create
    # a native question paragraph, then edit that new source.
    _, source = rewritten_job(files, lambda r: r.replace(0, len(r.text), 'Byline:\n     Q    Question?'))
    files['jobs/example.sgngl'] = source.native_bytes.replace(b'Question?', b'question?')
    _, after = rewritten_job(files, lambda r: r.replace(7, 8, ''))
    assert after.text == 'Byline:     Q    Question?'

def test_coarse_legacy_insertion_is_bounded_by_surviving_source_anchors():
    from dataclasses import replace
    from app.src.casecat.anchors import AnchoredSpan
    def edit(r):
        broad = AnchoredSpan('legacy-insert', (0, 1, 2), (), '\n')
        return replace(r, spans=(r.spans[0], broad, *r.spans[1:]))
    _, after = rewritten_job(container_files(('First.', 'Second.', 'Third.')), edit)
    assert after.text == 'First.\nSecond.Third.'
    assert after.baseline.spans[-1].content == 'Third.'

def test_inserted_examination_heading_uses_native_centered_paragraph():
    _,after=rewritten_job(container_files(),lambda r:r._replace(0,0,'EXAMINATION\n'))
    start=codec.u32(after.native_bytes,532)
    controls=[raw for _,raw in codec.records(after.native_bytes,start,start+codec.u32(after.native_bytes,536)) if raw[0]==0x16]
    assert controls[0]==bytes.fromhex('160700')
    assert after.text=='EXAMINATION\nHello world.'

def test_heading_before_native_byline_does_not_duplicate_paragraph_boundary():
    from app.tests.test_native_fields import field_files
    _,after=rewritten_job(field_files(),lambda r:r._replace(0,0,'EXAMINATION\n'))
    assert after.text.startswith('EXAMINATION\nBY MS. OLD:\n     Q')
    start=codec.u32(after.native_bytes,532)
    assert bytes.fromhex('160700') in after.native_bytes[start:]

@pytest.mark.parametrize('prefix',['\n     Q','\n     A','\n     MS.'])
def test_blank_paragraph_before_native_label_survives(prefix):
    from app.tests.test_native_fields import field_files
    def edit(r):
        p=r.text.index(prefix)
        return r._replace(p,p,'\n')
    before,after=rewritten_job(field_files(),edit)
    assert after.text==before.text.replace(prefix,'\n'+prefix,1)

def test_accept_insertion_uses_destination_clock_not_repeated_word_source():
    from dataclasses import replace
    from app.src.casecat.anchors import AnchoredSpan
    from app.src.suggestions import suggestions,resolve
    def edit(r):
        copied=replace(r.spans[0],identity='ai-copy',content='Extra ')
        incoming=replace(r,spans=(*r.spans[:2],copied,*r.spans[2:]))
        return resolve(r,incoming,suggestions(r,incoming)[0],True)[0]
    _,after=rewritten_job(container_files(('First. ', 'Second. ', 'Third.')),edit)
    assert after.text=='First. Second. Extra Third.'
    assert after.baseline.spans[-1].content=='Extra Third.'
