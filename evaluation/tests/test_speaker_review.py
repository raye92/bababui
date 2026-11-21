"""Speaker attribution and turn-boundary review, and its hand-graded cases.

The stage is shared/speaker_review.py, the code the editor runs. These tests use
canned model answers, never paid requests. The four cases come from the review's
specification and check the grader itself; they are not reviewed benchmarks.
"""
import copy
import json
from pathlib import Path

import pytest

from evaluation.speaker_review_grading import AREAS, grade, load_cases, main, parse_words, report, run_case
from shared.speaker_review import (CORRECTED, FLAGGED, KEPT, PROMPT, UNREVIEWED, SpeakerReview, label_highlights,
                                   review_speakers)

CASES = Path(__file__).parents[1] / 'speaker_review_cases'

CORRECT = {
    'answer-inside-question': {'turns': [
        {'id': 1, 'speaker': 'SPEAKER 2'}, {'id': 2, 'speaker': 'SPEAKER 1'},
        {'id': 3, 'speaker': 'SPEAKER 2', 'splits': [
            {'at': 'I first examined him in March', 'speaker': 'SPEAKER 1', 'why': 'The doctor answers.'},
            {'at': 'What did you find at that', 'speaker': 'SPEAKER 2', 'why': 'The examiner follows up.'}]},
        {'id': 4, 'speaker': 'SPEAKER 1'}]},
    'witness-clarifying-question': {'turns': [
        {'id': 1, 'speaker': 'SPEAKER 3'},
        {'id': 2, 'speaker': 'SPEAKER 1', 'splits': [
            {'at': 'The lumbar MRI from June', 'speaker': 'SPEAKER 3', 'why': 'The examiner answers the question.'},
            {'at': 'Yes, I reviewed it before', 'speaker': 'SPEAKER 1', 'why': 'The witness answers.'}]},
        {'id': 3, 'speaker': 'SPEAKER 3'}, {'id': 4, 'speaker': 'SPEAKER 1'}]},
    'ambiguous-objection': {'turns': [
        {'id': 1, 'speaker': 'SPEAKER 2'}, {'id': 2, 'speaker': 'SPEAKER 3'}, {'id': 3, 'speaker': 'SPEAKER 4'},
        {'id': 4, 'speaker': 'SPEAKER 2'},
        {'id': 5, 'speaker': 'SPEAKER 3', 'evidence': 'role', 'role': 'attorney colloquy',
         'candidates': ['SPEAKER 3', 'SPEAKER 4'], 'why': 'Either nonexamining attorney.'},
        {'id': 6, 'speaker': 'SPEAKER 2'}, {'id': 7, 'speaker': 'SPEAKER 1'},
        {'id': 8, 'speaker': 'SPEAKER 2', 'splits': [
            {'at': 'Objection. Calls for speculation.', 'speaker': 'SPEAKER 2', 'evidence': 'role',
             'role': 'attorney colloquy', 'candidates': ['SPEAKER 3', 'SPEAKER 4'], 'why': 'Not the examiner.'}]},
        {'id': 9, 'speaker': 'SPEAKER 1'}]},
    'chunk-boundary-renumbering': {'turns': [
        {'id': 1, 'speaker': 'SPEAKER 2'}, {'id': 2, 'speaker': 'SPEAKER 1'}, {'id': 3, 'speaker': 'SPEAKER 2'},
        {'id': 4, 'speaker': 'SPEAKER 1'}, {'id': 5, 'speaker': 'SPEAKER 3'}, {'id': 6, 'speaker': 'SPEAKER 2'},
        {'id': 7, 'speaker': 'SPEAKER 2', 'why': 'The examiner, renumbered at the chunk join.'},
        {'id': 8, 'speaker': 'SPEAKER 1', 'why': 'The doctor, renumbered.'},
        {'id': 9, 'speaker': 'SPEAKER 2', 'why': 'The examiner, renumbered.'},
        {'id': 10, 'speaker': 'SPEAKER 1', 'why': 'The doctor, renumbered.'}]},
    'interrupted-question': {'participants': {'SPEAKER 1': 'examining attorney Mr. Smith', 'SPEAKER 2': 'witness',
                                              'SPEAKER 3': 'attorney Ms. Jones'},
                             'turns': [{'id': n, 'speaker': f'SPEAKER {2 - n % 2}'} for n in range(1, 8)]
                             + [{'id': 8, 'speaker': 'SPEAKER 3'}, {'id': 9, 'speaker': 'SPEAKER 1'},
                                {'id': 10, 'speaker': 'SPEAKER 2'}]},
}
# The proposal that put the examiner's interrupted question on the witness.
WRONG_WITNESS = copy.deepcopy(CORRECT['interrupted-question'])
WRONG_WITNESS['turns'][6] = {'id': 7, 'speaker': 'SPEAKER 2', 'why': 'The witness interrupts with a question.'}


@pytest.fixture(scope='module')
def cases():
    return {case.id: case for case in load_cases(CASES)}


def answer(data, calls=None):
    def complete(payload, prompt):
        if calls is not None:
            calls.append((json.loads(payload), prompt))
        return json.dumps(data)
    return complete


def failures(result):
    return {area: sorted(f.kind for f in result['failures'] if f.area == area) for area in AREAS}


def lines(text):
    return [line for line in text.split('\n') if line.strip()]


# The stage -------------------------------------------------------------------

def test_doctor_example_splits_before_the_answer_and_highlights_only_its_A_label(cases):
    case = cases['answer-inside-question']
    calls = []
    review = review_speakers(case.words, answer(CORRECT[case.id], calls), context=case.context)

    assert calls[0][1] == PROMPT
    sent = calls[0][0]
    assert sent['participants'] == ['SPEAKER 1', 'SPEAKER 2']
    assert sent['review'] == {'first_id': 1, 'last_id': 4}
    # Gemini's two SPEAKER 2 segments arrive as one stitched turn, with its audio time.
    assert sent['turns'][2] == {'id': 3, 'speaker': 'SPEAKER 2', 'time': '0:00:18', 'text': (
        'Doctor, when did you examine him? I first examined him in March. '
        'What did you find at that March examination?')}
    assert lines(review.text)[2:5] == ['Speaker 2: Doctor, when did you examine him?',
                                       'Speaker 1: I first examined him in March.',
                                       'Speaker 2: What did you find at that March examination?']
    split = next(s for s in review.segments if s.status == CORRECTED)
    assert case.words[split.start].text == 'I' and case.words[split.start + 1].text == 'first'
    assert (split.speaker, split.gemini, split.split) == ('SPEAKER 1', 'SPEAKER 2', True)
    assert review.summary == 'Speaker review: 1 label corrected, 1 turn split, 0 flagged.'
    assert review.warnings == ()

    spans = label_highlights(review.record(), case.expected_text)
    assert [case.expected_text[a:b] for a, b in spans] == ['A']
    line = case.expected_text[:spans[0][0]].count('\n')
    assert case.expected_text.split('\n')[line].strip() == 'A    I first examined him in March.'


def test_spoken_words_order_and_audio_times_never_change(cases):
    for case in cases.values():
        review = review_speakers(case.words, answer(CORRECT[case.id]), context=case.context)
        assert review.words == case.words
        resolved = ' '.join(line.split(': ', 1)[1] for line in lines(review.text))
        assert resolved == ' '.join(w.text for w in case.words)
        assert [(s.start, s.end) for s in review.segments] == sorted((s.start, s.end) for s in review.segments)
        assert review.segments[0].start == 0 and review.segments[-1].end == len(case.words)
        assert all(a.end == b.start for a, b in zip(review.segments, review.segments[1:]))
        for segment in review.segments:
            assert segment.time == case.words[segment.start].start


def test_role_only_evidence_keeps_the_label_and_flags_the_turn_with_its_time(cases):
    case = cases['ambiguous-objection']
    review = review_speakers(case.words, answer(CORRECT[case.id]))
    flagged = [s for s in review.segments if s.status == FLAGGED]
    assert [(s.speaker, s.gemini, s.split, s.candidates) for s in flagged] == [
        ('SPEAKER 3', 'SPEAKER 3', False, ('SPEAKER 3', 'SPEAKER 4')),
        ('SPEAKER 2', 'SPEAKER 2', True, ('SPEAKER 3', 'SPEAKER 4'))]
    assert 'Speaker 2: What is that opinion based on?' in lines(review.text)
    assert 'Speaker 2 [unconfirmed]: Objection. Calls for speculation.' in lines(review.text)
    assert review.warnings[0] == ('Speaker review at 0:00:19: “Objection. Foundation.” could be SPEAKER 3 or '
                                  'SPEAKER 4 (attorney colloquy). Kept Speaker 3 for now; check the audio.')
    assert review.warnings[1].startswith('Speaker review at 0:00:29: “Objection. Calls for speculation.”')
    assert [f['time'] for f in review.record()['flags']] == [flagged[0].time, flagged[1].time]
    assert not review.record()['corrected']


@pytest.mark.parametrize('at, problem', [('I examined him in April', 'is not in'), ('him', 'repeats in')])
def test_a_split_that_cannot_be_placed_exactly_keeps_gemini_and_flags_the_turn(cases, at, problem):
    case = cases['answer-inside-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][2]['splits'] = [{'at': at, 'speaker': 'SPEAKER 1'}]
    review = review_speakers(case.words, answer(data))
    segments = [s for s in review.segments if s.turn == 3]
    turn = case.turns[2]
    assert [(s.status, s.speaker, s.start, s.end) for s in segments] == [(FLAGGED, 'SPEAKER 2', turn.start, turn.end)]
    assert problem in segments[0].note
    assert review.warnings[0].startswith('Speaker review at 0:00:18:')


def test_a_label_that_is_not_a_participant_is_flagged(cases):
    case = cases['answer-inside-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][3] = {'id': 4, 'speaker': 'THE WITNESS'}
    review = review_speakers(case.words, answer(data))
    last = review.segments[-1]
    assert (last.status, last.speaker) == (FLAGGED, 'SPEAKER 1')
    assert 'not a participant label' in last.note


def test_a_failed_or_invalid_response_keeps_every_gemini_label(cases):
    case = cases['chunk-boundary-renumbering']
    # The formatter then receives exactly the stitched Gemini transcript.
    gemini = '\n'.join(f'{case.words[t.start].speaker}: ' + ' '.join(w.text for w in case.words[t.start:t.end])
                       for t in case.turns)

    def fails(payload, prompt):
        raise ValueError('quota')
    for complete in (lambda payload, prompt: 'not json', fails):
        review = review_speakers(case.words, complete)
        assert {s.status for s in review.segments} == {UNREVIEWED}
        assert review.text == gemini
        assert [line.split(':')[0] for line in lines(review.text)] == [
            'Speaker 2', 'Speaker 1', 'Speaker 2', 'Speaker 1', 'Speaker 3', 'Speaker 2',
            'Speaker 4', 'Speaker 5', 'Speaker 4', 'Speaker 5']
        assert review.warnings == ("Speaker review could not be completed. Gemini's speaker labels were kept there.",)
        assert 'not reviewed' in review.summary


def test_missing_turns_are_reported_and_keep_their_labels(cases):
    case = cases['chunk-boundary-renumbering']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'] = data['turns'][:6]
    review = review_speakers(case.words, answer(data))
    assert [s.status for s in review.segments][-4:] == [UNREVIEWED] * 4
    assert review.warnings == ("Speaker review did not return 4 turns. Gemini's speaker labels were kept there.",)


def test_long_transcripts_are_reviewed_in_parts_with_the_whole_transcript_as_context(cases):
    case = cases['chunk-boundary-renumbering']
    calls, entries = [], CORRECT[case.id]['turns']

    def complete(payload, prompt):
        data = json.loads(payload)
        calls.append(data)
        first, last = data['review']['first_id'], data['review']['last_id']
        return json.dumps({'turns': [e for e in entries if first <= e['id'] <= last]})
    progress = []
    review = review_speakers(case.words, complete, batch_turns=4, progress=progress.append)
    assert [c['review'] for c in calls] == [{'first_id': 1, 'last_id': 4}, {'first_id': 5, 'last_id': 8},
                                            {'first_id': 9, 'last_id': 10}]
    assert all(len(c['turns']) == 10 for c in calls)
    assert progress[-1] == 'Reviewing speakers and turn boundaries, part 3 of 3...'
    assert [s.speaker for s in review.segments][6:] == ['SPEAKER 2', 'SPEAKER 1', 'SPEAKER 2', 'SPEAKER 1']


def test_a_formatted_draft_highlights_only_corrected_labels(cases):
    case = cases['chunk-boundary-renumbering']
    review = review_speakers(case.words, answer(CORRECT[case.id]))
    draft = case.expected_text
    marked = [draft[:a].count('\n') for a, _ in label_highlights(review.record(), draft)]
    shown = draft.split('\n')
    # The four turns after the chunk join changed speaker. Q/A conversion of the
    # correctly labeled turns before it, and the colloquy, are not highlighted.
    assert [shown[n].strip()[:12] for n in marked] == ['Q    Doctor,', 'A    No, it ', 'Q    Why not', 'A    The inc']
    assert label_highlights(None, draft) == ()
    assert label_highlights(review.record(), '') == ()


def test_wording_edits_do_not_move_the_label_highlight(cases):
    case = cases['answer-inside-question']
    review = review_speakers(case.words, answer(CORRECT[case.id]))
    edited = case.expected_text.replace('I first examined him in March.', 'I first examined him in early March.')
    spans = label_highlights(review.record(), edited)
    assert [edited[a:b] for a, b in spans] == ['A']


# The grader ------------------------------------------------------------------

def test_case_words_come_from_gemini_lines_with_their_times():
    words = parse_words('[0:29:08] Speaker 4: Doctor, did that\nSpeaker 5: No.')
    assert [(w.text, w.speaker, w.start) for w in words] == [
        ('Doctor,', 'Speaker 4', 1748.0), ('did', 'Speaker 4', 1748.4), ('that', 'Speaker 4', 1748.8),
        ('No.', 'Speaker 5', 1749.2)]


@pytest.mark.parametrize('case_id', sorted(CORRECT))
def test_correct_reviews_pass_every_area(cases, case_id):
    case = cases[case_id]
    review, _ = run_case(case, answer(CORRECT[case_id]))
    for draft in (None, case.expected_text):
        result = grade(case, review, draft)
        assert result['failures'] == []
        assert all(result['counts'][area]['evaluated'] for area in AREAS)


def test_every_turn_is_evaluated_including_unchanged_turns(cases):
    case = cases['chunk-boundary-renumbering']
    result = grade(case, run_case(case, answer(CORRECT[case.id]))[0])
    assert result['counts']['status']['evaluated'] == result['counts']['splits']['evaluated'] == 10
    assert result['counts']['identity']['evaluated'] == 10


def test_keeping_gemini_label_fails_identity_split_status_and_highlight(cases):
    case = cases['answer-inside-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][2] = {'id': 3, 'speaker': 'SPEAKER 2'}
    result = grade(case, run_case(case, answer(data))[0])
    assert failures(result) == {'identity': ['missed'], 'splits': ['missed', 'missed'],
                                'status': ['missed'], 'highlights': ['missed']}


def test_a_late_split_is_graded_at_the_exact_word(cases):
    case = cases['answer-inside-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][2]['splits'][0]['at'] = 'him in March'
    result = grade(case, run_case(case, answer(data))[0])
    split = next(f for f in result['failures'] if f.area == 'splits')
    assert (split.kind, split.expected, split.actual, split.detail) == (
        'wrong_word', 'split before “I”', 'split before “him”', '3 words late')
    assert failures(result)['status'] == []


def test_giving_the_witness_question_to_the_examiner_fails(cases):
    case = cases['witness-clarifying-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][1] = {'id': 2, 'speaker': 'SPEAKER 3', 'splits': [
        {'at': 'Yes, I reviewed it before', 'speaker': 'SPEAKER 1'}]}
    result = grade(case, run_case(case, answer(data))[0])
    assert failures(result) == {'identity': ['incorrect'], 'splits': ['missed'], 'status': [],
                                'highlights': ['incorrect']}
    assert next(f for f in result['failures'] if f.area == 'identity').detail == 'relabeled a part that Gemini had right'


def test_naming_one_attorney_for_an_ambiguous_objection_fails_identity_status_and_highlight(cases):
    case = cases['ambiguous-objection']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][4] = {'id': 5, 'speaker': 'SPEAKER 4', 'why': 'A guess.'}
    result = grade(case, run_case(case, answer(data))[0])
    assert failures(result) == {'identity': ['incorrect'], 'splits': [], 'status': ['incorrect'],
                                'highlights': ['incorrect']}
    identity = next(f for f in result['failures'] if f.area == 'identity')
    assert identity.detail == 'named one participant where the exchange establishes only a role'


def test_an_unflagged_objection_fails_status_only_as_a_missed_flag(cases):
    case = cases['ambiguous-objection']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][4] = {'id': 5, 'speaker': 'SPEAKER 3'}
    result = grade(case, run_case(case, answer(data))[0])
    assert failures(result) == {'identity': [], 'splits': [], 'status': ['missed'], 'highlights': []}
    status = next(f for f in result['failures'] if f.area == 'status')
    assert (status.expected, status.actual) == ('flagged for review', 'unchanged')


def test_missing_the_chunk_renumbering_fails_each_area_separately(cases):
    case = cases['chunk-boundary-renumbering']
    data = copy.deepcopy(CORRECT[case.id])
    for entry in data['turns'][6:]:
        entry['speaker'] = 'SPEAKER 4' if entry['id'] in (7, 9) else 'SPEAKER 5'
    result = grade(case, run_case(case, answer(data))[0], case.expected_text)
    assert failures(result) == {'identity': ['missed'] * 4, 'splits': [], 'status': ['missed'] * 4,
                                'highlights': ['missed'] * 4}


def test_a_formatter_that_merges_the_split_fails_highlight_placement_only(cases):
    case = cases['answer-inside-question']
    review, _ = run_case(case, answer(CORRECT[case.id]))
    merged = case.expected_text.replace('him?\n     A    I first', 'him?  I first')
    assert failures(grade(case, review, merged)) == {'identity': [], 'splits': [], 'status': [],
                                                      'highlights': ['missed']}


def test_saved_reviews_grade_like_live_ones(cases, tmp_path, capsys):
    for case in cases.values():
        review, _ = run_case(case, answer(CORRECT[case.id]))
        (tmp_path / f'{case.id}.review.json').write_text(json.dumps(review.to_json()), encoding='utf-8')
        restored = SpeakerReview.from_json(case.words, json.loads((tmp_path / f'{case.id}.review.json').read_text()))
        assert restored.segments == review.segments and restored.text == review.text
    (tmp_path / 'answer-inside-question.draft.txt').write_text(cases['answer-inside-question'].expected_text,
                                                               encoding='utf-8')
    assert main([str(CASES), '--saved', str(tmp_path), '--json', str(tmp_path / 'results.json')]) == 0
    out = capsys.readouterr().out
    assert 'Highlight placement: 42 of 42 correct' in out
    saved = json.loads((tmp_path / 'results.json').read_text())
    assert len(saved) == 5 and all(not r['failures'] for r in saved)


def test_a_saved_review_for_another_transcript_is_refused(cases):
    one, other = cases['answer-inside-question'], cases['witness-clarifying-question']
    review, _ = run_case(one, answer(CORRECT[one.id]))
    with pytest.raises(ValueError, match='different transcript'):
        SpeakerReview.from_json(other.words, review.to_json())


def test_report_lists_each_area_and_the_clue(cases):
    case = cases['answer-inside-question']
    data = copy.deepcopy(CORRECT[case.id])
    data['turns'][2] = {'id': 3, 'speaker': 'SPEAKER 2'}
    text = report([grade(case, run_case(case, answer(data))[0])])
    assert 'Speaker identity: 5 of 6 correct' in text
    assert 'Split points: 2 of 4 correct' in text
    assert 'Review status: 3 of 4 correct' in text
    assert 'Highlight placement: 5 of 6 correct' in text
    assert 'Clue: The introductions make SPEAKER 2 the examiner' in text


# Checks on a proposed change -----------------------------------------------------

def test_a_proposal_that_speaks_to_its_own_speaker_goes_to_the_audio(cases):
    case = cases['interrupted-question']
    questions = []

    def verify(question):
        questions.append(question)
        return {'speaker': 'SPEAKER 1', 'why': 'The examiner\'s voice.'}
    review = review_speakers(case.words, answer(WRONG_WITNESS), verify=verify)
    question = questions[0]
    assert question['turn']['text'] == 'Doctor, when you reviewed the records'
    assert (question['turn']['speaker'], question['turn']['proposed']) == ('SPEAKER 1', 'SPEAKER 2')
    assert question['before']['text'] == "The prior MRI findings and the applicant's medical history."
    assert question['after']['text'] == 'Objection, let him finish the question.'
    assert question['conflicts'] == ['it speaks directly to SPEAKER 2 (“Doctor”)']
    assert question['turn']['start'] == 324.0 and question['after']['end'] is not None
    kept = review.segments[6]
    assert (kept.status, kept.speaker, kept.gemini, kept.proposed) == (KEPT, 'SPEAKER 1', 'SPEAKER 1', 'SPEAKER 2')
    assert kept.reason == 'The witness interrupts with a question.'
    assert kept.checks[-1] == "the audio check heard SPEAKER 1: The examiner's voice."
    assert review.summary.endswith('1 proposed change dropped after the audio check.')
    assert lines(review.text)[6] == 'Speaker 1: Doctor, when you reviewed the records'
    change = review.record()['changes'][0]
    assert (change['gemini'], change['proposed'], change['speaker'], change['status']) == (
        'SPEAKER 1', 'SPEAKER 2', 'SPEAKER 1', KEPT)
    result = grade(case, review)
    assert result['failures'] == []


def test_without_the_audio_a_conflicting_proposal_keeps_gemini_and_is_flagged(cases):
    case = cases['interrupted-question']
    review = review_speakers(case.words, answer(WRONG_WITNESS))
    flagged = review.segments[6]
    assert (flagged.status, flagged.speaker, flagged.proposed) == (FLAGGED, 'SPEAKER 1', 'SPEAKER 2')
    assert lines(review.text)[6] == 'Speaker 1 [unconfirmed]: Doctor, when you reviewed the records'
    assert review.warnings == ('Speaker review at 0:05:24: “Doctor, when you reviewed the records” was proposed '
                               'for SPEAKER 2 (The witness interrupts with a question), but it speaks directly to '
                               'SPEAKER 2 (“Doctor”), and the audio could not be checked. Kept Speaker 1 for now; '
                               'check the audio.',)
    # The grader keeps identity right and reports the unneeded flag.
    result = grade(case, review)
    assert failures(result) == {'identity': [], 'splits': [], 'status': ['incorrect'], 'highlights': []}


def test_an_uncertain_or_failed_audio_check_also_flags(cases):
    case = cases['interrupted-question']
    for verify in (lambda q: {'speaker': 'uncertain'}, lambda q: {'speaker': 'SPEAKER 3'},
                   lambda q: (_ for _ in ()).throw(ValueError('timeout'))):
        segment = review_speakers(case.words, answer(WRONG_WITNESS), verify=verify).segments[6]
        assert (segment.status, segment.speaker) == (FLAGGED, 'SPEAKER 1')
        assert segment.checks[-1] == 'the audio check was uncertain'


def test_the_audio_can_confirm_a_conflicting_proposal(cases):
    case = cases['interrupted-question']
    segment = review_speakers(case.words, answer(WRONG_WITNESS),
                              verify=lambda q: {'speaker': 'SPEAKER 2'}).segments[6]
    assert (segment.status, segment.speaker) == (CORRECTED, 'SPEAKER 2')


def test_the_reporters_rough_is_an_additional_check(cases):
    case = cases['answer-inside-question']
    agree = ('EXAMINATION\nBY MS. RUIZ:\n     Q    Good morning, Doctor.  My name is Ana Ruiz, and I represent the '
             "defendant.  I'll be asking you some questions today.\n     A    Good morning.  I'm Dr. Paul Chen, "
             'the orthopedic evaluator in this case.\n     Q    Doctor, when did you examine him?\n     A    I first '
             'examined him in March.\n     Q    What did you find at that March examination?\n     A    Tenderness '
             'in the lower back and a reduced range of motion.\n')
    calls = []
    review = review_speakers(case.words, answer(CORRECT[case.id]), rough=agree, verify=calls.append)
    split = next(s for s in review.segments if s.status == CORRECTED)
    assert split.checks == ("the reporter's rough agrees (THE WITNESS)",) and calls == []
    # A rough that keeps the answer inside the examiner's Q disagrees, so the audio decides.
    disagree = agree.replace('him?\n     A    I first', 'him?  I first')
    review = review_speakers(case.words, answer(CORRECT[case.id]), rough=disagree,
                             verify=lambda q: {'speaker': 'SPEAKER 1'})
    split = next(s for s in review.segments if s.proposed == 'SPEAKER 1')
    assert split.status == CORRECTED
    assert split.checks[:2] == ("the reporter's rough has MS. RUIZ, which matches Gemini",
                                'the audio check heard SPEAKER 1')


def test_an_objection_cannot_go_to_the_witness(cases):
    case = cases['ambiguous-objection']
    data = copy.deepcopy(CORRECT[case.id])
    data['participants'] = {'SPEAKER 1': 'witness Dr. Brooks'}
    data['turns'][4] = {'id': 5, 'speaker': 'SPEAKER 1', 'why': 'A guess.'}
    segment = review_speakers(case.words, answer(data)).segments[4]
    assert (segment.status, segment.speaker) == (FLAGGED, 'SPEAKER 3')
    assert 'an objection is attorney colloquy, not the witness' in segment.checks


def test_audio_checks_are_logged_for_diagnostics(cases):
    case = cases['interrupted-question']
    logged = []
    review_speakers(case.words, answer(WRONG_WITNESS), verify=lambda q: {'speaker': 'SPEAKER 1'}, log=logged.append)
    assert [entry['kind'] for entry in logged] == ['batch', 'audio']
    assert logged[1]['answer'] == {'speaker': 'SPEAKER 1'}


def test_a_continuation_paragraph_starting_with_the_word_a_is_not_an_answer():
    from shared.speaker_review import label_units
    draft = 'BY MR. SMITH:\n     Q    Did it hurt?\n     A    Yes.\n          A few days later it stopped.'
    units = label_units(draft)
    assert [(u.kind, u.examiner) for u in units] == [('q', 'MR. SMITH'), ('a', 'MR. SMITH')]
    assert units[1].tokens == ['yes', 'a', 'few', 'days', 'later', 'it', 'stopped']
