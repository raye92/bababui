"""Tabs in ordinary transcript text use the same native record as the CAT Tab key."""
import pytest

from app.src import documents
from app.src.casecat.codec import records, u32
from app.tests.test_native_casecat import zip_bytes
from app.tests.test_native_structure import container_files


def _document(tmp_path, words):
    source = tmp_path / 'source.zip'
    source.write_bytes(zip_bytes(container_files(words)))
    return documents.import_casecat(source)


def _native_tabs(job):
    start = u32(job.native_bytes, 532)
    return sum(raw == b'\x09' for _, raw in records(job.native_bytes, start, start + u32(job.native_bytes, 536)))


def test_existing_body_tabs_are_editable_and_deletable(tmp_path):
    doc = _document(tmp_path, ('Left\t', '\tRight.'))
    assert doc.original == 'Left\t\tRight.'
    edited = doc.native.original.replace(4, 5, '')
    doc.set_text('original', edited.text, revision=edited)
    target = tmp_path / 'reviewed.zip'
    doc.export_casecat(target, corrected_audio=False)
    restored = documents.import_casecat(target).native.job
    assert restored.text == 'Left\tRight.'
    assert _native_tabs(restored) == 1
    assert restored.notes_bytes == doc.native.job.notes_bytes
    assert restored.stroke_clocks == doc.native.job.stroke_clocks


@pytest.mark.parametrize(('index', 'tabs'), [(0, '\t'), (5, '\t\t'), (11, '\t')])
def test_inserted_body_tabs_round_trip_as_native_tabs(tmp_path, index, tabs):
    doc = _document(tmp_path, ('Left.', 'Right.'))
    edited = doc.native.original.replace(index, index, tabs)
    doc.set_text('original', edited.text, revision=edited)
    target = tmp_path / 'reviewed.zip'
    doc.export_casecat(target, corrected_audio=False)
    restored = documents.import_casecat(target).native.job
    assert restored.text == edited.text
    assert _native_tabs(restored) == len(tabs)
    assert restored.notes_bytes == doc.native.job.notes_bytes
    assert restored.stroke_clocks == doc.native.job.stroke_clocks
