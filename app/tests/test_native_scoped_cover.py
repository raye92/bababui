"""Native tabbed notices can paginate the second caption without a hard page break."""
import pytest

from app.src.casecat import archive, codec
from app.src.casecat.caption import BODY_DIVIDER, cover_end, has_captions
from app.src.casecat.field_table import field_record, rewrite_fields
from app.src.casecat.project import NativeState
from app.src.casecat.structure import relocate
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import field_files


def scoped_bundle(page_break=b'', testimony_heading=b''):
    p = b'\x16\x08\x00'
    name = field_record('DEPONENT')
    heading = p + b"WORKERS' COMPENSATION APPEALS BOARD"
    caption = heading + p + b'Filed\tHere\x0aNext row.'
    front = (caption + p + name + page_break + caption + p + name + field_record('CREATION DATE IN WORDS') +
             b'\x0c' + p + b'A P P E A R A N C E S:' + p + b'Firm\x0aStreet' +
             b'\x0c' + p + b'I N D E X' + p + name + p + b'BY ' + field_record('EZ SPEAKER 01') +
             b'\x0c' + p + name + p + b'The declaration.' + BODY_DIVIDER)
    files = field_files(words=(p + b'Body|word.', b' Closing.'))
    # The shared fixture normally converts LF to a native paragraph on input.
    native = files['jobs/example.sgngl'].replace(b'Body|word.', b'Body\x0aword.')
    start, size = codec.u32(native, 532), codec.u32(native, 536)
    prefix = front + testimony_heading
    native = relocate(native, prefix + native[start:start + size], [(0, len(prefix), size, size)])
    files['jobs/example.sgngl'] = rewrite_fields(native, {'DEPONENT': 'A. Doe', 'CREATION DATE IN WORDS': 'May 7'})
    return archive.inspect_archive(zip_bytes(files)), start + len(front)


@pytest.mark.parametrize('page_break', [b'', b'\x0c'], ids=['natural-second-page', 'explicit-second-page'])
def test_scoped_cover_keeps_half_line_returns_and_stops_at_testimony(tmp_path, page_break):
    bundle, end = scoped_bundle(page_break)
    job = codec.load_job(bundle, bundle.jobs[0])
    assert cover_end(job.native_bytes) == end
    assert not has_captions(job.native_bytes)
    assert job.text.count('Filed\tHere\nNext row.') == 2
    assert 'Firm\nStreet' in job.text
    assert job.text.endswith('Bodyword. Closing.')

    # Edit both words previously used to recognize notices, and remove the
    # blank paragraph before testimony while keeping the tab and soft returns.
    text = job.text.replace('APPEALS BOARD', 'BOARD').replace('The declaration.\n\n', 'The oath.\n')
    revision = job.revision.revise(text)
    target = tmp_path / 'reviewed.zip'
    archive.export_zip(bundle, job.with_revision(revision), target, ai_copy=True)
    exported = archive.inspect_archive(target)
    restored = codec.load_job(exported, exported.jobs[0])
    assert restored.text == text
    assert restored.notes_bytes == job.notes_bytes
    assert restored.stroke_clocks == job.stroke_clocks
    assert not has_captions(restored.native_bytes)


@pytest.mark.parametrize('heading', [b'EXAMINATION ', b'CROSS-EXAMINATION'])
def test_scoped_cover_ends_at_a_centered_heading_after_the_blank_line_is_removed(tmp_path, heading):
    bundle, _ = scoped_bundle(testimony_heading=b'\x16\x07\x00' + heading)
    job = codec.load_job(bundle, bundle.jobs[0])
    pos = job.text.index('\n\n' + heading.decode())
    revision = job.revision.replace(pos, pos + 1, '')
    target = tmp_path / 'centered.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    exported = archive.inspect_archive(target)
    restored = NativeState.load(exported, job.key)
    assert restored.job.text == revision.text
    assert restored.original.text[restored.source_body_start:].startswith(heading.decode())


@pytest.mark.parametrize('version', [1, 2])
def test_old_scoped_project_restores_native_returns_and_retains_reviewed_wording(tmp_path, version):
    bundle, _ = scoped_bundle()
    old = codec.load_job(bundle, bundle.jobs[0], projection_version=version)
    assert 'FirmStreet' in old.text
    state = NativeState(bundle, old, old.revision, old.revision)
    before = state.original.text.index('Closing')
    state.original = state.original.replace(before, before + 7, 'Corrected')
    payload = {**state.to_dict(), 'text_projection_version': version}
    restored = NativeState.restore(bundle, payload)
    assert 'Firm\nStreet' in restored.original.text
    assert 'Filed\tHere\nNext row.' in restored.original.text
    assert restored.original.text.endswith('Bodyword. Corrected.')
    assert restored.incoming.text.endswith('Bodyword. Closing.')
    assert NativeState.restore(bundle, restored.to_dict()).original == restored.original
    target = tmp_path / 'reopened.zip'
    archive.export_zip(bundle, restored.job.with_revision(restored.original), target)
    assert codec.load_job(archive.inspect_archive(target), old.key).text == restored.original.text


def test_saved_scope_keeps_native_uppercase_on_a_date_field_after_an_unrelated_edit(tmp_path):
    bundle, _ = scoped_bundle()
    member = bundle.member(bundle.jobs[0] + '.sgngl')
    native = bundle.read(member)
    start, length = codec.u32(native, 532), codec.u32(native, 536)
    stream = native[start:start + length]
    date = field_record('CREATION DATE IN WORDS')
    pos = stream.index(date)
    edited_stream = stream[:pos] + b'\x12\x08' + date + b'\x12\x88' + stream[pos + len(date):]
    native = relocate(native, edited_stream, [(0, 0, pos, pos), (pos, pos + 2, len(date), len(date)),
                                               (pos + len(date), pos + len(date) + 4,
                                                length - pos - len(date), length - pos - len(date))])
    bundle = bundle.with_job_bytes(bundle.jobs[0], native, None)
    before = codec.load_job(bundle, bundle.jobs[0], projection_version=2)
    assert 'May 7' in before.text
    revision = before.revision.replace(len(before.text), len(before.text), ' We met on ')
    revision = revision.insert_field(len(revision.text), 'CREATION DATE IN WORDS', 'May 7')
    state = NativeState(bundle, before, revision, revision)
    restored = NativeState.restore(bundle, {**state.to_dict(), 'text_projection_version': 2})
    assert 'MAY 7' in restored.original.text
    assert restored.original.text.endswith('We met on May 7')
    assert [e.uppercase for e in restored.original.elements if e.name == 'CREATION DATE IN WORDS'] == [True, False]
    target = tmp_path / 'date.zip'
    archive.export_zip(bundle, restored.job.with_revision(restored.original), target, ai_copy=True)
    exported = archive.inspect_archive(target)
    assert codec.load_job(exported, exported.jobs[0]).text == restored.original.text


def test_saved_project_with_an_already_visible_table_keeps_its_existing_breaks():
    from app.tests.test_native_notice_cover import covered, details
    _, _, bundle, job, _, body = covered(field_files(), details())
    edited = job.with_revision(job.revision.replace(body - 2, body - 1, ''))
    bundle = bundle.with_job_bytes(job.key, codec.serialize_native(edited, bundle), None)
    modern = NativeState.load(bundle, job.key)
    assert any(field.wrap_caption for field in modern.original.elements)
    assert codec.load_job(bundle, job.key, projection_version=2).text != modern.original.text
    modern.original = modern.original.replace(len(modern.original.text), len(modern.original.text), ' Reviewed.')
    record = {**modern.to_dict(), 'text_projection_version': 2}
    restored = NativeState.restore(bundle, record)
    assert (restored.original, restored.incoming) == (modern.original, modern.incoming)


def test_a_recorded_oath_keeps_its_cover_format_and_stroke_order_on_export(tmp_path):
    bundle, boundary = scoped_bundle()
    key = bundle.jobs[0]
    native = bundle.read(bundle.member(key + '.sgngl'))
    start, length = codec.u32(native, 532), codec.u32(native, 536)
    stream = native[start:start + length]
    first_stroke, stroke = next((i, raw) for i, raw in codec.records(stream, 0, length) if raw[0] == 0x13)
    oath = stream.index(b'The declaration.')
    stream = stream[:oath] + stroke + stream[oath:first_stroke] + stream[first_stroke + len(stroke):]
    native = relocate(native, stream, [(0, 0, length, length)])
    bundle = bundle.with_job_bytes(key, native, None)
    job = codec.load_job(bundle, key)
    assert cover_end(native) == boundary + len(stroke)
    start = job.text.index('declaration')
    revision = job.revision.replace(start, start + len('declaration'), 'oath')
    target = tmp_path / 'recorded.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    restored = codec.load_job(archive.inspect_archive(target), key)
    assert restored.text == revision.text
    assert restored.stroke_clocks == job.stroke_clocks
    assert restored.notes_bytes == job.notes_bytes


def test_native_uppercase_off_after_the_divider_releases_testimony(tmp_path):
    bundle, _ = scoped_bundle()
    key = bundle.jobs[0]
    native = bundle.read(bundle.member(key + '.sgngl'))
    start, length = codec.u32(native, 532), codec.u32(native, 536)
    stream = native[start:start + length].replace(b'The declaration.', b'\x12\x08The declaration.')
    stream = stream.replace(BODY_DIVIDER, BODY_DIVIDER + b'\x12\x88')
    bundle = bundle.with_job_bytes(key, relocate(native, stream, [(0, 0, length, len(stream))]), None)
    job = codec.load_job(bundle, key)
    assert job.text.endswith('THE DECLARATION.\n\nBodyword. Closing.')
    revision = job.revision.replace(len(job.text), len(job.text), ' Reviewed.')
    target = tmp_path / 'end-caps.zip'
    archive.export_zip(bundle, job.with_revision(revision), target)
    assert codec.load_job(archive.inspect_archive(target), key).text == revision.text


def test_a_date_and_witness_fields_in_ordinary_testimony_do_not_make_a_notice():
    files = field_files()
    native = files['jobs/example.sgngl']
    start, size = codec.u32(native, 532), codec.u32(native, 536)
    prefix = (field_record('CREATION DATE IN WORDS') + b'\x0c' + field_record('DEPONENT') +
              b'\x0c' + field_record('DEPONENT') + BODY_DIVIDER)
    native = relocate(native, prefix + native[start:start + size], [(0, len(prefix), size, size)])
    assert cover_end(native) is None


def test_replacing_a_scope_without_a_divider_keeps_the_first_spoken_turn():
    from app.tests.test_native_notice_cover import details
    opening = b'\x16\x04\x00MR. COUNSEL:  Welcome.\x16\x02\x00Ready?'
    bundle, _ = scoped_bundle(testimony_heading=opening)
    key = bundle.jobs[0]
    native = bundle.read(bundle.member(key + '.sgngl'))
    start, size = codec.u32(native, 532), codec.u32(native, 536)
    stream = native[start:start + size].replace(b'\x16\x08\x00The declaration.',
                                               b'\x16\x04\x00THE REPORTER:  My declaration.')
    stream = stream.replace(BODY_DIVIDER, b'')
    bundle = bundle.with_job_bytes(key, relocate(native, stream, [(0, 0, size, len(stream))]), None)
    state = NativeState.load(bundle, key)
    testimony = state.original.text[state.source_body_start:]
    assert testimony.startswith('     MR. COUNSEL:  Welcome.\n     Q    Ready?')
    refreshed = state.with_notice('notice.pdf', b'test', details(), ('5', '16'))
    assert refreshed.original.text[refreshed.notice.body_start:] == testimony


@pytest.mark.parametrize('tabbed', [True, False], ids=['scoped-tabs', 'linked-table'])
def test_testimony_only_edit_preserves_every_native_cover_record(tmp_path, tabbed):
    from app.tests.test_native_notice_cover import covered, details
    bundle = scoped_bundle()[0] if tabbed else covered(field_files(), details())[2]
    job = codec.load_job(bundle, bundle.jobs[0])
    revision = job.revision.replace(len(job.text), len(job.text), ' Reviewed.')
    target = tmp_path / 'body-edit.zip'
    archive.export_zip(bundle, job.with_revision(revision), target, ai_copy=True)
    exported = archive.inspect_archive(target)
    restored = codec.load_job(exported, exported.jobs[0])
    def cover_stream(native):
        return native[codec.u32(native, 532):cover_end(native)]
    assert cover_stream(restored.native_bytes) == cover_stream(job.native_bytes)
    assert restored.text == revision.text
