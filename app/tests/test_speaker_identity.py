"""Voices a later chunk numbered afresh, linked by their voice and never by elimination."""
import json
import wave
from pathlib import Path
from types import SimpleNamespace

from app.src.audio_pipeline import Word
from app.src.speaker_identity import (DIFFERENT, LINKED, SAME, UNRESOLVED, identifying_clips, link_voices,
                                      verify_members)


def say(speaker, start, text, pace=0.4):
    return [Word(token, speaker, round(start + i * pace, 2), round(start + i * pace + 0.3, 2))
            for i, token in enumerate(text.split())]


def deposition():
    """Speaker 3 objects in chunk 1, then returns in chunk 2 as provisional Speaker 4."""
    words = (say('Speaker 1', 10, 'Doctor, did you review the operative report from March?')
             + say('Speaker 2', 16, 'Yes, I reviewed it before I wrote my report.')
             + say('Speaker 3', 22, 'Objection. Calls for speculation and lacks foundation.')
             + say('Speaker 1', 30, 'You can answer the question, Doctor.')
             + say('Speaker 2', 2000, 'The tear was small and it was in the medial meniscus.')
             + say('Speaker 4', 2010, 'Objection. Vague as to time and assumes facts.')
             + say('Speaker 4', 2100, 'I will join in that objection for the record.'))
    identities = {'Speaker 1': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 2': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 3': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 4': {'chunk': 2, 'status': 'provisional', 'suggested': None,
                                'evidence': 'did not speak in the minute shared with chunk 1'}}
    return words, identities


def test_a_returning_voice_matched_by_its_voice_takes_the_earlier_label():
    words, identities = deposition()
    asked = []

    def compare(question):
        asked.append(question)
        return {'matches': {c['id']: 'Speaker 3' for c in question['candidates']}, 'why': 'Same deep voice.'}
    linked, found, notes = link_voices(words, identities, compare)
    assert {w.speaker for w in linked if w.start >= 2010} == {'Speaker 3'}
    assert found['Speaker 4']['status'] == LINKED and found['Speaker 4']['to'] == 'Speaker 3'
    # One request: every earlier voice is a reference, and both of the voice's clearest clips are candidates.
    (question,) = asked
    assert [r['label'] for r in question['references']] == ['Speaker 1', 'Speaker 2', 'Speaker 3']
    assert sorted(c['text'] for c in question['candidates']) == [
        'I will join in that objection for the record.', 'Objection. Vague as to time and assumes facts.']
    assert notes and 'Speaker 3' in notes[0]


def test_a_voice_is_never_linked_because_one_label_is_left():
    words, identities = deposition()
    # Speaker 3 is the only earlier voice not heard in chunk 2, but the audio is uncertain.
    linked, found, notes = link_voices(words, identities,
                                       lambda q: {'matches': {c['id']: 'uncertain' for c in q['candidates']}})
    assert {w.speaker for w in linked if w.start >= 2010} == {'Speaker 4'}
    assert found['Speaker 4']['status'] == UNRESOLVED and found['Speaker 4']['heard'] == 'uncertain'
    assert 'only because that participant has not spoken' in notes[0]
    # Without an audio check the voice stays unresolved too.
    _, found, _ = link_voices(words, identities, None)
    assert found['Speaker 4']['status'] == UNRESOLVED


def test_two_clips_must_agree_before_voices_are_linked():
    words, identities = deposition()
    _, found, _ = link_voices(words, identities,
                              lambda q: {'matches': {'C1': 'Speaker 3', 'C2': 'Speaker 1'}})
    assert found['Speaker 4']['status'] == UNRESOLVED
    _, found, _ = link_voices(words, identities, lambda q: {'matches': {'C1': 'none', 'C2': 'none'}})
    assert found['Speaker 4']['heard'] == 'none'


def test_the_identifying_clip_is_a_clear_full_sentence():
    words = (say('Speaker 7', 100, 'Okay.') + say('Speaker 1', 101, 'Go ahead.')
             + say('Speaker 7', 110, 'Thank you, Doctor, I have nothing further at this time.')
             + say('Speaker 7', 140, 'and the um'))
    (clip,) = identifying_clips(words, 'Speaker 7')
    assert clip['text'] == 'Thank you, Doctor, I have nothing further at this time.'
    assert clip['start'] == 110


def test_an_unrelated_voice_with_the_same_gemini_number_is_not_grouped():
    words = (say('Speaker 6', 500, 'Thank you, Doctor, I have nothing further at this time.')
             + say('Speaker 2', 506, 'Thank you.')
             + say('Speaker 6', 520, 'Counsel, do you have any questions?')
             + say('Speaker 2', 524, 'No.')
             + say('Speaker 6', 530, 'Let us go off the record.')       # the reporter, same Gemini number
             + say('Speaker 2', 534, 'Sure.')
             + say('Speaker 6', 540, 'Okay.'))
    (clip,) = identifying_clips(words, 'Speaker 6')
    heard = {520: 'Speaker 6', 530: 'none', 540: 'uncertain'}

    def compare(question):
        assert [r['label'] for r in question['references']] == ['Speaker 6']
        return {'matches': {c['id']: heard[int(c['start'])] for c in question['candidates']}}
    verdicts = verify_members(words, 'Speaker 6', clip, compare)
    starts = {words[first].start: verdict for first, verdict in verdicts.items()}
    assert starts == {500: SAME, 520: SAME, 530: DIFFERENT, 540: 'uncertain'}


def test_voice_comparison_joins_the_excerpts_into_one_clip(tmp_path, monkeypatch):
    from app.src import speaker_audio
    from app.src.speaker_audio import VoiceComparison
    prepared, sent, deleted = [], [], []

    def prepare(path, segment, destination):
        prepared.append(segment)
        with wave.open(str(destination), 'wb') as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(16000)
            clip.writeframes(b'\1\0' * int(16000 * (segment['end'] - segment['start'])))
    monkeypatch.setattr(speaker_audio.media, 'prepare', prepare)

    class Files:
        def upload(self, file, config):
            with wave.open(file, 'rb') as clip:
                sent.append(clip.getnframes() / clip.getframerate())
            return SimpleNamespace(name='files/voices', uri='gs://voices', state='ACTIVE')

        def delete(self, name):
            deleted.append(name)

    class Interactions:
        def create(self, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(status='completed', output_text=json.dumps(
                {'matches': {'C1': 'speaker 3', 'C2': 'none', 'C3': 'Speaker 9'}, 'why': 'Deep voice.'}))

    check = VoiceComparison(tmp_path / 'job.wav', 'key', 'gemini-4-argon',
                            sdk=SimpleNamespace(files=Files(), interactions=Interactions()))
    answer = check({'references': [{'label': 'Speaker 1', 'start': 10, 'end': 14, 'text': 'Doctor, why?'},
                                   {'label': 'Speaker 3', 'start': 22, 'end': 25, 'text': 'Objection.'}],
                    'candidates': [{'id': 'C1', 'start': 2010, 'end': 2013, 'text': 'Objection. Vague.'},
                                   {'id': 'C2', 'start': 2100, 'end': 2102, 'text': 'Join.'},
                                   {'id': 'C3', 'start': 2200, 'end': 2201, 'text': 'Okay.'}]})
    # Labels not among the references are uncertain, never a new match.
    assert answer == {'matches': {'C1': 'Speaker 3', 'C2': 'none', 'C3': 'uncertain'}, 'why': 'Deep voice.'}
    assert prepared[0] == {'start': 9.75, 'end': 14.25} and len(prepared) == 5
    duration, request = sent
    assert abs(duration - (4.5 + 3.5 + 3.5 + 2.5 + 1.5 + 4 * 1.0)) < .01
    payload = json.loads(request['input'][1]['text'])
    assert payload['references'][1] == {'id': 'R2', 'label': 'Speaker 3', 'text': 'Objection.',
                                        'from': 5.5, 'to': 9.0}
    assert payload['candidates'][0]['from'] == 10.0 and deleted == ['files/voices']
    assert 'Words, roles and which labels have not been heard recently are never a reason' in \
        request['system_instruction']


def run_worker(tmp_path, monkeypatch, words, identities, decisions, compare):
    from hashlib import sha256
    from app.src import jobs
    from app.src.audio_pipeline import Transcription, render
    from app.src.jobs import ProcessingWorker, Request, TranscriptionCoordinator
    from shared.speaker_review import PROMPT as SPEAKER_PROMPT
    wav = tmp_path / 'job.wav'
    wav.write_bytes(b'recording')
    monkeypatch.setattr(jobs, 'has_key', lambda key: True)
    monkeypatch.setattr(jobs, 'AudioSpeakerCheck', lambda *args: (lambda q: {'speaker': 'uncertain'}))
    monkeypatch.setattr(jobs, 'VoiceComparison', lambda *args: compare)
    sent = {}

    class Pipeline:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, path, progress, **kwargs):
            return Transcription(render(words), tuple(words), (), 3000000, sha256(path.read_bytes()).hexdigest(),
                                 identities)

    class Processor:
        def __init__(self, config, model):
            pass

        def check_ready(self):
            pass

        def complete(self, text, prompt):
            if prompt == SPEAKER_PROMPT:
                sent['speakers'] = json.loads(text)
                return json.dumps(decisions)
            if prompt == 'rules':
                sent['formatter'] = text
                return text
            return '{"words": []}'

    from app.tests.test_suggestions import revision
    request = Request('doc', str(wav), 'formatter', 'transcribe', 'rules', {'gemini_api_key': 'key'},
                      original=revision('The rough has no speaker labels yet.'), review_model='reviewer')
    worker = ProcessingWorker(request, TranscriptionCoordinator(), Pipeline, Processor)
    failed, reviewed = [], []
    worker.failed.connect(lambda *args: failed.append(args))
    worker.reviewed.connect(lambda *args: reviewed.append(args))
    worker.run()
    assert not failed, failed
    return sent, reviewed[0][1]


def test_the_worker_links_a_returning_voice_before_the_speaker_review(tmp_path, monkeypatch):
    words, identities = deposition()

    def compare(question):
        return {'matches': {c['id']: question['references'][-1]['label'] for c in question['candidates']}}
    sent, result = run_worker(tmp_path, monkeypatch, words, identities, {'turns': []}, compare)
    # The speaker review and the formatter see one label for the returning attorney.
    assert 'Speaker 4' not in sent['formatter'] and sent['formatter'].count('Speaker 3:') == 2
    assert any("Speaker 4 was chunk 2's number for Speaker 3" in note for note in sent['speakers']['notes'])
    record = result.after_ai[2]['speaker_review']
    assert 'Speaker 4' not in [v['label'] for v in record['voices']]


def test_renumbering_found_by_the_review_is_not_highlighted(tmp_path, monkeypatch):
    from shared.speaker_review import label_highlights
    words = (say('Speaker 1', 10, 'Doctor, did you review the report?') + say('Speaker 2', 14, 'Yes, I did.')
             + say('Speaker 5', 2000, 'Doctor, what did it show?') + say('Speaker 2', 2004, 'A small tear.')
             + say('Speaker 5', 2008, 'Thank you, Doctor.'))
    identities = {'Speaker 1': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 2': {'chunk': 1, 'status': 'first chunk'},
                  'Speaker 5': {'chunk': 2, 'status': 'provisional', 'suggested': None, 'evidence': ''}}
    # No voice check: the review gives the later chunk's number back to the examiner by the exchange.
    decisions = {'turns': [{'id': 3, 'speaker': 'SPEAKER 1', 'why': 'The examiner continues.'},
                           {'id': 5, 'speaker': 'SPEAKER 1', 'why': 'The examiner thanks the witness.'}]}
    _, result = run_worker(tmp_path, monkeypatch, words, identities, decisions, None)
    record = result.after_ai[2]['speaker_review']
    assert record['renumbered'] == {'SPEAKER 5': 'SPEAKER 1'}
    assert record['corrected'] == []
    draft = ('     SPEAKER 1:  Doctor, did you review the report?\n     SPEAKER 2:  Yes, I did.\n'
             '     SPEAKER 1:  Doctor, what did it show?\n     SPEAKER 2:  A small tear.\n'
             '     SPEAKER 1:  Thank you, Doctor.')
    assert label_highlights(record, draft) == ()
