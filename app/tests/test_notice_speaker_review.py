from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.src.casecat import archive, codec
from app.src.casecat.project import NativeState
from app.src.notice_review import begin_document_review
from app.src.suggestion_filter import override_speaker, speaker_choices, validate_review
from app.src.suggestions import resolve, suggestions
from app.tests.test_native_notice_cover import details, field_files, zip_bytes


@pytest.fixture
def covered_job():
    bundle = archive.inspect_archive(zip_bytes(field_files()))
    state = NativeState.load(bundle, bundle.jobs[0])
    return state.with_notice('notice.pdf', b'notice', details(), ())


def body_speakers(revision, start):
    return [(revision.text[e.start:e.end], e.name) for e in revision.elements
            if e.start >= start and e.name.startswith('EZ SPEAKER ')]


def test_accepting_one_reassignment_and_rejecting_the_other_keeps_native_speakers(covered_job):
    state = covered_job
    start = state.notice.body_start
    source = state.original.text[start:]
    proposal = source.replace('MS. RAY', 'MR. SMITH')
    begin_document_review(state, proposal)
    assert state.incoming.text == state.original.text[:start] + proposal
    assert body_speakers(state.incoming, start) == [('MR. SMITH', 'EZ SPEAKER 02')] * 2
    changes = suggestions(state.original, state.incoming)
    assert len(changes) == 2 and not any(change.field for change in changes)
    left, right = resolve(state.original, state.incoming, changes[0], True)
    remaining, = suggestions(left, right)
    left, right = resolve(left, right, remaining, False)
    assert left.text == right.text == state.original.text[:start] + source.replace('MS. RAY', 'MR. SMITH', 1)
    assert body_speakers(left, start) == [('MR. SMITH', 'EZ SPEAKER 02'), ('MS. RAY', 'EZ SPEAKER 01')]
    assert left.definitions == state.original.definitions
    codec.validate_job(state.bundle, state.job.with_revision(left))
    out = codec.serialize_native(state.job.with_revision(left), state.bundle)
    assert codec.load_job(state.bundle.with_job_bytes(state.job.key, out, None), state.job.key).text == left.text


def test_an_unlisted_speaker_changes_only_the_proposed_occurrence(covered_job):
    state = covered_job
    start = state.notice.body_start
    proposal = state.original.text[start:].replace('MS. RAY', 'THE INTERPRETER', 1)
    begin_document_review(state, proposal)
    assert state.incoming.text == state.original.text[:start] + proposal
    assert body_speakers(state.incoming, start) == [('MS. RAY', 'EZ SPEAKER 01')]
    assert state.incoming.definitions == state.original.definitions


def test_confirmed_speaker_fields_without_honorifics_stay_per_occurrence(covered_job):
    state = covered_job.with_notice('notice.pdf', b'notice', replace(details(), speakers=('RAY', 'LEE')), ())
    start = state.notice.body_start
    proposal = state.original.text[start:].replace('BY RAY:', 'BY LEE:')
    begin_document_review(state, proposal)
    assert state.incoming.text == state.original.text[:start] + proposal
    assert body_speakers(state.incoming, start) == [('LEE', 'EZ SPEAKER 02'), ('RAY', 'EZ SPEAKER 01')]


@pytest.mark.parametrize('assisted', (False, True))
def test_formatting_keeps_the_spoken_surname_confirmed_by_notice_and_testimony(covered_job, assisted, tmp_path):
    import json
    from app.src.jobs import ProcessingWorker, Request, RunSteps

    notice = replace(details(), plaintiff='Avery Vale', speakers=('MS. VALE', 'MR. SMITH'))
    state = covered_job.with_notice('notice.pdf', b'notice', notice, ())
    start = state.body_position(state.original)
    state.original = state.original.revise(state.original.text.replace(
        'Question?', 'Did you examine Mr. Vale before issuing the report?').replace(
        'More.', 'When did you last examine Mr. Vale?'))
    source = state.original.text[start:]
    expected = source.replace('the report', 'your report').replace('MS. VALE:', 'MS. BALE:')
    formatted = expected.replace('Mr. Vale', 'Mr. Bale')
    assert source.count('Mr. Vale') == 2

    class Processor:
        def __init__(self, config, model):
            self.model = model

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if self.model == 'formatter':
                return formatted
            return json.dumps({str(item['id']): 'abstain' for item in json.loads(text)})

    request = Request('job', str(tmp_path / 'unavailable.wav'), 'formatter', 'audio', 'Format the transcript.', {},
                      original=state.original, body_start=start, bundle=state.bundle, job=state.job,
                      vocabulary=state.notice.details.with_current_names(state.original).vocabulary(),
                      review_model='reviewer' if assisted else None,
                      steps=RunSteps(transcribe=False), raw_transcript='Speaker 1: Saved recording.')
    worker = ProcessingWorker(request, None, processor_factory=Processor)
    results, errors = [], []
    worker.succeeded.connect(lambda identifier, text, warnings, alignment: results.append(text))
    worker.reviewed.connect(lambda identifier, review, warnings, alignment: results.append(review))
    worker.failed.connect(lambda identifier, error: errors.append(error))
    worker.run()
    assert not errors
    result, = results
    if assisted:
        state.original, state.incoming, state.review = result.after_ai
    else:
        begin_document_review(state, result)
    assert state.incoming.text[start:] == expected


@pytest.mark.parametrize('confirmed', ('ROBIN MARK', 'robin mark'))
def test_notice_name_recognition_distinguishes_full_names_from_capitalized_ordinary_words(confirmed):
    from app.src.vocabulary_reconciliation import preserve_notice_spellings

    original = '     Q    Mark the numbers on this page.\n     A    Robin Mark signed that copy.'
    formatted = '     Q    Mask the numbers on this page.\n     A    Robin Mars signed that copy.'
    assert preserve_notice_spellings(original, formatted, (confirmed,)) == (
        '     Q    Mask the numbers on this page.\n     A    Robin Mark signed that copy.')


@pytest.mark.parametrize(('other_testimony', 'names'), (
    ('', ('Avery Vale', 'Jamie Bale')),
    ('\n     A    Ms. Bale sent the other report.', ('Avery Vale',)),
))
def test_a_different_known_person_remains_a_proposal(other_testimony, names):
    from app.src.vocabulary_reconciliation import preserve_notice_spellings

    original = '     Q    Did you examine Mr. Vale before the report?' + other_testimony
    formatted = original.replace('Mr. Vale', 'Mr. Bale')
    assert preserve_notice_spellings(original, formatted, names) == formatted


@pytest.mark.parametrize('assisted', (False, True))
def test_mixed_labels_keep_evidence_positions_and_allow_a_confirmed_index_speaker(covered_job, assisted, monkeypatch):
    from app.src import jobs

    state = covered_job
    start = state.notice.body_start
    head, body = state.original.text[:start], state.original.text[start:]
    proposal = body.replace('BY MS. RAY', 'BY MR. SMITH').replace('MS. RAY: More.', 'THE INTERPRETER: More.')
    proposal += '\n     Speaker 3: Another question.'
    if assisted:
        def verify_body(original, incoming, review, *_args, **_kwargs):
            assert original.text == body
            assert incoming.text == proposal
            return original, incoming, review, 'No automatic decisions.'

        monkeypatch.setattr(jobs, 'review_edits', verify_body)
        request = SimpleNamespace(original=state.original, body_start=start, bundle=state.bundle, job=state.job,
                                  disabled_rules=frozenset(),
                                  review_model='test', document_id='job', config={})
        worker = jobs.ProcessingWorker(request, None)
        result = worker._review(proposal, lambda message: None)
        state.original, state.incoming, state.review = result.after_ai
    else:
        begin_document_review(state, proposal)
    assert state.incoming.text == head + proposal
    assert body_speakers(state.incoming, start) == [('MR. SMITH', 'EZ SPEAKER 02')]
    validate_review(state.review, state.incoming.text)
    location, = state.review['locations']
    assert state.incoming.text[location['start']:location['end']] == 'Speaker 3'
    assert state.original.text[location['start']:location['end']] != 'Speaker 3'
    assert 'mr. smith' in speaker_choices(state.original)
    override_speaker(state, 'SPEAKER 3', 'MR. SMITH')
    assert state.incoming.text == head + proposal.replace('Speaker 3', 'MR. SMITH')
    assert body_speakers(state.incoming, start) == [('MR. SMITH', 'EZ SPEAKER 02')] * 2
    assert state.incoming.definitions == state.original.definitions
