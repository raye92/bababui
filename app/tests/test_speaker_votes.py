import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import math
import re
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from app.src import speaker_votes as votes
from app.src.casecat.anchors import AnchoredSpan, Revision
from app.src.suggestion_filter import _paragraphs, begin_review, override_speaker, validate_review
from app.src.suggestions import suggestions


def labeled(lines):
    """Build colloquy lines with native speaker fields, one per (name, body)."""
    old = Revision((AnchoredSpan('root', (), (), ''),))
    for name, body in lines:
        old = old._replace(len(old.text), len(old.text), '     ')
        old = old.insert_field(len(old.text), name, name)
        old = old._replace(len(old.text), len(old.text), f':  {body}\n')
    return old


def tagged(original, tags):
    """Replace each line's label with its AI speaker tag."""
    return ''.join(re.sub(r'^(\s*)[^:]+:', lambda m: f'{m[1]}{tag}:', line, count=1)
                   for line, tag in zip(original.text.splitlines(keepends=True), tags))


SMITH, JONES, WITNESS = 'MR. SMITH', 'MS. JONES', 'THE WITNESS'
TAGS = {SMITH: 'SPEAKER 1', WITNESS: 'SPEAKER 2', JONES: 'SPEAKER 3'}
BASE = [(SMITH, f'Counsel, exhibit {i} is marked for identification.') for i in range(4)] + \
       [(WITNESS, f'I reviewed the records from visit number {i}.') for i in range(4)] + \
       [(JONES, f'We received the supplemental report on page {i}.') for i in range(4)]


def disputed(body, *, reporter=JONES, ai=WITNESS):
    """The reporter wrote `reporter`; the AI tag belongs to `ai`'s speaker."""
    original = labeled(BASE + [(reporter, body)])
    tags = [TAGS[name] for name, _ in BASE] + [TAGS[ai]]
    return original, tagged(original, tags)


class Voice:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def vote(self, paragraphs, index, current, proposed, *, byline=False):
        self.calls.append((index, current, proposed))
        return self.answer


def review(original, text, voice=None):
    state = SimpleNamespace(original=original)
    begin_review(state, text, voice=voice)
    location = next(p for p in state.review['locations'] if 'decision' in p)
    return state, location


def test_decide_needs_a_second_source_to_change_or_keep_a_label():
    assert votes.decide(JONES, WITNESS) == votes.FLAG
    assert votes.decide(JONES, WITNESS, voice=JONES) == votes.KEEP
    assert votes.decide(JONES, WITNESS, context=JONES) == votes.KEEP
    assert votes.decide(JONES, WITNESS, voice=WITNESS) == votes.SUGGEST
    assert votes.decide(JONES, WITNESS, voice=WITNESS, context=WITNESS) == votes.SUGGEST
    assert votes.decide(JONES, WITNESS, voice=WITNESS, context=JONES) == votes.FLAG


@pytest.mark.parametrize('body, current, proposed, examiner, expected', [
    ('Objection.  Foundation.', JONES, WITNESS, SMITH, JONES),
    ('Objection.  Foundation.', WITNESS, JONES, SMITH, JONES),
    ('Objection.  Foundation.', SMITH, JONES, SMITH, JONES),
    ('Counsel, was that the original report?', WITNESS, JONES, SMITH, JONES),
    ('Doctor, could you share your screen?', WITNESS, JONES, SMITH, JONES),
    ('Counsel, was that the original report?', SMITH, JONES, SMITH, None),
    ('Thank you.', JONES, WITNESS, SMITH, None),
    ('Correct.', JONES, WITNESS, SMITH, None),
])
def test_context_votes_only_on_reliable_cues(body, current, proposed, examiner, expected):
    assert votes.context_vote(body, current, proposed, examiner) == expected


def test_only_the_ai_label_disputes_a_courtesy_so_it_needs_review():
    original, text = disputed('Thank you.')
    state, location = review(original, text)
    assert location['decision'] == votes.FLAG
    assert location['votes'] == {'voice': None, 'context': None}
    assert len(suggestions(state.original, state.incoming)) == 1
    validate_review(state.review, state.incoming.text)


def test_voice_support_keeps_the_reporter_label_without_a_suggestion():
    original, text = disputed('Thank you.')
    voice = Voice(JONES)
    state, location = review(original, text, voice)
    assert voice.calls == [(12, JONES, WITNESS)]
    assert location['decision'] == votes.KEEP
    assert state.incoming.text.endswith('MS. JONES:  Thank you.\n')
    assert suggestions(state.original, state.incoming) == []


def test_context_support_keeps_an_attorney_objection():
    original, text = disputed('Objection.  Foundation.')
    state, location = review(original, text)
    assert location['decision'] == votes.KEEP
    assert location['votes']['context'] == JONES
    assert suggestions(state.original, state.incoming) == []


def test_context_agreeing_with_the_ai_label_suggests_the_change():
    original, text = disputed('Objection.  Foundation.', reporter=WITNESS, ai=JONES)
    state, location = review(original, text)
    assert location['decision'] == votes.SUGGEST
    assert state.incoming.text.endswith('MS. JONES:  Objection.  Foundation.\n')
    assert len(suggestions(state.original, state.incoming)) == 1


def test_override_does_not_replace_a_kept_label():
    original, text = disputed('Thank you.')
    state, _ = review(original, text, Voice(JONES))
    override_speaker(state, 'SPEAKER 2', SMITH)
    assert state.incoming.text.endswith('MS. JONES:  Thank you.\n')
    assert state.incoming.text.count('MR. SMITH:') == 8


def test_saved_reviews_reject_unknown_decisions_and_votes():
    original, text = disputed('Thank you.')
    state, location = review(original, text)
    location['decision'] = 'maybe'
    with pytest.raises(ValueError):
        validate_review(state.review, state.incoming.text)
    location.update(decision=votes.KEEP, votes={'voice': 3})
    with pytest.raises(ValueError):
        validate_review(state.review, state.incoming.text)


def test_flagged_attribution_card_says_needs_review():
    from PySide6.QtWidgets import QApplication, QLabel
    from app.src.review_view import ReviewView
    app = QApplication.instance() or QApplication([])
    original, text = disputed('Thank you.')
    state, _ = review(original, text)
    view = ReviewView()
    view.set_revisions(original, state.incoming, review=state.review)
    titles = [card.findChild(QLabel).text() for card in view.cards]
    assert titles == ['Speaker attribution · Needs review']
    view.close()


def test_speech_turns_name_questions_answers_and_colloquy():
    text = ('BY MR. SMITH:\n     Q    Did you examine him?\n     A    Yes.\n'
            '     MS. JONES:  Objection.\n     THE WITNESS:  Sure.\n')
    turns = votes.speech_turns(_paragraphs(text))
    assert {i: name for i, (name, _) in turns.items()} == {1: SMITH, 2: WITNESS, 3: JONES, 4: WITNESS}
    assert text[turns[1][1]:].startswith('Did you')


def voice(f0, seconds, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    phase = 2 * np.pi * f0 * (t + 0.002 * np.sin(2 * np.pi * 5 * t))
    return 0.3 * sum(np.sin(k * phase) / k for k in range(1, 6))


@pytest.mark.parametrize('f0', [90, 145, 200])
def test_pitch_finds_the_fundamental(f0):
    x = voice(f0, 1.0, 8000).astype(np.float32)
    found = votes.pitch_semitones(x)
    assert len(found) > 50
    assert abs(np.median(found) - 12 * math.log2(f0 / 55)) < 0.5


def test_silence_has_no_pitch():
    assert len(votes.pitch_semitones(np.zeros(8000, np.float32))) == 0


class Playback:
    """Each paragraph starts two seconds after the previous one."""
    def position_ms(self, revision, position):
        return revision.text.count('\n', 0, position) * 2000


class Alignment:
    def __init__(self, matches=True):
        self.matches = matches

    def playback(self):
        return Playback()

    def matches_wav(self, path):
        return self.matches


def recording(path, pitches, rate=16000):
    audio = np.concatenate([np.concatenate((voice(f0, 1.5, rate), np.zeros(int(0.5 * rate))))
                            for f0 in pitches])
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())


PITCH = {SMITH: 200, JONES: 145, WITNESS: 90}


@pytest.mark.parametrize('heard, expected', [(JONES, votes.KEEP), (WITNESS, votes.SUGGEST)])
def test_voice_check_compares_the_turn_with_job_profiles(tmp_path, heard, expected):
    original, text = disputed('Thank you.')
    wav = tmp_path / 'job.wav'
    recording(wav, [PITCH[name] for name, _ in BASE] + [PITCH[heard]])
    check = votes.VoiceCheck.create(original, Alignment(), str(wav))
    state, location = review(original, text, check)
    assert location['votes']['voice'] == heard
    assert location['decision'] == expected


def test_voice_check_abstains_for_another_recording_or_close_voices(tmp_path):
    original, text = disputed('Thank you.')
    wav = tmp_path / 'job.wav'
    recording(wav, [PITCH[name] for name, _ in BASE] + [PITCH[JONES]])
    _, location = review(original, text, votes.VoiceCheck.create(original, Alignment(False), str(wav)))
    assert location['votes']['voice'] is None and location['decision'] == votes.FLAG
    close = {SMITH: 200, JONES: 120, WITNESS: 112}
    recording(wav, [close[name] for name, _ in BASE] + [close[JONES]])
    _, location = review(original, text, votes.VoiceCheck.create(original, Alignment(), str(wav)))
    assert location['votes']['voice'] is None and location['decision'] == votes.FLAG
    assert votes.VoiceCheck.create(original, None, str(wav)) is None
