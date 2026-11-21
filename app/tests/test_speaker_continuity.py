"""Job-wide speaker identities across chunks, overlaps and recovery clips."""
import pytest

from app.src.audio_pipeline import (CHUNK_SECONDS, CHUNK_STEP, PROVISIONAL, Word, render, stitch,
                                    stitch_identities)

QUESTION = 'Doctor what did the {n} report show about the knee'.split()
ANSWER = 'It showed a small tear in the {n} meniscus and swelling'.split()


def deposition(length, start=5.0):
    """(participant, absolute start in the WAV, word) for an alternating examination."""
    words, t, n = [], start, 0
    while t < length:
        for who, line in (('examiner', QUESTION), ('doctor', ANSWER)):
            for token in line:
                words.append((who, round(t, 2), token.replace('{n}', f'n{n}')))
                t += 0.5
            t += 1.0
        n += 1
    return [w for w in words if w[1] < length]


def chunk(script, index, labels, length=10_000):
    """What Gemini returns for one chunk: its own speaker numbers and chunk-relative times."""
    start = index * CHUNK_STEP
    end = min(start + CHUNK_SECONDS, length)
    return [Word(text, labels[who], round(t - start, 2), round(t - start + 0.4, 2))
            for who, t, text in script if start <= t < end]


def identities_by_participant(script, words):
    found = {}
    for (who, _, _), word in zip(script, words):
        found.setdefault(who, set()).add(word.speaker)
    return found


def test_each_participant_keeps_one_identity_when_gemini_renumbers_every_chunk():
    # Each chunk's speakers are matched in the minute it shares with the previous
    # chunk, against that chunk's job-wide labels, so chunk 3 follows chunk 2's.
    length = 2 * CHUNK_STEP + CHUNK_SECONDS
    script = deposition(length)
    chunks = [chunk(script, 0, {'examiner': 'spk:0', 'doctor': 'spk:1'}, length),
              chunk(script, 1, {'examiner': 'spk:1', 'doctor': 'spk:0'}, length),  # swapped
              chunk(script, 2, {'examiner': 'spk:2', 'doctor': 'spk:0'}, length)]  # renumbered again
    words, warnings, identities = stitch_identities(chunks)
    # Every word once, at its time in the original WAV.
    assert [(w.start, w.text) for w in words] == [(t, text) for _, t, text in script]
    assert identities_by_participant(script, words) == {'examiner': {'Speaker 1'}, 'doctor': {'Speaker 2'}}
    assert not [w for w in warnings if 'speaker' in w.lower()]
    assert set(identities) == {'Speaker 1', 'Speaker 2'}


@pytest.mark.parametrize('first, second', [(1700, 1760), (1745, 1805), (1742, 1797), (1755, 1815), (1770, 1830)])
@pytest.mark.parametrize('jitter', [0, 0.3])
def test_a_question_asked_twice_a_minute_apart_survives_once_at_each_time(first, second, jitter):
    question = 'Did you review the MRI before the surgery?'.split()
    filler = 'I am not sure I recall that exactly'.split()
    script, t = [], 1600.0
    while t < 1900:
        line, who = (question, 'examiner') if t in (first, second) else (filler, 'doctor')
        for w in line:
            script.append((who, t, w))
            t = round(t + 0.5, 2)
        t = round(t + 0.5, 1)
        for when in (first, second):
            if when - 8 < t < when:
                t = float(when)
    a = [Word(w, {'examiner': 'x', 'doctor': 'y'}[who], t, t + 0.4) for who, t, w in script if t < 1800]
    # The later chunk hears the same audio with its own numbers and slightly different times.
    b = [Word(w, {'examiner': 'q', 'doctor': 'r'}[who], round(t - 1740 + jitter, 2), round(t - 1740 + jitter + 0.4, 2))
         for who, t, w in script if t >= 1740]
    words, _ = stitch([a, b])
    assert [w.text for w in words] == [w for _, _, w in script]
    assert [round(w.start - (jitter if w.start >= 1771 else 0)) for w in words if w.text == 'Did'] == [first, second]
    # The examiner keeps chunk 1's label for both questions.
    assert {w.speaker for w in words if w.text == 'Did'} == {'Speaker 2'}


def test_a_short_utterance_in_the_shared_minute_maps_the_speaker():
    # 261106lewis: the witness answers for the whole shared minute, and the examiner
    # says only "Okay. Now," at its end, at the same moment in both chunks.
    answer = ('I spent a lot of time on this case and I found him to be a pleasant individual '
              'and it was based on the facts and not on my impression ').split() * 2
    a = [Word('Please', 'spk:0', 1600, 1600.4), Word('explain.', 'spk:0', 1600.5, 1601)]
    a += [Word(w, 'spk:1', 1741 + i * 0.9, 1741 + i * 0.9 + 0.5) for i, w in enumerate(answer)]
    a += [Word('Okay.', 'spk:0', 1796.3, 1796.7), Word('Now,', 'spk:0', 1797.0, 1797.3)]
    b = [Word(w, 'spk:0', 1 + i * 0.9, 1 + i * 0.9 + 0.5) for i, w in enumerate(answer)]
    b += [Word('Okay.', 'spk:1', 56.3, 56.7), Word('Now,', 'spk:1', 57.0, 57.3),
          Word('Doctor,', 'spk:1', 57.5, 57.9), Word('your', 'spk:1', 58, 58.3), Word('report?', 'spk:1', 58.5, 59)]
    words, warnings, identities = stitch_identities([a, b])
    assert render(words).endswith('Speaker 1: Okay. Now, Doctor, your report?')
    assert not any('Unmatched' in w for w in warnings)


def test_a_returning_attorney_silent_in_the_shared_minute_is_provisional_not_assigned_by_elimination():
    length = CHUNK_STEP + CHUNK_SECONDS
    script = deposition(length)
    script += [('defense', 600.0, 'Objection.'), ('defense', 600.5, 'Form.'),
               ('defense', 2600.0, 'Objection.'), ('defense', 2600.5, 'Vague.')]
    script.sort(key=lambda w: w[1])
    chunks = [chunk(script, 0, {'examiner': 'spk:0', 'doctor': 'spk:1', 'defense': 'spk:2'}, length),
              chunk(script, 1, {'examiner': 'spk:1', 'doctor': 'spk:0', 'defense': 'spk:2'}, length)]
    words, warnings, identities = stitch_identities(chunks)
    found = identities_by_participant(script, words)
    assert found['examiner'] == {'Speaker 1'} and found['doctor'] == {'Speaker 2'}
    # Speaker 3 is the only label left in chunk 1, but the voice check decides, not elimination.
    assert found['defense'] == {'Speaker 3', 'Speaker 4'}
    assert identities['Speaker 4']['status'] == PROVISIONAL and identities['Speaker 4']['suggested'] is None
    assert identities['Speaker 4']['chunk'] == 2
    assert 'Unmatched speaker in chunk 2 assigned Speaker 4; review the identity.' in warnings


def test_when_gemini_merged_two_voices_only_the_better_match_maps():
    # 2613fceb: chunk 1 put the examiner's interruption under the witness's number.
    words_a = 'it is very different because restrictions change from day to day'.split()
    words_b = 'what do you mean by safer'.split()
    a = [Word(w, 'spk:1', 1741 + i, 1741.5 + i) for i, w in enumerate(words_a)]
    a += [Word(w, 'spk:1', 1760 + i, 1760.5 + i) for i, w in enumerate(words_b)]
    b = [Word(w, 'spk:1', 1 + i, 1.5 + i) for i, w in enumerate(words_a)]
    b += [Word(w, 'spk:2', 20 + i, 20.5 + i) for i, w in enumerate(words_b)]
    b += [Word(w, 'spk:2', 70 + i, 70.5 + i) for i, w in enumerate('next question please'.split())]
    b += [Word(w, 'spk:1', 80 + i, 80.5 + i) for i, w in enumerate('it still depends'.split())]
    words, _, identities = stitch_identities([a, b])
    assert {w.speaker for w in words if w.text in ('it', 'still', 'depends')} == {'Speaker 1'}
    # Both of chunk 2's voices voted for Speaker 1. The stronger match keeps it;
    # the other is not forced onto a label and waits for the voice check.
    assert {w.speaker for w in words if w.text in ('next', 'question', 'please')} == {'Speaker 2'}
    assert identities['Speaker 2']['status'] == PROVISIONAL


def test_one_shared_word_only_suggests_a_match():
    a = [Word('Question', 'spk:0', 1750, 1750.5), Word('here?', 'spk:0', 1751, 1751.5)]
    a += [Word(w, 'spk:0', 1760 + i, 1760.5 + i) for i, w in enumerate('was that your opinion then'.split())]
    a += [Word('Yes.', 'spk:1', 1795.2, 1795.5)]
    b = [Word(w, 'spk:0', 20 + i, 20.5 + i) for i, w in enumerate('was that your opinion then'.split())]
    b += [Word('Yes.', 'spk:1', 55.2, 55.5), Word('It', 'spk:1', 62, 62.3), Word('was.', 'spk:1', 62.5, 63)]
    words, _, identities = stitch_identities([a, b])
    assert words[-1].speaker == 'Speaker 3'
    assert identities['Speaker 3']['suggested'] == 'Speaker 2'
    assert identities['Speaker 3']['status'] == PROVISIONAL


def test_a_recovery_clip_with_fresh_numbering_keeps_the_chunk_identities(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, media
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: 1500)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))
    script = deposition(1500)
    before = [w for w in script if w[1] < 600]
    after = [w for w in script if w[1] >= 700]
    missing = [w for w in script if 600 <= w[1] < 700]

    def transcribe(path, progress=None):
        start = prepared[-1]['start']
        if start == 0:  # Gemini skips from 9:59 to 11:40.
            return [Word(w, {'examiner': 'spk:0', 'doctor': 'spk:1'}[who], t, t + 0.4) for who, t, w in before + after]
        # The recovery clip numbers its speakers afresh, and adds one voice it cannot match.
        offset = start
        clip = [Word(w, {'examiner': 'spk:1', 'doctor': 'spk:0'}[who], round(t - offset, 2), round(t - offset + 0.4, 2))
                for who, t, w in script if offset <= t < prepared[-1]['end']]
        return clip + [Word('Hello?', 'spk:2', 50, 50.4)]
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    result = pipeline.run(wav)
    assert len(prepared) == 2
    spoken = [w for w in result.words if w.text != 'Hello?']
    assert [(w.start, w.text) for w in spoken] == [(t, w) for _, t, w in script]
    assert identities_by_participant(script, spoken) == {'examiner': {'Speaker 1'}, 'doctor': {'Speaker 2'}}
    assert [w for w in result.words if w.text == 'Hello?'][0].speaker == 'Speaker 3'
    assert result.identities['Speaker 3']['status'] == PROVISIONAL
    assert missing and all(any(w.start == t for w in spoken) for _, t, _ in missing)


def test_the_pipeline_keeps_one_identity_per_participant_across_three_chunks(tmp_path, monkeypatch):
    from app.src.audio_pipeline import AudioPipeline, FIRST, media
    length = 2 * CHUNK_STEP + CHUNK_SECONDS
    script = deposition(length)
    wav = tmp_path / 'input.wav'
    wav.write_bytes(b'wav')
    monkeypatch.setattr(media, 'probe', lambda _: length)
    prepared = []
    monkeypatch.setattr(media, 'prepare', lambda source, segment, dest: prepared.append(dict(segment)))
    numbering = [{'examiner': 'spk:0', 'doctor': 'spk:1'}, {'examiner': 'spk:1', 'doctor': 'spk:0'},
                 {'examiner': 'spk:2', 'doctor': 'spk:0'}]

    def transcribe(path, progress=None):
        index = round(prepared[-1]['start'] / CHUNK_STEP)
        return chunk(script, index, numbering[index], length)
    pipeline = AudioPipeline('fake', tmp_path / 'cache')
    monkeypatch.setattr(pipeline, 'transcribe_segment', transcribe)
    result = pipeline.run(wav)
    assert len(prepared) == 3
    assert [(w.start, w.text) for w in result.words] == [(t, text) for _, t, text in script]
    assert identities_by_participant(script, result.words) == {'examiner': {'Speaker 1'}, 'doctor': {'Speaker 2'}}
    assert {label: info['status'] for label, info in result.identities.items()} == {
        'Speaker 1': FIRST, 'Speaker 2': FIRST}
    assert result.text.splitlines()[0].startswith('Speaker 1: Doctor what did the n0 report')
