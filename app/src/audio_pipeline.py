"""WAV transcription and timestamp-aware, best-effort speaker stitching."""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time
import uuid

from evaluation import media
from evaluation.transcription import GeminiTranscriber
from evaluation.storage import file_lock


AUDIO_MODEL = 'gemini-3.5-transcribe'


@dataclass(frozen=True)
class Word:
    text: str
    speaker: str
    start: float
    end: float


def segments(duration):
    if not math.isfinite(duration) or not 0 < duration <= 3540:
        raise ValueError('Choose a WAV recording between 0 and 59 minutes long.')
    return [(0, duration)] if duration <= 1800 else [(0, 1800), (1740, duration)]


def parse_words(response):
    words = []
    for step in getattr(response, 'steps', None) or []:
        if getattr(step, 'type', None) != 'model_output':
            continue
        for block in getattr(step, 'content', None) or []:
            if getattr(block, 'type', None) != 'text':
                continue
            raw = block.text.encode('utf-8')
            annotations = [a for a in (getattr(block, 'annotations', None) or [])
                           if getattr(a, 'type', None) == 'word_info']
            if raw.strip() and not annotations:
                raise ValueError('Transcription is missing word timestamps or speaker tags.')
            for i, a in enumerate(annotations):
                start, end = a.start_index, a.end_index
                if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(raw):
                    raise ValueError('Invalid transcription word offsets.')
                if i and start < annotations[i-1].end_index:
                    raise ValueError('Transcription word offsets are out of order.')
                # Include punctuation between annotations, using the original UTF-8 text.
                next_start = annotations[i+1].start_index if i+1 < len(annotations) else len(raw)
                begin = 0 if i == 0 else start
                text = raw[begin:next_start].decode('utf-8').strip()
                try:
                    t0 = float(a.start_offset.removesuffix('s'))
                    t1 = float(a.end_offset.removesuffix('s'))
                except (AttributeError, TypeError, ValueError):
                    raise ValueError('Transcription is missing valid word timestamps.') from None
                if not a.speaker or not math.isfinite(t0) or not math.isfinite(t1) or not 0 <= t0 <= t1:
                    raise ValueError('Transcription is missing valid speaker tags or timestamps.')
                if words and t0 < words[-1].start:
                    raise ValueError('Transcription timestamps are out of order.')
                words.append(Word(text, a.speaker, t0, t1))
    if not words:
        raise ValueError('No speech with speaker tags was returned.')
    return words


def render(words):
    turns = []
    previous = None
    for word in words:
        if word.speaker != previous:
            turns.append(f'{word.speaker}: {word.text}')
            previous = word.speaker
        else:
            turns[-1] += ' ' + word.text
    return '\n'.join(turns)


def stitch(chunks):
    labels = {}
    def label(speaker):
        return labels.setdefault(speaker, f'Speaker {len(labels)+1}')
    a = [replace(w, speaker=label(w.speaker)) for w in chunks[0]]
    if len(chunks) == 1:
        return render(a), []
    b = [replace(w, start=w.start+1740, end=w.end+1740) for w in chunks[1]]
    left = [(i, w) for i, w in enumerate(a) if w.start >= 1740]
    right = [(i, w) for i, w in enumerate(b) if w.start < 1800]
    normalize = lambda w: re.sub(r'[^\w]', '', w.text.casefold())
    matcher = SequenceMatcher(None, [normalize(w) for _, w in left],
                              [normalize(w) for _, w in right], autojunk=False)
    pairs = []
    for match in matcher.get_matching_blocks():
        if match.size >= 3:
            pairs.extend((left[match.a+k], right[match.b+k]) for k in range(match.size)
                         if normalize(left[match.a+k][1])
                         and abs(left[match.a+k][1].start-right[match.b+k][1].start) <= 10)
    votes = defaultdict(Counter)
    for (_, wa), (_, wb) in pairs:
        votes[wb.speaker][wa.speaker] += 1
    candidates = {}
    for speaker, counts in votes.items():
        ranked = counts.most_common()
        target, score = ranked[0]
        if score >= 5 and score / sum(counts.values()) >= .7 and (len(ranked) == 1 or score > ranked[1][1]):
            candidates[speaker] = target
    targets = Counter(candidates.values())
    mapping = {s: t for s, t in candidates.items() if targets[t] == 1}
    warnings = []
    next_label = len(labels) + 1
    for speaker in dict.fromkeys(w.speaker for w in b):
        if speaker not in mapping:
            mapping[speaker] = f'Speaker {next_label}'
            next_label += 1
            warnings.append(f'Unmatched speaker in chunk 2 assigned {mapping[speaker]}; review the identity.')
    b = [replace(w, speaker=mapping[w.speaker]) for w in b]
    if len(pairs) >= 5:
        (ia, _), (ib, _) = min(pairs, key=lambda p: abs(p[0][1].start-1770))
        combined = a[:ia] + b[ib:]
    else:
        combined = [w for w in a if w.start < 1770] + [w for w in b if w.start >= 1770]
        warnings.append('Uncertain overlap alignment: joined at 29:30. Review for missing or repeated words.')
    return render(combined), warnings


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class AudioPipeline:
    def __init__(self, key, cache, sdk=None):
        self.client = GeminiTranscriber(key, sdk)
        self.cache = Path(cache)

    def transcribe_segment(self, path, state_path, warnings):
        sdk = self.client.client()
        name = 'files/' + uuid.uuid4().hex
        save_json(state_path, {'remote': name})
        try:
            uploaded = sdk.files.upload(file=str(path), config={'mime_type': 'audio/wav', 'name': name})
            name = uploaded.name
            save_json(state_path, {'remote': name})
            deadline = time.monotonic()+300
            while str(getattr(uploaded.state, 'value', uploaded.state)).upper() == 'PROCESSING':
                if time.monotonic() > deadline:
                    raise ValueError('Audio upload processing timed out.')
                time.sleep(1)
                uploaded = sdk.files.get(name=name)
            if str(getattr(uploaded.state, 'value', uploaded.state)).upper() not in ('ACTIVE', 'NONE'):
                raise ValueError('Audio upload processing failed.')
            response = sdk.interactions.create(model=AUDIO_MODEL,
                input=[{'type': 'audio', 'uri': uploaded.uri, 'mime_type': 'audio/wav'}], store=False,
                generation_config={'transcription_config': {'mode': {'type': 'verbatim',
                    'diarization_mode': 'speaker', 'timestamp_granularities': ['word']}}},
                automatic_continuation=False, timeout=1800)
            if getattr(response.status, 'value', response.status) != 'completed':
                raise ValueError('Transcription did not complete; existing text was preserved.')
            return parse_words(response)
        finally:
            try:
                self.client.delete(name)
                save_json(state_path, {'remote': None})
            except Exception:
                warnings.append('Remote audio cleanup is pending; retry BABABUI to attempt cleanup again.')

    def run(self, path, progress=lambda message: None):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        progress('Validating WAV...')
        duration = media.probe(path)
        plan = segments(duration)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        directory = self.cache / AUDIO_MODEL / 'overlap-v1' / digest
        with file_lock(directory / 'cache.lock'):
            return self._run_locked(path, plan, directory, progress)

    def _run_locked(self, path, plan, directory, progress):
        state_path = directory / 'state.json'
        warnings, chunks = [], []
        if state_path.exists():
            remote = json.loads(state_path.read_text(encoding='utf-8')).get('remote')
            if remote:
                try:
                    self.client.delete(remote)
                    save_json(state_path, {'remote': None})
                except Exception:
                    warnings.append('Remote audio cleanup remains pending. Cached transcription can still be used.')
        for i, (start, end) in enumerate(plan):
            progress(f'Transcribing chunk {i+1} of {len(plan)}...')
            cached = directory / f'chunk-{i}.json'
            if cached.exists():
                words = [Word(**w) for w in json.loads(cached.read_text(encoding='utf-8'))]
            else:
                # Do not replace the pending-upload record with another upload.
                if state_path.exists():
                    remote = json.loads(state_path.read_text(encoding='utf-8')).get('remote')
                    if remote:
                        self.client.delete(remote)
                        save_json(state_path, {'remote': None})
                with tempfile.TemporaryDirectory(prefix='bababui-audio-') as temporary:
                    prepared = Path(temporary) / 'segment.wav'
                    media.prepare(path, {'start': start, 'end': end}, prepared)
                    words = self.transcribe_segment(prepared, state_path, warnings)
                save_json(cached, [asdict(w) for w in words])
            chunks.append(words)
        progress('Matching speakers and joining transcript...')
        text, stitch_warnings = stitch(chunks)
        if not text.strip():
            raise ValueError('Transcription returned no usable text.')
        return text, warnings + stitch_warnings
