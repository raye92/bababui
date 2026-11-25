import json
import zipfile

import pytest

from app.src import documents
from app.src.casecat import archive, codec, project
from app.src.casecat.structure import relocate
from app.src.notice_model import NoticeDetails
from app.src.review_editing import edit_review
from app.src.review_model import build_review
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_fields import FIELD, field_files


def _write_legacy_document(tmp_path, version, state, native, data):
    if isinstance(version, str):
        source = tmp_path / 'session.json'
        project.recovery_asset(source, state)
        source.write_text(json.dumps({'version': int(version[-1]), 'active_id': data['id'],
                                      'documents': [{**data, 'native': native}]}), encoding='utf-8')
        return source, lambda: documents.load_session(source)[0][0]
    source = tmp_path / 'old.bababui'
    with zipfile.ZipFile(source, 'w') as zipped:
        zipped.writestr('source.zip', state.bundle.data)
        zipped.writestr('document.json', json.dumps({'version': version, 'native': native, 'document': data}))
        if state.notice:
            zipped.writestr('notice.zip', state.notice.data)
    return source, lambda: documents.open_document(source)


@pytest.mark.parametrize('version', [1, 2, 3, 'recovery-1', 'recovery-2'])
def test_old_projects_restore_concealed_tabs_and_keep_reviewed_text(tmp_path, version):
    files = field_files(words=(b'\x09Opening ' + FIELD + b'.', b'\x16\x08\x00Middle\x09 passage.',
                               b'\x16\x08\x00Pending wording.'))
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    original = job.baseline
    at = original.text.index('wording')
    incoming = original.replace(at, at + len('wording'), 'change')
    at = original.text.index('passage')
    model, review = edit_review(build_review(original, incoming), None, 'original', at, at, '\t')
    location = model.incoming.text.index('Middle')
    review['evidence']['speakers']['SPEAKER 1'] = {'counts': {}, 'mapped': None, 'leader': None, 'unresolved': 1}
    location = {'speaker': 'SPEAKER 1', 'start': location, 'end': location + len('Middle'), 'resolved': False}
    review['locations'].append(location)
    review['evidence']['occurrences'].append(location)
    state = project.NativeState(bundle, job, model.original, model.incoming, review)
    if version == 3:
        state.notice = project.AttachedNotice('notice.pdf', b'notice', NoticeDetails(), job.native_bytes,
                                              files['jobs/example.sgxml'], job.text.index('Pending'))
    doc = documents.Document(native=state)
    native = state.to_dict()
    native.pop('text_projection_version', None)
    if version == 1:
        for side in ('original', 'incoming'):
            for key in ('elements', 'all_caps', 'definitions'):
                native[side].pop(key)
    data = documents._document_record(doc)
    data.update(original=doc.original, incoming=doc.incoming)
    source, reopen = _write_legacy_document(tmp_path, version, state, native, data)
    before = source.read_bytes()

    restored = reopen()

    assert source.read_bytes() == before
    assert restored.native.bundle.data == bundle.data
    assert restored.original == '\tOpening MS. OLD.\nMiddle\t \tpassage.\nPending wording.'
    assert restored.incoming == '\tOpening MS. OLD.\nMiddle\t \tpassage.\nPending change.'
    field, = restored.native.original.elements
    assert (field.name, restored.original[field.start:field.end]) == ('EZ SPEAKER 01', 'MS. OLD')
    model = build_review(restored.native.original, restored.native.incoming, restored.native.review)
    assert [(restored.original[a:b], restored.incoming[c:d]) for a, b, c, d in model.ranges] == [
        ('wording', 'change')]
    for row in (*restored.native.review['locations'], *restored.native.review['evidence']['occurrences']):
        assert restored.incoming[row['start']:row['end']] == 'Middle'
    if version == 3:
        assert restored.native.notice.body_start == restored.original.index('Pending') - 1
        assert restored.native.body_position(restored.native.original) == restored.original.index('Pending')
    exported = tmp_path / 'exported.zip'
    restored.export_casecat(exported, corrected_audio=False)
    assert documents.import_casecat(exported).original == restored.original

    tab = restored.original.index('\t')
    for side in ('original', 'incoming'):
        revision = getattr(restored.native, side).replace(tab, tab + 1, '')
        restored.set_text(side, revision.text, revision=revision)
    # A deliberate modern deletion must remain deleted when the job reopens.
    restored.native.review = None
    target = tmp_path / 'modern.bababui'
    documents.save_document(restored, target)
    modern = documents.open_document(target)
    assert modern.original == restored.original
    assert modern.incoming == restored.incoming
    assert modern.native.bundle.data == bundle.data


@pytest.mark.parametrize('version', [1, 'recovery-2'])
def test_old_projects_reject_conflicting_redundant_text(tmp_path, version):
    bundle = archive.inspect_archive(zip_bytes(field_files(words=(b'Old\x09 transcript.',))))
    job = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    state = project.NativeState(bundle, job, job.baseline, job.baseline)
    native = state.to_dict()
    native.pop('text_projection_version')
    doc = documents.Document(native=state)
    data = documents._document_record(doc)
    data.update(original='Old\t transcript.', incoming=doc.incoming)
    _, reopen = _write_legacy_document(tmp_path, version, state, native, data)

    with pytest.raises(ValueError):
        reopen()


def test_tab_survives_when_an_old_edit_emptied_its_source_stroke(tmp_path):
    files = field_files(words=(b'Before ', b'Deleted\x09 wording ', b'after.'))
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    revision = job.baseline.replace(len('Before '), job.text.index('after'), '')
    legacy = project.NativeState(bundle, job, revision, revision).to_dict()
    legacy.pop('text_projection_version')

    state = project.NativeState.restore(bundle, legacy)
    target = tmp_path / 'exported.zip'
    documents.Document(native=state).export_casecat(target, corrected_audio=False)
    restored = documents.import_casecat(target)

    assert [span.content for span in restored.native.job.baseline.spans] == ['Before ', '\t', 'after.']
    assert restored.native.job.notes_bytes == job.notes_bytes


def test_tab_before_first_steno_remains_before_the_stroke(tmp_path):
    files = field_files(words=(b'Deleted ', b'Testimony.'))
    native = files['jobs/example.sgngl']
    start, size = codec.u32(native, 532), codec.u32(native, 536)
    files['jobs/example.sgngl'] = relocate(native, b'\x09' + native[start:start + size], ((0, 1, size, size),))
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    revision = job.baseline.replace(0, len('Deleted '), '')
    legacy = project.NativeState(bundle, job, revision, revision).to_dict()
    legacy.pop('text_projection_version')

    state = project.NativeState.restore(bundle, legacy)
    target = tmp_path / 'exported.zip'
    documents.Document(native=state).export_casecat(target, corrected_audio=False)
    restored = documents.import_casecat(target)

    assert [span.content for span in restored.native.job.baseline.spans] == ['\t', '', 'Testimony.']
    assert [span.stroke_refs for span in restored.native.job.baseline.spans] == [(), (0,), (1,)]


def test_restoration_does_not_duplicate_previously_visible_caption_tabs():
    from app.tests.test_native_notice_cover import covered, details
    files, _, _, _, _, _ = covered(field_files(words=(b'Question\x09here?',)), details())
    native = files['jobs/example.sgngl']
    start, size = codec.u32(native, 532), codec.u32(native, 536)
    files['jobs/example.sgngl'] = relocate(native, b'\x09' + native[start:start + size], ((0, 1, size, size),))
    bundle = archive.inspect_archive(zip_bytes(files))
    modern = codec.load_job(bundle, bundle.jobs[0])
    old = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    legacy = project.NativeState(bundle, old, old.baseline, old.baseline).to_dict()
    legacy.pop('text_projection_version')

    state = project.NativeState.restore(bundle, legacy)

    assert old.text.count('\t') > 0
    assert state.original.text.count('\t') == old.text.count('\t') + 1
    assert state.original == modern.baseline


def test_old_project_keeps_its_conflict_spacing_while_restoring_source_tabs(tmp_path):
    frame = b'\x11\x09\x00\x00\x00\x00'
    files = field_files(words=(b'Before' + frame + b'\x02first \x02second\x03\x09 after.',))
    bundle = archive.inspect_archive(zip_bytes(files))
    job = codec.load_job(bundle, bundle.jobs[0], legacy_projection=True)
    state = project.NativeState(bundle, job, job.baseline, job.baseline)
    native = state.to_dict()
    native.pop('text_projection_version')
    doc = documents.Document(native=state)
    data = documents._document_record(doc)
    data.update(original=doc.original, incoming=doc.incoming)
    _, reopen = _write_legacy_document(tmp_path, 2, state, native, data)

    restored = reopen()

    assert restored.native.job.text == 'Before^ first  ^ second\t after.'
    assert restored.original == 'Before ^ first ^ second\t after.'
    target = tmp_path / 'exported.zip'
    restored.export_casecat(target, corrected_audio=False)
    exported = documents.import_casecat(target)
    assert exported.original == restored.original
    assert exported.native.job.notes_bytes == job.notes_bytes
