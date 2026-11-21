"""Spelling review: underline a word only when its exact spelling needs the reporter's judgment."""
import json

import pytest

from shared.spelling_review import (CONFLICT, PROMPT, SpellingReview, near, review_spelling, spelled_out,
                                    spelling_note, spelling_ranges, validate_record)

ROUGH = ("     Q    Did Dr. Meyer examine you at Pacific Orthopaedic\n"
         "Associates?\n"
         "     A    Yes.  Dr. Meyer and an orthopedic surgeon saw me.\n"
         "     Q    What did Meyer find?\n"
         "     A    A peroneal nerve injury.\n")


def model(*words):
    calls = []

    def complete(payload, prompt):
        calls.append((json.loads(payload), prompt))
        return json.dumps({'words': list(words)})
    complete.calls = calls
    return complete


def marked(record, text):
    return [text[a:b] for a, b, _ in spelling_ranges(record, text)]


def review(*words, rough=ROUGH, draft=None, sources=()):
    return review_spelling(rough, draft if draft is not None else rough, model(*words), sources=sources).record()


MEYER = {'word': 'Meyer', 'context': 'Meyer', 'category': 'person', 'alternatives': ['Meier'],
         'why': 'The surname is never spelled or confirmed.'}


def test_an_unconfirmed_surname_is_underlined_and_nothing_around_it():
    # The doctor's surname sounds like Meyer or Meier, and neither spelling is confirmed.
    record = review(MEYER)
    assert marked(record, ROUGH) == ['Meyer', 'Meyer', 'Meyer']
    # Only the surname: never the title before it or the line around it.
    assert all(ROUGH[a - 1] == ' ' and b - a == len('Meyer') for a, b, _ in spelling_ranges(record, ROUGH))
    assert record['summary'] == 'Spelling review: 1 word to check.'
    assert spelling_note(record, 0) == 'Check the spelling: Meyer or Meier? The surname is never spelled or confirmed.'


def test_the_notice_spelling_in_the_draft_stays_unmarked():
    # The notice identifies the doctor as Meier and the draft says Meier.
    draft = ROUGH.replace('Meyer', 'Meier')
    record = review({**MEYER, 'word': 'Meier', 'context': 'Meier', 'alternatives': ['Meyer']},
                    rough=draft, sources=[('person', 'Dr. John Meier')])
    assert record['terms'] == []
    assert marked(record, draft) == []


def test_a_draft_that_conflicts_with_the_notice_is_underlined_even_when_the_model_is_silent():
    # The notice says Meier, but the draft says Meyer.
    record = review(sources=[('person', 'Dr. John Meier')])
    assert marked(record, ROUGH) == ['Meyer', 'Meyer', 'Meyer']
    term = record['terms'][0]
    assert (term['word'], term['kind'], term['source'], term['alternatives']) == ('Meyer', CONFLICT, 'notice', ['Meier'])
    assert spelling_note(record, 0).startswith('Check the spelling of Meyer: the notice has Meier.')


def test_only_the_uncertain_word_of_an_organization_is_underlined():
    record = review({'word': 'Orthopaedic', 'context': 'Pacific Orthopaedic Associates', 'category': 'organization',
                     'alternatives': ['Orthopedic']})
    # The name wraps onto the next line; the generic "orthopedic surgeon" is not part of it.
    assert marked(record, ROUGH) == ['Orthopaedic']
    start = ROUGH.index('Orthopaedic')
    assert spelling_ranges(record, ROUGH) == ((start, start + len('Orthopaedic'), 0),)


def test_an_organization_conflict_needs_the_rest_of_its_name():
    draft = ROUGH.replace('Orthopaedic', 'Orthopedic') + '     A    Orthopedic care helped.\n'
    record = review(draft=draft, rough=draft, sources=[('organization', 'Pacific Orthopaedic Associates')])
    assert marked(record, draft) == ['Orthopedic']
    assert draft.index('Pacific Orthopedic') + len('Pacific ') == spelling_ranges(record, draft)[0][0]


@pytest.mark.parametrize('answer, expected', [
    ([{'word': 'peroneal', 'context': 'A peroneal nerve', 'category': 'term', 'alternatives': ['perineal'],
       'why': 'Both fit the audio and nothing says where the injury is.'}], ['peroneal']),
    ([], []),
], ids=['both fit and the context leaves it open', 'the testimony settles it'])
def test_peroneal_or_perineal(answer, expected):
    record = review(*answer)
    assert marked(record, ROUGH) == expected


@pytest.mark.parametrize('entry', [
    {'word': 'Meyer', 'context': 'Meyer', 'category': 'person', 'alternatives': []},
    {'word': 'Meyer', 'context': 'Meyer', 'category': 'person', 'alternatives': ['Meyer']},
    {'word': 'Meyer', 'context': 'Meyer', 'category': 'person', 'alternatives': ['Kowalski']},
    {'word': 'Meyer', 'context': 'Meyer', 'category': 'mood', 'alternatives': ['Meier']},
    {'word': 'Okafor', 'context': 'Dr. Okafor', 'category': 'person', 'alternatives': ['Okafur']},
    'Meyer',
], ids=['a name alone', 'the same spelling', 'not a spelling of it', 'not a checked kind of word',
        'not in the transcript', 'not an object'])
def test_a_name_or_term_alone_is_never_enough(entry):
    record = review(entry)
    assert record['terms'] == [] and marked(record, ROUGH) == []


def test_a_spelling_given_letter_by_letter_settles_or_contradicts_the_word():
    rough = ROUGH + '     Q    Spell it, please.\n     A    M-E-I-E-R.\n'
    assert spelled_out(rough) == {'meier'}
    settled = review({**MEYER, 'word': 'Meier', 'context': 'Meier', 'alternatives': ['Meyer']},
                     rough=rough.replace('Dr. Meyer', 'Dr. Meier'))
    assert settled['terms'] == []
    contradicted = review(MEYER, rough=rough)
    assert [(t['word'], t['kind'], t['source']) for t in contradicted['terms']] == [('Meyer', CONFLICT, 'testimony')]


def test_words_in_the_rough_and_in_the_ai_edits_are_both_checked():
    rough = '     Q    Did Dr. Meyer read the MRI?\n     A    Yes.\n'
    draft = '     Q    Did Dr. Myers read the MRI?\n     A    Yes, sir.\n'
    complete = model(MEYER, {'word': 'Myers', 'context': 'Dr. Myers', 'category': 'person',
                             'alternatives': ['Meyer', 'Meier']})
    record = review_spelling(rough, draft, complete).record()
    assert marked(record, rough) == ['Meyer'] and marked(record, draft) == ['Myers']
    sent, prompt = complete.calls[0]
    assert prompt == PROMPT
    assert sent['transcript'].startswith('1:      Q    Did Dr. Meyer read the MRI?')
    assert sent['edits'] and 'Myers' in sent['edits'][0]['draft'] and 'Meyer' in sent['edits'][0]['reporter']


def test_case_counts_except_for_all_caps_labels_and_sentence_starts():
    text = 'MR. ROSE:  The rose was red.\n     Q    Rose saw it.\n     A    Peroneal.  The peroneal nerve.\n'
    rose = review({'word': 'Rose', 'context': 'Rose', 'category': 'person', 'alternatives': ['Ross']}, rough=text)
    assert marked(rose, text) == ['ROSE', 'Rose']
    term = review({'word': 'peroneal', 'context': 'peroneal', 'category': 'term', 'alternatives': ['perineal']},
                  rough=text)
    assert marked(term, text) == ['Peroneal', 'peroneal']


def test_confirmed_names_are_compared_by_spelling_not_by_any_resemblance():
    assert near('Meyer', 'Meier') and near('Smyth', 'Smith') and near('Orthopedic', 'Orthopaedic')
    assert not near('Mary', 'Mark') and not near('Associate', 'Associates')
    assert not near('Garza', 'Garcia') and not near('Devin', 'Kevin') and not near('Meier', 'MEIER')


def test_the_record_round_trips_and_a_bad_record_marks_nothing():
    record = review(MEYER)
    assert SpellingReview.from_record(json.loads(json.dumps(record))).record() == record
    assert validate_record(record) is record
    for bad in ({'version': 9, 'terms': []}, {'version': 1, 'terms': [{'word': 'x'}]}, ['Meyer']):
        with pytest.raises(ValueError):
            validate_record(bad)
        assert spelling_ranges(bad, ROUGH) == ()


def test_a_long_transcript_is_checked_in_batches_and_the_results_combined():
    lines = [f'     Q    Line {i} about Dr. Meyer and the peroneal nerve.' for i in range(60)]
    rough = '\n'.join(lines)
    complete = model(MEYER, {'word': 'peroneal', 'context': 'peroneal', 'category': 'term',
                             'alternatives': ['perineal']})
    progress = []
    result = review_spelling(rough, rough, complete, batch_chars=1000, progress=progress.append)
    assert len(complete.calls) > 1 and progress[0].startswith('Checking spellings (1 of ')
    assert [t.word for t in result.terms] == ['Meyer', 'peroneal']
    first = complete.calls[0][0]['transcript'].split('\n')
    second = complete.calls[1][0]['transcript'].split('\n')
    assert first[0].startswith('1: ') and second[0].startswith(f'{len(first) + 1}: ')


def test_invalid_model_output_is_an_error():
    with pytest.raises(ValueError):
        review_spelling(ROUGH, ROUGH, lambda payload, prompt: 'Sorry, I cannot help.')
