"""Repeated native strokes keep distinct editorial and playback associations."""
from dataclasses import replace
import struct

import pytest

from app.src.casecat import archive, codec, project, timing
from app.tests.test_native_casecat import job_files, zip_bytes
from app.tests.test_native_structure import container_files
from app.tests.test_native_audio import audio_archive


def duplicate_files():
    files = container_files(('First ', 'nearby ', 'copy ', 'again ', 'last.'))
    native = bytearray(files['jobs/example.sgngl'])
    groups = [(offset, raw) for offset, raw in codec.records(
        native, 1024, 1024 + codec.u32(native, 536)) if raw[0] == 0x13]
    for offset, _ in groups[2:4]:
        native[offset + 3:offset + 11] = groups[0][1][3:]
    notes = bytearray(files['jobs/example.sgstn'])
    struct.pack_into('<I', notes, 516, 3)
    files['jobs/example.sgstn'] = bytes(notes[:656] + notes[672:680])
    files['jobs/example.sgngl'] = bytes(native)
    return files


def load(files):
    bundle = archive.inspect_archive(zip_bytes(files))
    return bundle, codec.load_job(bundle, bundle.jobs[0])


def steno_records(job):
    start = codec.u32(job.native_bytes, 532)
    return [raw for _, raw in codec.records(
        job.native_bytes, start, start + codec.u32(job.native_bytes, 536))
        if raw[0] == 0x13]


def test_duplicates_have_distinct_occurrences_and_inherit_preceding_clock(tmp_path):
    files = duplicate_files()
    bundle, job = load(files)
    assert job.text == 'First nearby copy again last.'
    assert [s.stroke_refs for s in job.baseline.spans] == [(0,), (1,), (2,), (3,), (4,)]
    assert job.stroke_clocks == (1000, 1010, 1010, 1010, 1040)
    assert job.native_bytes == files['jobs/example.sgngl']
    assert job.notes_bytes == files['jobs/example.sgstn']
    codec.validate_job(bundle, job)
    target = tmp_path / 'unchanged.zip'
    archive.export_zip(bundle, job, target)
    assert target.read_bytes() == bundle.data


@pytest.mark.parametrize('groups, expected', [
    (((0, 1), (0, 1), (2,)), (1000, 1010, 1010, 1010, 1020)),
    (((0,), (0, 1, 0, 2)), (1000, 1000, 1010, 1010, 1020)),
    (((0, 1, 2), (0, 0)), (1000, 1010, 1020, 1020, 1020)),
])
def test_repeated_groups_mixed_groups_and_trailing_duplicates(groups, expected):
    files = job_files(('a', 'b', 'c'))
    notes = files['jobs/example.sgstn']
    stream = b''.join(b'\x13\x02' + bytes([len(group)]) + b''.join(
        notes[640 + ref * 8:648 + ref * 8] for ref in group) + b'x' for group in groups)
    header = bytearray(files['jobs/example.sgngl'][:1024])
    struct.pack_into('<I', header, 536, len(stream))
    files['jobs/example.sgngl'] = bytes(header) + stream
    bundle, job = load(files)
    assert job.stroke_clocks == expected
    codec.validate_job(bundle, job)


def test_identical_consecutive_original_notes_are_consumed_before_duplicates():
    files = job_files(('a', 'b'))
    notes = bytearray(files['jobs/example.sgstn'])
    notes[648:656] = notes[640:648]
    native = bytearray(files['jobs/example.sgngl'])
    second = 1024 + 12
    native[second + 3:second + 11] = notes[640:648]
    files.update({'jobs/example.sgngl': bytes(native), 'jobs/example.sgstn': bytes(notes)})
    _, job = load(files)
    assert job.stroke_clocks == (1000, 1000)
    assert job.baseline.spans[1].stroke_refs == (1,)


@pytest.mark.parametrize('problem', ['unknown', 'future', 'missing', 'kind', 'empty'])
def test_duplicate_support_does_not_accept_other_steno_mismatches(problem):
    files = duplicate_files()
    native = bytearray(files['jobs/example.sgngl'])
    groups = [(o, r) for o, r in codec.records(native, 1024, 1024 + codec.u32(native, 536))
              if r[0] == 0x13]
    offset = groups[2][0]
    if problem == 'unknown':
        native[offset + 3] ^= 0x80
    elif problem == 'future':
        offset = groups[1][0]
        native[offset + 3:offset + 11] = groups[-1][1][3:]
    elif problem == 'missing':
        last = groups[-1][0]
        native[last + 3:last + 11] = groups[0][1][3:]
    elif problem == 'kind':
        native[offset + 1] = 3
    else:
        native[offset + 2] = 0
    files['jobs/example.sgngl'] = bytes(native)
    with pytest.raises(ValueError, match='steno'):
        load(files)


@pytest.mark.parametrize('word', ['First', 'nearby', 'copy', 'again', 'last'])
def test_edit_export_and_project_restore_keep_duplicates_at_their_own_locations(tmp_path, word):
    bundle, job = load(duplicate_files())
    at = job.text.index(word)
    edited = job.with_revision(job.revision.replace(at, at + len(word), 'Changed'))
    state = project.NativeState(bundle, job, edited.revision, job.baseline)
    restored, _ = project.read_project(project.project_bytes(state, {}))
    assert restored.original == edited.revision
    assert restored.incoming == job.baseline
    assert restored.job.stroke_clocks == job.stroke_clocks
    destination = tmp_path / 'edited.zip'
    archive.export_zip(bundle, edited, destination)
    exported = archive.inspect_archive(destination)
    after = codec.load_job(exported, job.key)
    assert after.text == edited.text
    assert steno_records(after) == steno_records(job)
    assert after.stroke_clocks == job.stroke_clocks
    for name in bundle.members:
        if not name.endswith('.sgngl'):
            assert exported.read(name) == bundle.read(name)
    expected = [s.content for s in job.baseline.spans]
    index = next(i for i, text in enumerate(expected) if word in text)
    expected[index] = expected[index].replace(word, 'Changed')
    assert [s.content for s in after.baseline.spans] == expected


def test_duplicate_refs_cannot_exceed_occurrence_count():
    bundle, job = load(duplicate_files())
    span = replace(job.baseline.spans[-1], stroke_refs=(5,))
    revision = replace(job.baseline, spans=(*job.baseline.spans[:-1], span))
    with pytest.raises(ValueError, match='steno reference'):
        codec.validate_job(bundle, job.with_revision(revision))


def test_duplicate_playback_uses_local_clock_through_pause_and_pcm_correction(tmp_path):
    source = audio_archive(tmp_path)
    files = {name: source.read(name) for name in source.members}
    native = bytearray(files['jobs/example.sgngl'])
    end = 1024 + codec.u32(native, 536)
    groups = [(o, r) for o, r in codec.records(native, 1024, end) if r[0] == 0x13]
    duplicate = groups[0][1] + b'copy '
    at = groups[-1][0]
    native[at:at] = duplicate
    struct.pack_into('<I', native, 536, end - 1024 + len(duplicate))
    files['jobs/example.sgngl'] = bytes(native)
    bundle, job = load(files)
    times = timing.AudioMap.from_job(bundle, job, tmp_path / 'sample.wav')
    assert times.stroke_ms[:3] == (5940, 11940, 11940)
    assert times.position_ms(job.baseline, job.text.index('copy')) == 11940
    assert times.range_at(job.baseline, 12000) == (6, 16)
    at = job.text.index('copy')
    edited = job.revision.replace(at, at + 4, 'replacement')
    assert times.position_ms(edited, at) == 11940
    # The original occurrence and the following passage keep their own timing.
    original_job = codec.load_job(source, source.jobs[0])
    original_times = timing.AudioMap.from_job(source, original_job, tmp_path / 'sample.wav')
    assert times.stroke_ms[0] == original_times.stroke_ms[0]
    assert times.stroke_ms[-1] == original_times.stroke_ms[-1]
