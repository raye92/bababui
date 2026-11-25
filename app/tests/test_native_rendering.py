import re
from pathlib import Path
import struct

import pytest

from app.src.casecat.archive import export_zip, inspect_archive
from app.src.casecat.codec import load_job, records, u32
from app.src.casecat.project import NativeState
from app.tests.test_native_casecat import job_files, zip_bytes
from app.tests.test_native_structure import container_files


CONFLICT_START = b'\x11\x09\x00\x00\x00\x00'
FLAGGED_CONFLICT_START = b'\x11\x09\x02\x02\x00\x00'
CONFLICT = (CONFLICT_START + b'\x02there\x02their\x03\x0e\x20\x0b').decode('cp1252')


def native_stream(payload):
    files = job_files(words=('',))
    native = bytearray(files['jobs/example.sgngl'])
    native += payload
    struct.pack_into('<I', native, 536, len(native) - 1024)
    files['jobs/example.sgngl'] = bytes(native)
    bundle = inspect_archive(zip_bytes(files))
    return load_job(bundle, bundle.jobs[0])


def test_sentence_capitalization_preserves_internal_case_and_original_bytes():
    payload = b'\x16\x02\x00good morning.  my name is Ana.\x16\x03\x00yes, on may 21.'
    job = native_stream(payload)
    assert job.text == '     Q    Good morning.  My name is Ana.\n     A    Yes, on may 21.'
    assert job.native_bytes.endswith(payload)


@pytest.mark.parametrize('opener', [CONFLICT_START, FLAGGED_CONFLICT_START])
def test_conflict_alternatives_keep_their_visible_separators(opener):
    job = native_stream(b'he said ' + opener + b'\x02he also \x02else\x03 today.')
    assert job.text == 'He said ^ he also  ^ else today.'


def test_unframed_conflict_bytes_are_silent_and_retained_during_edits(tmp_path):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', '\x02there\x02their\x03 house.'))))
    source = load_job(bundle, bundle.jobs[0])
    assert source.text == 'He saw theretheir house.'
    start = source.text.index('house')
    revision = source.revision.replace(start, start + len('house'), 'office')
    destination = tmp_path / 'unframed.zip'

    export_zip(bundle, source.with_revision(revision), destination)

    restored = load_job(inspect_archive(destination), source.key)
    assert restored.text == 'He saw theretheir office.'
    assert b'\x02there\x02their\x03 office.' in restored.native_bytes


def test_old_saved_unframed_carets_remain_visible_in_reviewed_export(tmp_path):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', '\x02there\x02their\x03 house.'))))
    source = load_job(bundle, bundle.jobs[0], legacy_projection=True)
    revision = source.revision.revise('He saw ^ there ^ their office.')
    project = NativeState(bundle, source, revision, revision).to_dict()
    project.pop('text_projection_version')

    state = NativeState.restore(bundle, project)
    assert state.job.baseline.text == 'He saw theretheir house.'
    assert state.original.text == 'He saw ^ there ^ their office.'
    destination = tmp_path / 'legacy.zip'
    export_zip(bundle, state.job.with_revision(state.original), destination)

    restored = load_job(inspect_archive(destination), source.key)
    assert restored.text == state.original.text
    start, length = u32(restored.native_bytes, 532), u32(restored.native_bytes, 536)
    assert [raw for _, raw in records(restored.native_bytes, start, start + length)
            if raw in (b'\x02', b'\x03')] == [b'\x02', b'\x02', b'\x03']


@pytest.mark.parametrize(('position', 'expected'), [
    (7, 'He saw  ^ there ^ their house.'),
    (8, 'He saw ^  there ^ their house.'),
    (15, 'He saw ^ there  ^ their house.'),
    (16, 'He saw ^ there ^  their house.'),
])
def test_inserting_space_near_separator_preserves_native_conflict(tmp_path, position, expected):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', CONFLICT, 'house.'))))
    source = load_job(bundle, bundle.jobs[0])
    revision = source.revision.replace(position, position, ' ')
    destination = tmp_path / 'conflict.zip'

    export_zip(bundle, source.with_revision(revision), destination)

    exported = inspect_archive(destination)
    restored = load_job(exported, source.key)
    assert restored.text == expected
    start, length = u32(restored.native_bytes, 532), u32(restored.native_bytes, 536)
    markers = [CONFLICT_START, b'\x02', b'\x02', b'\x03']
    assert [raw for _, raw in records(restored.native_bytes, start, start + length)
            if raw in (*markers, b'^')] == markers
    if position == 15:
        # A later alternative supplies one leading space independently of
        # any literal space recorded before its separator.
        assert b'there \x02their' in restored.native_bytes[start:start + length]
    assert restored.notes_bytes == source.notes_bytes
    assert restored.stroke_clocks == source.stroke_clocks
    assert exported.read(restored.audio_member) == bundle.read(source.audio_member)


@pytest.mark.parametrize('position', [8, 14, 16])
def test_removing_required_conflict_spacing_rejects_export(tmp_path, position):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', CONFLICT, 'house.'))))
    source = load_job(bundle, bundle.jobs[0])
    revision = source.revision.replace(position, position + 1, '')
    destination = tmp_path / 'conflict.zip'

    with pytest.raises(ValueError, match='native conflict separator'):
        export_zip(bundle, source.with_revision(revision), destination)

    assert not destination.exists()


def test_first_translated_separator_can_follow_text_without_an_extra_space(tmp_path):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', CONFLICT, 'house.'))))
    source = load_job(bundle, bundle.jobs[0])
    revision = source.revision.replace(6, 7, '')
    destination = tmp_path / 'conflict.zip'

    export_zip(bundle, source.with_revision(revision), destination)

    restored = load_job(inspect_archive(destination), source.key)
    assert restored.text == 'He saw^ there ^ their house.'
    assert CONFLICT_START + b'\x02there\x02their\x03' in restored.native_bytes


def test_resolving_one_conflict_removes_only_its_paired_controls(tmp_path):
    bundle = inspect_archive(zip_bytes(container_files(('He saw ', CONFLICT, 'or ', CONFLICT, 'house.'))))
    source = load_job(bundle, bundle.jobs[0])
    revision = source.revision.replace(source.text.index('^'), source.text.index(' or '), 'there')
    destination = tmp_path / 'conflict.zip'

    export_zip(bundle, source.with_revision(revision), destination)

    exported = inspect_archive(destination)
    restored = load_job(exported, source.key)
    assert restored.text == 'He saw there or ^ there ^ their house.'
    start, length = u32(restored.native_bytes, 532), u32(restored.native_bytes, 536)
    markers = [CONFLICT_START, b'\x02', b'\x02', b'\x03']
    assert [raw for _, raw in records(restored.native_bytes, start, start + length)
            if raw in markers] == markers
    assert restored.notes_bytes == source.notes_bytes
    assert restored.stroke_clocks == source.stroke_clocks
    assert exported.read(restored.audio_member) == bundle.read(source.audio_member)


def test_explicit_case_controls_override_automatic_capitalization():
    job = native_stream(b'\x16\x02\x00\x12\x8egood. \x12\x8eanother. \x12\x0eagain.')
    assert job.text == '     Q    good. another. Again.'


def test_public_reference_matches_all_words_in_native_import():
    # Private validation runs locally. Synthetic tests above remain portable.
    source = Path('C:/Users/caray/Downloads/261109walth.zip')
    reference = Path('C:/Users/caray/Downloads/261109walthxd/261109walth.txt')
    if not source.exists() or not reference.exists():
        pytest.skip('Private native job and reporter export are not distributed.')
    bundle = inspect_archive(source)
    job = load_job(bundle, bundle.jobs[0])
    printed = reference.read_text(encoding='utf-8-sig')
    lines = [match[1] for line in printed.splitlines()
             if (match := re.match(r'^\s{8,}\d{1,2} {4}(.*)', line))]
    assert job.text.split() == ' '.join(lines).split()
