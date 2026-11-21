"""Q/A or colloquy from whom each turn addressed, settled by the exchange around it."""
import pytest

from app.src.addressees import _spoken, addressed, revise

OPENING = ['EXAMINATION',
           'BY MR. SWEET:',
           '     Q    Doctor, please turn to your report.',
           '     A    Okay.']
QUESTION = 'What page are you on again, and what paragraph?'
CLARIFY = "Are you asking me or counsel?  Sorry."
# How the formatter might have labeled the three turns before this pass.
LABELINGS = {'question as Q': ('Q', 'THE WITNESS', 'MR. SWEET'),
             'all Q and A': ('Q', 'A', 'Q'),
             'all colloquy': ('MR. SWEET', 'THE WITNESS', 'MR. SWEET')}


def line(label, text):
    return f'     {label}    {text}' if label in ('Q', 'A') else f'     {label}:  {text}'


def exchange(labels, reply, *after):
    question, clarify, answer = labels
    return '\n'.join(OPENING + [line(question, QUESTION), line(clarify, CLARIFY), line(answer, reply), *after])


@pytest.mark.parametrize('labels', LABELINGS.values(), ids=LABELINGS.keys())
def test_a_reply_to_counsel_makes_the_question_and_both_replies_colloquy(labels):
    revised, notes = revise(exchange(labels, "Counsel, I'm sorry."))
    assert revised.split('\n')[4:] == [
        '     MR. SWEET:  What page are you on again, and what paragraph?',
        '     THE WITNESS:  Are you asking me or counsel?  Sorry.',
        "     MR. SWEET:  Counsel, I'm sorry."]
    assert revised.split('\n')[:4] == OPENING
    if labels[0] == 'Q':
        assert notes[0]['text'] == QUESTION and notes[0]['label'] == 'MR. SWEET'
        assert "“Counsel, I'm sorry.”" in notes[0]['why'] and 'addressed to counsel' in notes[0]['why']


@pytest.mark.parametrize('labels', LABELINGS.values(), ids=LABELINGS.keys())
def test_a_reply_to_the_witness_makes_the_exchange_q_and_a(labels):
    """The same opening with "You, Doctor." The labels follow the clarification, not the
    formatter's first guess."""
    revised, _ = revise(exchange(labels, 'You, Doctor.', '     THE WITNESS:  Page 12, paragraph 3.'))
    assert revised.split('\n') == OPENING + [
        '     Q    What page are you on again, and what paragraph?',
        '     A    Are you asking me or counsel?  Sorry.',
        '     Q    You, Doctor.',
        '     A    Page 12, paragraph 3.']


def test_the_reply_decides_the_label_of_the_same_question():
    counsel, _ = revise(exchange(LABELINGS['question as Q'], "Counsel, I'm sorry."))
    witness, _ = revise(exchange(LABELINGS['question as Q'], 'You, Doctor.'))
    assert line('MR. SWEET', QUESTION) in counsel.split('\n')
    assert line('Q', QUESTION) in witness.split('\n')


def test_colloquy_continues_until_the_examiner_turns_back_to_the_witness():
    draft = exchange(LABELINGS['all Q and A'], "Counsel, I'm sorry.",
                     '',
                     '     MS. JONES:  Page 12, paragraph 3.',
                     '',
                     '     Q    Thank you, counsel.',
                     '     Q    Doctor, do you see paragraph 3?',
                     '     A    Yes, I do.')
    revised, _ = revise(draft)
    assert revised.split('\n')[4:] == [
        '     MR. SWEET:  What page are you on again, and what paragraph?',
        '     THE WITNESS:  Are you asking me or counsel?  Sorry.',
        "     MR. SWEET:  Counsel, I'm sorry.",
        '',
        '     MS. JONES:  Page 12, paragraph 3.',
        '',
        '     MR. SWEET:  Thank you, counsel.',
        'BY MR. SWEET:',
        '     Q    Doctor, do you see paragraph 3?',
        '     A    Yes, I do.']


def test_a_turn_that_thanks_counsel_and_then_asks_the_witness_is_split_there():
    draft = exchange(LABELINGS['question as Q'], "Counsel, I'm sorry.",
                     '     MS. JONES:  Page 12, paragraph 3.',
                     'BY MR. SWEET:',
                     '     Q    Thank you.  Doctor, do you see paragraph 3?',
                     '     A    Yes, I do.')
    revised, notes = revise(draft)
    assert revised.split('\n')[7:] == [
        '     MS. JONES:  Page 12, paragraph 3.',
        '     MR. SWEET:  Thank you.',
        'BY MR. SWEET:',
        '     Q    Doctor, do you see paragraph 3?',
        '     A    Yes, I do.']
    assert [n['label'] for n in notes][-2:] == ['MR. SWEET', 'Q']
    assert _spoken(revised) == _spoken(draft)


def test_a_question_the_witness_answers_resumes_the_examination():
    draft = exchange(LABELINGS['all colloquy'], "Counsel, I'm sorry.",
                     '     MS. JONES:  It is page 12.',
                     '     MR. SWEET:  And do you see where it says lumbar strain?',
                     '     MS. JONES:  Objection.  Form.',
                     '     THE WITNESS:  Yes.')
    revised, _ = revise(draft)
    assert revised.split('\n')[7:] == [
        '     MS. JONES:  It is page 12.',
        'BY MR. SWEET:',
        '     Q    And do you see where it says lumbar strain?',
        '     MS. JONES:  Objection.  Form.',
        '     A    Yes.']


def test_generic_labels_come_from_who_spoke_each_turn():
    """The formatter keeps Gemini's numbers. Its input says who spoke each turn, so the
    witness's clarification goes under the witness's number."""
    source = '\n'.join(['Speaker 1: Doctor, please turn to your report.',
                        'Speaker 2: Okay.',
                        f'Speaker 1: {QUESTION}',
                        'Speaker 2: Are you asking me or counsel? Sorry.',
                        "Speaker 1: Counsel, I'm sorry.",
                        'Speaker 3: Page 12, paragraph 3.',
                        'Speaker 1: Thank you. Doctor, do you see paragraph 3?',
                        'Speaker 2: Yes, I do.'])
    draft = '\n'.join(['     SPEAKER 2:  I do.',
                       'EXAMINATION',
                       'BY SPEAKER 1:',
                       '     Q    Doctor, please turn to your report.',
                       '     A    Okay.',
                       f'     Q    {QUESTION}',
                       f'     A    {CLARIFY}',
                       "     Q    Counsel, I'm sorry.",
                       '',
                       '     SPEAKER 3:  Page 12, paragraph 3.',
                       '',
                       'BY SPEAKER 1:',
                       '     Q    Thank you.  Doctor, do you see paragraph 3?',
                       '     A    Yes, I do.'])
    revised, _ = revise(draft, 'Speaker 2: I do.\n' + source)
    assert revised.split('\n')[5:] == [
        f'     SPEAKER 1:  {QUESTION}',
        f'     SPEAKER 2:  {CLARIFY}',
        "     SPEAKER 1:  Counsel, I'm sorry.",
        '',
        '     SPEAKER 3:  Page 12, paragraph 3.',
        '',
        '     SPEAKER 1:  Thank you.',
        'BY SPEAKER 1:',
        '     Q    Doctor, do you see paragraph 3?',
        '     A    Yes, I do.']


def test_an_examination_that_opens_with_a_remark_to_counsel_starts_at_the_first_question():
    draft = '\n'.join(['     THE WITNESS:  I do.',
                       'EXAMINATION',
                       'BY MR. SWEET:',
                       f'     Q    {QUESTION}',
                       f'     A    {CLARIFY}',
                       "     Q    Counsel, I'm sorry.",
                       '     MS. JONES:  Page 12.',
                       '     Q    Doctor, do you see it?',
                       '     A    Yes.'])
    revised, _ = revise(draft)
    assert revised.split('\n') == [
        '     THE WITNESS:  I do.',
        f'     MR. SWEET:  {QUESTION}',
        f'     THE WITNESS:  {CLARIFY}',
        "     MR. SWEET:  Counsel, I'm sorry.",
        '     MS. JONES:  Page 12.',
        'EXAMINATION',
        'BY MR. SWEET:',
        '     Q    Doctor, do you see it?',
        '     A    Yes.']


@pytest.mark.parametrize('reply, whom', [
    ("Counsel, I'm sorry.", 'counsel'), ('Sorry, counsel.', 'counsel'), ('Not you.', 'counsel'),
    ("I'm sorry, Doctor, I was asking counsel.", 'counsel'), ('Your attorney.', 'counsel'),
    ('You, Doctor.', 'witness'), ("I'm asking you, Doctor.", 'witness'), ('Doctor.', 'witness'),
    ('Yes, you.', 'witness'), ('Him.', None), ('Go ahead.', None)])
def test_whom_the_reply_names(reply, whom):
    assert addressed(reply) == whom


@pytest.mark.parametrize('clarify', ['Are you asking me about January?', 'I am not sure.'])
def test_a_draft_without_an_addressee_question_is_unchanged(clarify):
    draft = '\n'.join(OPENING + [line('Q', QUESTION), line('A', clarify), line('Q', "Counsel, I'm sorry.")])
    assert revise(draft) == (draft, [])


def test_continuation_paragraphs_and_review_notes_stay_put():
    draft = exchange(LABELINGS['question as Q'], "Counsel, I'm sorry.",
                     '          And the next paragraph too.',
                     '',
                     'REVIEW NOTES',
                     '     A    Not a turn.')
    revised, _ = revise(draft)
    assert revised.split('\n')[-5:] == ["     MR. SWEET:  Counsel, I'm sorry.",
                                        '          And the next paragraph too.', '', 'REVIEW NOTES',
                                        '     A    Not a turn.']


def test_an_interruption_by_the_other_attorney_stays_colloquy_until_the_examiner_resumes():
    """Mr. Sweet interrupts Mr. Ramirez's examination to ask counsel for the page. The
    formatter put Mr. Sweet's turns under Mr. Ramirez's examination as Q. Who spoke comes
    from the labels the formatter was given, so they go back under SPEAKER 3."""
    source = '\n'.join(['Speaker 1: Doctor, is that correct?',
                        'Speaker 2: Correct.',
                        "Speaker 3: Counsel, I'm sorry for interrupting. What page are you on again, and what "
                        'paragraph?',
                        'Speaker 2: Are you asking me or counsel? Sorry.',
                        "Speaker 3: Counsel. I'm sorry.",
                        "Speaker 1: Oh, sorry. I'm here.",
                        'Speaker 3: What page are you on again in this report?',
                        'Speaker 1: Never mind. Strike that question, Doctor. Did you evaluate the records?',
                        'Speaker 2: Correct.'])
    draft = '\n'.join(['     SPEAKER 3:  Good morning.',
                       'EXAMINATION',
                       'BY SPEAKER 1:',
                       '     Q    Doctor, is that correct?',
                       '     A    Correct.',
                       "     Q    Counsel, I'm sorry for interrupting.  What page are you on again, and what "
                       'paragraph?',
                       f'     A    {CLARIFY}',
                       "     Q    Counsel.  I'm sorry.",
                       "     SPEAKER 1:  Oh, sorry.  I'm here.",
                       '     SPEAKER 3:  What page are you on again in this report?',
                       'BY SPEAKER 1:',
                       '     Q    Never mind.  Strike that question, Doctor.  Did you evaluate the records?',
                       '     A    Correct.'])
    revised, notes = revise(draft, 'Speaker 3: Good morning.\n' + source)
    assert revised.split('\n')[5:] == [
        "     SPEAKER 3:  Counsel, I'm sorry for interrupting.  What page are you on again, and what paragraph?",
        f'     SPEAKER 2:  {CLARIFY}',
        "     SPEAKER 3:  Counsel.  I'm sorry.",
        "     SPEAKER 1:  Oh, sorry.  I'm here.",
        '     SPEAKER 3:  What page are you on again in this report?',
        'BY SPEAKER 1:',
        '     Q    Never mind.  Strike that question, Doctor.  Did you evaluate the records?',
        '     A    Correct.']
    assert 'attorney' in notes[0]['why']


def test_a_question_from_the_other_attorney_to_the_witness_is_not_examination():
    """"You, Doctor." from an attorney who is not examining leaves the exchange as colloquy."""
    draft = '\n'.join(OPENING + ['     MS. JONES:  What page are you on?', f'     THE WITNESS:  {CLARIFY}',
                                 '     MS. JONES:  You, Doctor.', '     THE WITNESS:  Page 12.'])
    assert revise(draft) == (draft, [])
