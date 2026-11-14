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

from shared import media
from shared.transcription import GeminiTranscriber
from shared.storage import file_lock


AUDIO_MODEL = 'gemini-3.5-transcribe'


@dataclass(frozen=True)
class Word:
    text: str
    speaker: str
    start: float | None
    end: float | None


@dataclass(frozen=True)
class Transcription:
    text: str
    words: tuple[Word, ...]
    warnings: tuple[str, ...]
    duration_ms: int
    wav_sha256: str


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
                    t0 = t1 = math.nan
                if not (math.isfinite(t0) and math.isfinite(t1) and 0 <= t0 <= t1):
                    t0 = t1 = None
                if not a.speaker:
                    raise ValueError('Transcription is missing speaker tags.')
                # Overlapping turns can run backward. Preserve text order and
                # let the alignment choose timestamps that agree with it.
                words.append(Word(text, a.speaker, t0, t1))
    if not words:
        raise ValueError('No speech with speaker tags was returned.')
    return words


def _check_wav(path, digest):
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError('The WAV changed during transcription. Run BABABUI again.')


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


def _seam_positions(words, default):
    """Use adjacent times to place untimed text at a chunk seam."""
    first = next((word.start for word in words if word.start is not None), default)
    for word in words:
        if word.start is not None:
            first = word.start
        yield first


def stitch(chunks):
    labels = {}
    def label(speaker):
        return labels.setdefault(speaker, f'Speaker {len(labels)+1}')
    a = [replace(w, speaker=label(w.speaker)) for w in chunks[0]]
    if len(chunks) == 1:
        return tuple(a), []
    b = [replace(w, start=w.start+1740, end=w.end+1740) if w.start is not None else w
         for w in chunks[1]]
    left = [(i, w) for i, w in enumerate(a) if w.start is not None and w.start >= 1740]
    right = [(i, w) for i, w in enumerate(b) if w.start is not None and w.start < 1800]
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
        combined = [w for w, t in zip(a, _seam_positions(a, 0)) if t < 1770]
        combined.extend(w for w, t in zip(b, _seam_positions(b, 1770)) if t >= 1770)
        warnings.append('Uncertain overlap alignment: joined at 29:30. Review for missing or repeated words.')
    return tuple(combined), warnings


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class AudioPipeline:
    def __init__(self, key, cache, sdk=None, *, testing=False):
        self.client = GeminiTranscriber(key, sdk)
        self.cache = Path(cache)
        self.testing = testing

    def transcribe_segment(self, path):
        sdk = self.client.client()
        uploaded = sdk.files.upload(file=str(path), config={'mime_type': 'audio/wav'})
        deadline = time.monotonic()+300
        while str(getattr(uploaded.state, 'value', uploaded.state)).upper() == 'PROCESSING':
            if time.monotonic() > deadline:
                raise ValueError('Audio upload processing timed out.')
            time.sleep(1)
            uploaded = sdk.files.get(name=uploaded.name)
        if str(getattr(uploaded.state, 'value', uploaded.state)).upper() not in ('ACTIVE', 'NONE'):
            raise ValueError('Audio upload processing failed.')
        response = sdk.interactions.create(model=AUDIO_MODEL,
            input=[{'type': 'audio', 'uri': uploaded.uri, 'mime_type': 'audio/wav'}], store=False,
            generation_config={'transcription_config': {'mode': {'type': 'verbatim',
                'diarization_mode': 'speaker', 'timestamp_granularities': ['word']}}},
            automatic_continuation=False, timeout=1800)
        if self.testing:
            # Preserve the response before validation, including malformed timestamps.
            debug_dir = Path(tempfile.gettempdir()) / 'bababui-transcriptions'
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / f'response-{time.time_ns()}.json'
            payload = response.model_dump(mode='json') if hasattr(response, 'model_dump') else vars(response)
            debug_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=vars),
                                  encoding='utf-8')
            debug_path.with_suffix('.txt').write_text('\n'.join(
                block.text
                for step in getattr(response, 'steps', None) or []
                if getattr(step, 'type', None) == 'model_output'
                for block in getattr(step, 'content', None) or []
                if getattr(block, 'type', None) == 'text'), encoding='utf-8')
        if getattr(response.status, 'value', response.status) != 'completed':
            raise ValueError('Transcription did not complete; existing text was preserved.')
        return parse_words(response)

    def run(self, path, progress=lambda message: None):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        progress('Validating WAV...')
        duration = media.probe(path)
        plan = segments(duration)
        directory = self.cache / AUDIO_MODEL / 'overlap-v1' / digest
        with file_lock(directory / 'cache.lock'):
            return self._run_locked(path, plan, directory, progress, digest)

    def _run_locked(self, path, plan, directory, progress, digest):
        chunks = []
        for i, (start, end) in enumerate(plan):
            progress(f'Transcribing chunk {i+1} of {len(plan)}...')
            cached = directory / f'chunk-{i}.json'
            if cached.exists():
                words = [Word(**w) for w in json.loads(cached.read_text(encoding='utf-8'))]
            else:
                with tempfile.TemporaryDirectory(prefix='bababui-audio-') as temporary:
                    prepared = Path(temporary) / 'segment.wav'
                    media.prepare(path, {'start': start, 'end': end}, prepared)
                    words = self.transcribe_segment(prepared)
                _check_wav(path, digest)
                save_json(cached, [asdict(w) for w in words])
            chunks.append([w if (w.start is not None and w.end is not None
                                 and 0 <= w.start <= w.end <= end - start)
                           else replace(w, start=None, end=None) for w in words])
        progress('Matching speakers and joining transcript...')
        words, warnings = stitch(chunks)
        text = render(words)
        if not text.strip():
            raise ValueError('Transcription returned no usable text.')
        _check_wav(path, digest)
        return Transcription(text, words, tuple(warnings), int(plan[-1][1] * 1000), digest)
