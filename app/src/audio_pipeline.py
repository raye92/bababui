"""WAV transcription and timestamp-aware, best-effort speaker stitching."""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
import hashlib
from itertools import count
import json
import math
from pathlib import Path
import re
import tempfile
import time

from app.src.speech_alignment import recover_word_times
from shared import media
from shared.transcription import GeminiTranscriber
from shared.storage import file_lock


AUDIO_MODEL = 'gemini-3.5-transcribe'
CHUNK_SECONDS = 30 * 60
OVERLAP_SECONDS = 60
CHUNK_STEP = CHUNK_SECONDS - OVERLAP_SECONDS
MAX_CHUNKS = 3
TIMING_CLIP_SECONDS = 5 * 60


@dataclass(frozen=True)
class Word:
    text: str
    speaker: str | None
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
    max_duration = CHUNK_SECONDS + (MAX_CHUNKS - 1) * CHUNK_STEP
    if not math.isfinite(duration) or not 0 < duration <= max_duration:
        raise ValueError('Choose a WAV recording longer than 0 seconds and at most 1 hour 28 minutes.')
    plan = []
    for index in range(MAX_CHUNKS):
        start = index * CHUNK_STEP
        end = min(start + CHUNK_SECONDS, duration)
        plan.append((start, end))
        if end == duration:
            break
    return plan


def parse_words(response, *, timestamps=True):
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
                words.extend(Word(token, None, None, None) for token in block.text.split())
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
                speaker = getattr(a, 'speaker', None) or None
                if not timestamps:
                    # Without timestamps, one annotation can cover an entire speaker turn.
                    words.extend(Word(token, speaker, None, None) for token in text.split())
                    continue
                try:
                    t0 = float(a.start_offset.removesuffix('s'))
                    t1 = float(a.end_offset.removesuffix('s'))
                except (AttributeError, TypeError, ValueError):
                    t0 = t1 = math.nan
                if not (math.isfinite(t0) and math.isfinite(t1) and 0 <= t0 <= t1):
                    t0 = t1 = None
                # Overlapping turns can run backward. Preserve text order and
                # let the alignment choose timestamps that agree with it.
                words.append(Word(text, speaker, t0, t1))
    if not words:
        raise ValueError('No speech was returned.')
    return words


def _check_wav(path, digest):
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError('The WAV changed during transcription. Run BABABUI again.')


def render(words):
    turns = []
    previous = None
    for word in words:
        if not turns or word.speaker != previous:
            turns.append(f'{word.speaker or "Unknown speaker"}: {word.text}')
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
    speakers = dict.fromkeys(w.speaker for w in chunks[0] if w.speaker is not None)
    labels = {speaker: f'Speaker {i}' for i, speaker in enumerate(speakers, 1)}
    next_label = count(len(labels) + 1)
    tail = [replace(w, speaker=labels[w.speaker]) if w.speaker is not None else w for w in chunks[0]]
    combined, warnings = [], []
    for index, chunk in enumerate(chunks[1:], 1):
        start = index * CHUNK_STEP
        incoming = [replace(w, start=w.start+start, end=w.end+start) if w.start is not None else w
                    for w in chunk]
        # Only the previous chunk participates in the next overlap.
        kept, tail, seam_warnings = _join_overlap(tail, incoming, index + 1, start, next_label)
        combined.extend(kept)
        warnings.extend(seam_warnings)
    combined.extend(tail)
    return tuple(combined), warnings


def _join_overlap(a, b, chunk_number, start, next_label):
    midpoint = start + OVERLAP_SECONDS // 2
    a_timed = any(w.start is not None for w in a)
    b_timed = any(w.start is not None for w in b)
    left = [(i, w) for i, w in enumerate(a) if w.start is not None and w.start >= start]
    right = [(i, w) for i, w in enumerate(b) if w.start is not None and w.start < start + OVERLAP_SECONDS]
    # Search near the edge of an untimed chunk for the repeated minute.
    if not a_timed:
        left = list(enumerate(a[-400:], max(0, len(a) - 400)))
    if not b_timed:
        right = list(enumerate(b[:400]))
    normalize = lambda w: re.sub(r'[^\w]', '', w.text.casefold())
    left_text = [normalize(w) for _, w in left]
    right_text = [normalize(w) for _, w in right]
    matcher = SequenceMatcher(None, left_text, right_text, autojunk=False)
    pairs = []
    if a_timed and b_timed:
        for match in matcher.get_matching_blocks():
            if match.size >= 3:
                pairs.extend((left[match.a+k], right[match.b+k]) for k in range(match.size)
                             if left_text[match.a+k]
                             and abs(left[match.a+k][1].start-right[match.b+k][1].start) <= 10)
    else:
        match = matcher.find_longest_match()
        tokens = left_text[match.a:match.a+match.size]
        phrase = ' ' + ' '.join(tokens) + ' '
        edges = [' ' + ' '.join(edge) + ' ' for edge in (left_text, right_text)]
        if match.size >= 8 and len(set(tokens) - {''}) >= 4 and all(
                edge.find(phrase) == edge.rfind(phrase) for edge in edges):
            pairs = [(left[match.a+k], right[match.b+k]) for k in range(match.size)]
    votes = defaultdict(Counter)
    for (_, wa), (_, wb) in pairs:
        if wa.speaker is not None and wb.speaker is not None:
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
    for speaker in dict.fromkeys(w.speaker for w in b):
        if speaker is not None and speaker not in mapping:
            mapping[speaker] = f'Speaker {next(next_label)}'
            warnings.append(f'Unmatched speaker in chunk {chunk_number} assigned {mapping[speaker]}; review the identity.')
    b = [replace(w, speaker=mapping[w.speaker]) if w.speaker is not None else w for w in b]
    if len(pairs) >= 5:
        if a_timed and b_timed:
            (ia, _), (ib, _) = min(pairs, key=lambda p: abs(p[0][1].start-midpoint))
        elif a_timed:
            (ia, _), (ib, _) = pairs[-1]
            ia += 1
            ib += 1
        else:
            (ia, _), (ib, _) = pairs[0]
        return a[:ia], b[ib:], warnings
    if not (a_timed and b_timed):
        warnings.append('Could not match the overlap without timestamps. Both chunks were kept. Review for repeated words.')
        return a, b, warnings
    a = [w for w, t in zip(a, _seam_positions(a, start)) if t < midpoint]
    b = [w for w, t in zip(b, _seam_positions(b, midpoint)) if t >= midpoint]
    minutes, seconds = divmod(midpoint, 60)
    warnings.append(f'Uncertain overlap alignment: joined at {minutes}:{seconds:02d}. Review for missing or repeated words.')
    return a, b, warnings


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

    def transcribe_segment(self, path, progress=lambda message: None, *, timing_only=False):
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
        for timestamps in ((True,) if timing_only else (True, False)):
            mode = {'type': 'verbatim', 'diarization_mode': 'speaker'}
            if timestamps:
                mode['timestamp_granularities'] = ['word']
            for attempt in range(2):
                try:
                    response = sdk.interactions.create(model=AUDIO_MODEL,
                        input=[{'type': 'audio', 'uri': uploaded.uri, 'mime_type': 'audio/wav'}], store=False,
                        generation_config={'max_output_tokens': 16384, 'transcription_config': {'mode': mode}},
                        automatic_continuation=False, timeout=1800)
                    break
                except Exception as exc:
                    status_code = getattr(exc, 'status_code', getattr(exc, 'code', None))
                    if status_code != 429 or attempt:
                        raise
                    progress('Transcription rate limit reached (429). Waiting 60 seconds before retrying this chunk...')
                    time.sleep(60)
                    progress('Retrying transcription for this chunk...')
            if self.testing:
                self._save_response(response)
            status = getattr(response.status, 'value', response.status)
            if status == 'completed':
                try:
                    return parse_words(response, timestamps=timestamps)
                except ValueError:
                    if timing_only:
                        return []  # A short clip can be silent or have unusable annotations.
                    raise
            if timing_only and status == 'incomplete':
                return []
            if status != 'incomplete':
                break
        raise ValueError('Transcription did not complete; existing text was preserved.')

    @staticmethod
    def _save_response(response):
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

    def _segment_words(self, path, start, end, cached, progress, digest, *, timing_only=False):
        if cached.exists():
            words = [Word(**w) for w in json.loads(cached.read_text(encoding='utf-8'))]
        else:
            with tempfile.TemporaryDirectory(prefix='bababui-audio-') as temporary:
                prepared = Path(temporary) / 'segment.wav'
                media.prepare(path, {'start': start, 'end': end}, prepared)
                if timing_only:
                    try:
                        words = self.transcribe_segment(prepared, progress, timing_only=True)
                    except Exception:
                        # A failed optional API call must leave the completed transcript usable.
                        progress('Word timing request failed. Keeping the completed transcription.')
                        return None
                else:
                    words = self.transcribe_segment(prepared, progress)
            _check_wav(path, digest)
        words = [w if (w.start is not None and w.end is not None and 0 <= w.start <= w.end <= end - start)
                 else replace(w, start=None, end=None) for w in words]
        if not cached.exists() and (not timing_only or any(w.start is not None for w in words)):
            save_json(cached, [asdict(w) for w in words])
        return words

    def _recover_timing(self, path, start, end, words, directory, progress, digest):
        observations = []
        step = min(TIMING_CLIP_SECONDS, math.ceil((end - start) / 2))
        for offset in range(0, math.ceil(end - start), step):
            clip_start, clip_end = start + offset, min(start + offset + step, end)
            cached = directory / 'word-timing' / f'{clip_start}-{clip_end}.json'
            clip = self._segment_words(path, clip_start, clip_end, cached, progress, digest, timing_only=True)
            if clip is None:
                break
            observations.extend(replace(w, start=w.start + offset, end=w.end + offset)
                                if w.start is not None else w for w in clip)
        return recover_word_times(words, observations)

    def _run_locked(self, path, plan, directory, progress, digest):
        chunks, timing_warnings = [], []
        for i, (start, end) in enumerate(plan):
            progress(f'Transcribing chunk {i+1} of {len(plan)}...')
            words = self._segment_words(path, start, end, directory / f'chunk-{i}.json', progress, digest)
            if not any(w.start is not None for w in words):
                progress(f'Recovering word timestamps for chunk {i+1} from shorter audio clips...')
                words = self._recover_timing(path, start, end, words, directory, progress, digest)
            chunks.append(words)
            if not any(w.start is not None for w in words):
                timing_warnings.append(f'No word timestamps for chunk {i+1}.')
        progress('Matching speakers and joining transcript...')
        words, warnings = stitch(chunks)
        text = render(words)
        if not text.strip():
            raise ValueError('Transcription returned no usable text.')
        _check_wav(path, digest)
        return Transcription(text, words, tuple(timing_warnings + warnings), int(plan[-1][1] * 1000), digest)
