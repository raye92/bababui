"""Hand-graded ASR-to-AI-draft cases for each area, graded with sample drafts."""
import json

from evaluation.draft_grading import (Case, grade, load_cases, note_area, render, report_html,
                                       restoration_spans, run, track_edits, parse_asr, parse_draft)


def kinds(result):
    return sorted({(f.area, f.category) for f in result['failures']})


# Wording -------------------------------------------------------------------

WORDING = {
    'id': 'wording',
    'witness': 'SPEAKER 2',
    'asr': """Speaker 1: Doctor, how did the injury happen?
Speaker 2: He told me he fell off a ladder at work while he was painting.
Speaker 1: How high was the latter?
Speaker 2: About eight feet. I saw him on March 3rd. No, I'm sorry, March 5th.
Speaker 1: And the pain level at that visit?
Speaker 2: He rated it a seven out of ten when he""",
    'expected': """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, how did the injury happen?
     A    He told me he fell off a ladder at work while he was painting.
     Q    How high was the ladder?
     A    About 8 feet.  I saw him on March 3.  No, I'm sorry, March 5.
     Q    And the pain level at that visit?
     A    He rated it a 7 out of 10 when he -- [REVIEW 1]

REVIEW NOTES
[REVIEW 1] The answer stops mid-sentence and the missing words cannot be established. Check the audio.""",
    'checkpoints': [
        {'area': 'wording', 'asr': 'latter', 'clue': 'The answer just before describes a fall off a ladder; "latter" is a homophone mistranscription.'},
        {'area': 'wording', 'asr': "March 3rd. No, I'm sorry, March 5th", 'clue': 'The witness corrects herself; both dates are testimony and stay.'},
        {'area': 'wording', 'asr': 'seven out of ten when he', 'clue': 'The answer stops mid-sentence and nothing later supplies the missing words.'},
    ],
}

WORDING_BAD = """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, how did the injury happen?
     A    He told me he fell off a ladder at work while he was painting. [REVIEW 1]
     Q    How high was the latter?
     A    About eight feet.  I saw him on March 5th.
     Q    And the pain level at that visit?
     A    He rated it a seven out of ten when he was walking.

REVIEW NOTES
[REVIEW 1] Check the wording of this answer."""


def test_wording_expected_draft_has_no_failures():
    case = Case(WORDING)
    result = grade(case, WORDING['expected'])
    assert result['failures'] == []
    # Every speech paragraph's wording is checked, not only the edited ones.
    assert result['counts']['wording']['evaluated'] == 6


def test_wording_failures_are_reported_by_category():
    case = Case(WORDING)
    result = grade(case, WORDING_BAD)
    by = {(f.category, f.expected, f.actual): f for f in result['failures'] if f.area == 'wording'}
    assert ('missed', 'ladder', 'latter') in by
    assert by[('missed', 'ladder', 'latter')].clue.startswith('The answer just before describes a fall')
    assert ('incorrect', "3rd No I'm sorry March", '(nothing)') in by
    invented = next(f for f in result['failures'] if f.category == 'incorrect' and 'walking' in f.actual)
    assert 'flagging' in invented.detail
    assert any(f.category == 'missed' and f.expected == 'flagged for review' for f in result['failures'])
    assert any(f.category == 'unnecessary_flag' and f.area == 'wording' for f in result['failures'])
    # A missed correction and two unwanted edits change what the highlights show.
    assert sum(f.category == 'highlight' for f in result['failures']) == 3
    assert '«latter»' in by[('missed', 'ladder', 'latter')].excerpt


def test_style_and_punctuation_changes_are_not_edits():
    _, asr = parse_asr('Speaker 1: Disc protrusion at L4 L5 on March 15th, ten percent, by email. OK.')
    draft = parse_draft('     SPEAKER 1:  Disc protrusion at L4-L5 on March 15, 10%, by e-mail.  Okay.', 'SPEAKER 2')
    edits, _ = track_edits(asr, draft.tokens)
    assert edits == []


def test_optional_verbatim_cleanup_counts_either_way():
    record = {'id': 'cleanup', 'witness': 'SPEAKER 2',
              'asr': 'Speaker 1: And did you um review the the records?\nSpeaker 2: Yes.',
              'expected': '     Q    Did you review the records?\n     A    Yes.'}
    kept = '     Q    And did you um review the the records?\n     A    Yes.'
    assert grade(Case(record), kept)['failures'] == []
    assert grade(Case(record), record['expected'])['failures'] == []
    # Removing both copies of a repeated word loses it: that is still an edit.
    lost = grade(Case(record), '     Q    Did you review records?\n     A    Yes.')['failures']
    assert [(f.area, f.category) for f in lost if f.category != 'highlight'] == [('wording', 'incorrect')]


# Speakers ------------------------------------------------------------------

SPEAKERS = {
    'id': 'speakers',
    'witness': 'SPEAKER 2',
    'asr': """Speaker 1: Did you examine his lumbar spine? Yes, I examined his lumbar spine and found tenderness at L4-L5.
Speaker 3: Objection, vague.
Speaker 1: Counsel, I'll rephrase. Doctor, what did the MRI show?
Speaker 2: It showed a disc protrusion at L4-L5.
Speaker 3: Counsel, was that the 2024 MRI?
Speaker 1: Yes, the 2024 MRI.
Speaker 3: Thank you.
Speaker 1: Doctor, what records did you review?
Speaker 2: I reviewed the records from Kaiser
Speaker 3: and the physical therapy notes from 2023.""",
    'expected': """EXAMINATION
BY SPEAKER 1:
     Q    Did you examine his lumbar spine?
     A    Yes, I examined his lumbar spine and found tenderness at L4-L5.
     SPEAKER 3:  Objection.  Vague.
     SPEAKER 1:  Counsel, I'll rephrase.
BY SPEAKER 1:
     Q    Doctor, what did the MRI show?
     A    It showed a disc protrusion at L4-L5.
     SPEAKER 3:  Counsel, was that the 2024 MRI?
     SPEAKER 1:  Yes, the 2024 MRI.
     SPEAKER 3:  Thank you. [REVIEW 1]
BY SPEAKER 1:
     Q    Doctor, what records did you review?
     A    I reviewed the records from Kaiser and the physical therapy notes from 2023.

REVIEW NOTES
[REVIEW 1] Speaker uncertain: either attorney could be thanking counsel here.""",
    'checkpoints': [
        {'area': 'speakers', 'asr': 'Yes, I examined his lumbar spine', 'clue': 'Firsthand knowledge of the examination: the doctor answers inside the attorney\'s turn.'},
        {'area': 'speakers', 'asr': 'Objection, vague', 'clue': 'Only the nonexamining attorney objects.'},
        {'area': 'speakers', 'asr': 'Thank you', 'clue': 'A courtesy after an exchange between counsel; either attorney or the witness could say it.'},
        {'area': 'speakers', 'asr': 'and the physical therapy notes from 2023', 'clue': 'The sentence continues the doctor\'s list of records he reviewed; counsel has no firsthand knowledge of it.'},
        {'area': 'paragraphs', 'asr': 'Doctor, what did the MRI show', 'clue': 'Counsel turns from the objection back to the witness; the question starts a new Q.'},
    ],
}

SPEAKERS_KEPT_GEMINI = """EXAMINATION
BY SPEAKER 1:
     Q    Did you examine his lumbar spine?  Yes, I examined his lumbar spine and found tenderness at L4-L5.
     SPEAKER 3:  Objection.  Vague.
     SPEAKER 1:  Counsel, I'll rephrase.
BY SPEAKER 1:
     Q    Doctor, what did the MRI show?
     A    It showed a disc protrusion at L4-L5.
     SPEAKER 3:  Counsel, was that the 2024 MRI?
     SPEAKER 1:  Yes, the 2024 MRI.
     SPEAKER 3:  Thank you.
BY SPEAKER 1:
     Q    Doctor, what records did you review?
     A    I reviewed the records from Kaiser
     SPEAKER 3:  and the physical therapy notes from 2023."""


def test_speaker_expected_draft_has_no_failures():
    result = grade(Case(SPEAKERS), SPEAKERS['expected'])
    assert result['failures'] == []


def test_speakers_kept_from_gemini_are_missed_corrections():
    result = grade(Case(SPEAKERS), SPEAKERS_KEPT_GEMINI)
    missed = [f for f in result['failures'] if f.category == 'missed']
    assert {f.area for f in missed} == {'speakers', 'paragraphs'}
    examined = next(f for f in missed if f.area == 'speakers' and 'examined' in f.excerpt and 'flag' not in f.expected)
    assert examined.expected == 'SPEAKER 2 (A)' and examined.actual.startswith('SPEAKER 1')
    assert examined.clue.startswith('Firsthand knowledge')
    assert any(f.expected == 'flagged for review' and f.area == 'speakers' for f in missed)
    assert any('physical therapy' in f.excerpt and f.area == 'speakers' for f in missed)
    # The two missed relabels also miss their yellow labels.
    assert sum(f.category == 'highlight' and f.area == 'speakers' for f in result['failures']) == 2


def test_relabeling_an_objection_is_an_incorrect_edit():
    draft = SPEAKERS['expected'].replace('     SPEAKER 3:  Objection.  Vague.',
                                         '     SPEAKER 2:  Objection.  Vague. [REVIEW 2]').replace(
        'REVIEW NOTES\n', 'REVIEW NOTES\n[REVIEW 2] Speaker unclear for the objection.\n')
    result = grade(Case(SPEAKERS), draft)
    assert kinds(result) == [('speakers', 'highlight'), ('speakers', 'incorrect'), ('speakers', 'unnecessary_flag')]
    wrong = next(f for f in result['failures'] if f.category == 'incorrect')
    assert wrong.detail == "relabeled a speaker that Gemini had right"
    assert wrong.clue == 'Only the nonexamining attorney objects.'


def test_right_speaker_in_the_wrong_form_is_an_incorrect_edit():
    draft = SPEAKERS['expected'].replace('     A    It showed', '     SPEAKER 2:  It showed')
    result = grade(Case(SPEAKERS), draft)
    assert kinds(result) == [('speakers', 'incorrect')]
    assert result['failures'][0].detail == 'right speaker, wrong Q/A or colloquy form'


# Paragraphs ----------------------------------------------------------------

PARAGRAPHS = {
    'id': 'paragraphs',
    'witness': 'SPEAKER 2',
    'asr': """Speaker 1: Doctor, what did the MRI show?
Speaker 2: The MRI showed a disc protrusion
Speaker 2: at L4-L5 with mild stenosis.
Speaker 1: Doctor, when you reviewed the records
Speaker 3: Objection, vague as to which records.
Speaker 1: from 2025, did you see the MRI report?
Speaker 2: Yes, I did.
Speaker 2: Turning to the shoulder, the X-rays were normal.
Speaker 1: When did you see him?
Speaker 2: In March.
Speaker 2: In June.""",
    'expected': """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, what did the MRI show?
     A    The MRI showed a disc protrusion at L4-L5 with mild stenosis.
     Q    Doctor, when you reviewed the records --
     SPEAKER 3:  Objection.  Vague as to which records.
BY SPEAKER 1:
     Q    -- from 2025, did you see the MRI report?
     A    Yes, I did.
          Turning to the shoulder, the X-rays were normal.
     Q    When did you see him?
     A    In March.
     A    In June. [REVIEW 1]

REVIEW NOTES
[REVIEW 1] Paragraph boundary: two answers in a row, so a question may be missing between them. Check the audio.""",
    'checkpoints': [
        {'area': 'paragraphs', 'asr': 'at L4-L5 with mild stenosis', 'clue': 'Gemini broke one sentence in two; the second part completes "a disc protrusion".'},
        {'area': 'paragraphs', 'asr': 'Objection, vague as to which records', 'clue': 'The objection interrupts the question; both halves keep their order around it.'},
        {'area': 'paragraphs', 'asr': 'Turning to the shoulder', 'clue': 'The witness moves to a new subject; a new paragraph is allowed.'},
        {'area': 'paragraphs', 'asr': 'In June', 'clue': 'Two answers in a row read like replies to two questions.'},
    ],
}

PARAGRAPHS_BAD = """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, what did the MRI show?
     A    The MRI showed a disc protrusion
     A    at L4-L5 with mild stenosis.
     Q    Doctor, when you reviewed the records from 2025, did you see the MRI report?
     SPEAKER 3:  Objection.  Vague as to which records.
     A    Yes, I did.  Turning to the shoulder, the X-rays were normal.
     Q    When did you see him?
     A    In March.  In June."""


def test_paragraph_expected_draft_has_no_failures():
    result = grade(Case(PARAGRAPHS), PARAGRAPHS['expected'])
    assert result['failures'] == []
    # Every boundary Gemini or the expected draft has is evaluated.
    assert result['counts']['paragraphs']['evaluated'] == 10


def test_paragraph_failures():
    result = grade(Case(PARAGRAPHS), PARAGRAPHS_BAD)
    paragraph = [f for f in result['failures'] if f.area == 'paragraphs']
    details = sorted(f.detail for f in paragraph if f.category != 'highlight')
    assert details == ['joined across a real boundary', 'joined across a real boundary',
                       'joined across a real boundary', 'kept an artificial Gemini break',
                       'missed a needed review flag', 'moved out of testimony order',
                       'moved out of testimony order']
    stenosis = next(f for f in paragraph if f.detail == 'kept an artificial Gemini break')
    assert stenosis.clue.startswith('Gemini broke one sentence')
    moved = next(f for f in paragraph if f.detail == 'moved out of testimony order')
    assert moved.clue.startswith('The objection interrupts the question')
    # Paragraph-only edits never show change highlights; only the moved words do.
    assert {f.actual for f in paragraph if f.category == 'highlight'} == {'struck-through removal', 'green background'}
    assert not any(f.area == 'wording' for f in result['failures'])


# Names, organizations and terms ----------------------------------------------

NAMES = {
    'id': 'names',
    'witness': 'SPEAKER 2',
    'context': 'Notice: applicant Shanoan Cotton; witness Natalie Broussard, D.D.S.',
    'asr': """Speaker 1: Doctor, please state your name for the record.
Speaker 2: Natalie Brousard. The last name is spelled B R O U S S A R D.
Speaker 1: I represent the district with regard to the applicant Shino and Cotton.
Speaker 1: Doctor, what did you diagnose?
Speaker 2: Suspected carpal tunnel syndrome in the left wrist. The report says right, but it was the left.
Speaker 1: Did she have dry mouth?
Speaker 2: Yes, zerostomia from the medication.
Speaker 1: Which medication?
Speaker 2: She was taking Selex at the time.""",
    'expected': """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, please state your name for the record.
     A    Natalie Broussard.  The last name is spelled B-R-O-U-S-S-A-R-D.
     Q    I represent the district with regard to the applicant, Shanoan Cotton.
          Doctor, what did you diagnose?
     A    Suspected carpal tunnel syndrome in the left wrist.  The report says right, but it was the left.
     Q    Did she have dry mouth?
     A    Yes, xerostomia from the medication.
     Q    Which medication?
     A    She was taking Selex at the time. [REVIEW 1]

REVIEW NOTES
[REVIEW 1] Medication name unclear: Celexa or Celebrex. Check the audio or the records.""",
    'terms': [{'term': 'Broussard', 'heard': ['Brousard']}, {'term': 'Shanoan Cotton', 'heard': ['Shino and Cotton']},
              'carpal tunnel syndrome', {'term': 'xerostomia', 'heard': ['zerostomia']}, 'Selex'],
    'checkpoints': [
        {'area': 'names', 'asr': 'Brousard', 'clue': 'The witness spells her last name, B-R-O-U-S-S-A-R-D, in the same answer.'},
        {'area': 'names', 'asr': 'Shino and Cotton', 'clue': 'The dialogue says "the applicant"; the notice spells the applicant\'s name Shanoan Cotton.'},
        {'area': 'names', 'asr': 'Suspected carpal tunnel syndrome in the left wrist', 'clue': 'Suspected, not confirmed; left, not right. The witness contrasts her finding with the report.'},
        {'area': 'names', 'asr': 'zerostomia', 'clue': 'The question asks about dry mouth; xerostomia is the medical term.'},
        {'area': 'names', 'asr': 'Selex', 'clue': 'Nothing in the exchange says which medication: Celexa and Celebrex both fit.'},
    ],
}

NAMES_BAD = """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, please state your name for the record.
     A    Natalie Brousard.  The last name is spelled B-R-O-U-S-S-A-R-D.
     Q    I represent the district with regard to the applicant Shino and Cotton.
          Doctor, what did you diagnose?
     A    Carpal tunnel syndrome in the right wrist.  The report says right, but it was the left.
     Q    Did she have dry mouth?
     A    Yes, xerostomia from the medication.
     Q    Which medication?
     A    She was taking Celebrex at the time."""


def test_names_expected_draft_has_no_failures():
    result = grade(Case(NAMES), NAMES['expected'])
    assert result['failures'] == []
    # Every term is evaluated, including the one that correctly stays unchanged.
    assert result['counts']['names']['evaluated'] == 5


def test_names_failures_and_orange_highlights():
    result = grade(Case(NAMES), NAMES_BAD)
    names = [f for f in result['failures'] if f.area == 'names']
    pairs = {(f.category, f.expected, f.actual) for f in names}
    assert ('missed', 'Broussard', 'Brousard') in pairs
    assert ('missed', 'Shanoan Cotton', 'Shino and Cotton') in pairs
    assert ('incorrect', 'Suspected', '(nothing)') in pairs
    assert ('incorrect', 'left', 'right') in pairs
    guess = next(f for f in names if f.category == 'incorrect' and f.actual == 'Celebrex')
    assert 'flagging' in guess.detail and guess.clue.startswith('Nothing in the exchange')
    assert any(f.category == 'missed' and f.expected == 'flagged for review' for f in names)
    highlight = {(f.expected, f.actual) for f in names if f.category == 'highlight'}
    assert ('green background + orange underline', 'no highlight') in highlight
    assert ('no highlight', 'green background + orange underline') in highlight


def test_rendered_term_correction_has_green_and_orange():
    case = Case(NAMES)
    html = '\n'.join(render(case, case.expected))
    assert 'background:#ccffd8; text-decoration: underline #f08c00' in html
    assert '>Broussard<' in html and '>xerostomia<' in html


# Combined: wrong label, right medical wording ------------------------------------

COMBINED = {
    'id': 'combined',
    'witness': 'SPEAKER 2',
    'asr': """Speaker 1: Doctor, what did you find on examination of the wrist?
Speaker 1: I found a positive Tinel's sign at the right wrist and diagnosed carpal tunnel syndrome.
Speaker 1: Did you order nerve conduction studies?
Speaker 2: Yes, I did.""",
    'expected': """EXAMINATION
BY SPEAKER 1:
     Q    Doctor, what did you find on examination of the wrist?
     A    I found a positive Tinel's sign at the right wrist and diagnosed carpal tunnel syndrome.
     Q    Did you order nerve conduction studies?
     A    Yes, I did.""",
    'terms': ["Tinel's sign", 'carpal tunnel syndrome', 'nerve conduction studies'],
    'checkpoints': [
        {'area': 'speakers', 'asr': "I found a positive Tinel's sign", 'clue': 'The doctor reports her own examination findings in answer to the question.'},
    ],
}


def test_combined_expected_result_is_a_yellow_label_with_testimony_untouched():
    case = Case(COMBINED)
    assert grade(case, COMBINED['expected'])['failures'] == []
    lines = render(case, case.expected)
    assert lines[3].startswith('     <span style="background:#fff3a3">A</span>')
    assert '#ccffd8' not in '\n'.join(lines)


def test_combined_relabel_that_also_rewrites_testimony_fails_wording_and_highlights():
    draft = COMBINED['expected'].replace("positive Tinel's sign at the right wrist", 'positive Tinel sign at the left wrist')
    result = grade(Case(COMBINED), draft)
    assert ('speakers', 'incorrect') not in kinds(result)
    assert {f.area for f in result['failures'] if f.category == 'incorrect'} == {'names', 'wording'}
    assert any(f.category == 'highlight' and f.actual.startswith('green background') for f in result['failures'])


def test_combined_label_kept_from_gemini_is_missed():
    draft = COMBINED['expected'].replace("     A    I found", "     Q    I found")
    result = grade(Case(COMBINED), draft)
    assert kinds(result) == [('speakers', 'highlight'), ('speakers', 'missed')]
    highlight = next(f for f in result['failures'] if f.category == 'highlight')
    assert (highlight.expected, highlight.actual) == ('yellow label', 'no label highlight')


# Exclusions and report ---------------------------------------------------------

def test_excluded_spans_are_not_graded():
    record = {**NAMES, 'exclude': [{'asr': 'Brousard', 'reason': 'restored during review'}]}
    result = grade(Case(record), NAMES_BAD)
    assert not any(f.expected == 'Broussard' for f in result['failures'])
    assert result['counts']['names']['not_graded'] >= 1


def test_report_lists_failures_with_excerpt_clue_expected_and_actual():
    cases = [Case({**NAMES, 'drafts': {'sample': NAMES_BAD}})]
    html = report_html(cases, run(cases))
    for text in ('Missed corrections', 'Incorrect edits', 'Highlight errors', 'Gemini excerpt',
                 'Contextual clue', 'Expected', 'Actual', 'Shino and Cotton'):
        assert text in html


# Optional cleanup, saved drafts and loading ----------------------------------

def test_hand_marked_optional_words_count_either_way():
    record = {'id': 'restart', 'witness': 'SPEAKER 2',
              'asr': 'Speaker 1: Where is that?\nSpeaker 2: If you look on page on the medical history on page eight.',
              'expected': '     Q    Where is that?\n     A    If you look on page -- on the medical history on page 8.',
              'optional': [{'asr': 'look [on page] on the medical', 'reason': 'Abandoned start.'}]}
    # Either copy of "on" can be the one removed; the result is the same.
    dropped = '     Q    Where is that?\n     A    If you look on the medical history on page 8.'
    assert grade(Case(record), dropped)['failures'] == []
    assert grade(Case(record), record['expected'])['failures'] == []
    # Words outside the brackets still count.
    lost = '     Q    Where is that?\n     A    If you look on the history on page 8.'
    assert ('wording', 'incorrect') in kinds(grade(Case(record), lost))


def test_review_note_label_decides_its_area():
    assert note_area('Name spelling: the witness spells only her last name.') == 'names'
    assert note_area('Speaker uncertain: Gemini says the witness.') == 'speakers'
    assert note_area('Wording gap: the witness stops mid-sentence.') == 'wording'
    assert note_area('Paragraph: two answers in a row.') == 'paragraphs'
    # Without a label, keywords decide.
    assert note_area('Could be the witness or counsel.') == 'speakers'


SAVED = {
    'id': 'saved', 'witness': 'SPEAKER 2',
    'asr': """Speaker 1: Did you see the zerostoma in the records?
Speaker 2: Yes, it proceeds the injury. And you note I saw it. Thank you so much if there's""",
    'expected': """     Q    Did you see the xerostomia in the records?
     A    Yes, it precedes the injury.  And you note -- I saw it.  Thank you so much if there's --""",
}
REPORTER = """     Q    Did you see the xerostomia in the records?
     A    Yes, it proceeds the injury.  I saw it."""
SAVED_DRAFT = """     Q    Did you see the xerostomia in the records?
     A    Yes, it precedes the injury.  I saw it."""


def test_restoration_spans_find_reporter_wording_in_a_saved_draft():
    case = Case(SAVED)
    spans = {tuple(x['span']): x['reason'] for x in restoration_spans(case, SAVED_DRAFT, REPORTER)}
    text = {span: ' '.join(t.raw for t in case.asr[slice(*span)]) for span in spans}
    # "xerostomia" matches the reporter, so review may have restored it.
    assert 'zerostoma' in text.values()
    # "precedes" differs from the reporter, so it is the AI's own correction.
    assert 'proceeds' not in text.values()
    # Both leave out "you note", and the reporter's text ends before the last words.
    assert any(value.endswith('you note') for value in text.values())
    assert "Thank you so much if there's" in text.values()
    assert any('does not reach' in reason for reason in spans.values())


def test_hidden_flags_are_not_graded():
    case = Case(WORDING)
    unflagged = WORDING['expected'].replace(' [REVIEW 1]', '').split('\nREVIEW NOTES')[0]
    assert ('wording', 'missed') in kinds(grade(case, unflagged))
    result = grade(case, unflagged, flags_visible=False)
    assert result['failures'] == []
    assert result['counts']['wording']['not_graded'] == 1


def test_load_cases_reads_case_folders_and_reporter_files(tmp_path):
    folder = tmp_path / 'saved'
    folder.mkdir()
    (folder / 'asr.txt').write_text(SAVED['asr'], encoding='utf-8')
    (folder / 'expected.txt').write_text(SAVED['expected'], encoding='utf-8')
    (folder / 'draft.txt').write_text(SAVED_DRAFT, encoding='utf-8')
    (folder / 'reporter.txt').write_text(REPORTER, encoding='utf-8')
    (folder / 'case.json').write_text(json.dumps({
        'id': 'saved', 'witness': 'SPEAKER 2', 'asr_file': 'asr.txt', 'expected_file': 'expected.txt',
        'terms': [{'term': 'xerostomia', 'heard': ['zerostoma']}],
        'drafts': {'saved draft': {'file': 'draft.txt', 'reporter_file': 'reporter.txt', 'flags_visible': False}}}),
        encoding='utf-8')
    cases = load_cases(tmp_path)
    [result] = run(cases)
    assert result['failures'] == []
    assert result['counts']['names']['not_graded'] == 1
    assert len(result['excluded']) == 3
