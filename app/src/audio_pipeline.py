"""WAV transcription and timestamp-aware, best-effort speaker stitching."""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from difflib import SequenceMatcher
import hashlib
from itertools import chain, count
import json
import math
from pathlib import Path
import re
import tempfile
import time

from app.src.speech_alignment import recover_word_times
from app.src.vocabulary_reconciliation import normalized_vocabulary, reconcile_vocabulary
from shared import media
from shared.transcription import GeminiTranscriber
from shared.storage import file_lock


AUDIO_MODEL = 'gemini-3.5-transcribe'
CHUNK_SECONDS = 30 * 60
OVERLAP_SECONDS = 60
CHUNK_STEP = CHUNK_SECONDS - OVERLAP_SECONDS
MAX_DURATION = CHUNK_SECONDS + 3 * CHUNK_STEP
VOCABULARY_SECONDS = 60 * 60
TIMING_CLIP_SECONDS = 5 * 60
# A chunk with no words for this long, right after steady speech (this many
# words in the five minutes before), may have stopped or skipped ahead.
TAIL_GAP_SECONDS = 45
FIRST, PROVISIONAL = 'first chunk', 'provisional'
RECOVERED = 'Speaker R'  # a voice in a recovery clip that matched none of the chunk's own
# Matching a chunk's speaker to the previous chunk needs 5 shared words, or at
# least this many exact words: the same word at the same moment of the WAV.
MIN_EXACT_WORDS = 2
EXACT_SECONDS = 1.0
TAIL_SPEECH_WORDS = 50
MAX_REFILLS = 4
# Words that announce a pause, so silence after them is expected.
PAUSE_CUES = re.compile(r"\boff\s+(?:of\s+)?(?:the\s+)?record\b|\brecess\b|\bbreak\b|\bconcluded\b|"
                        r"\badjourn", re.I)


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
    # How each job-wide speaker label was established: {label: {"chunk", "status",
    # "suggested", "evidence"}}. A provisional label waits for the voice check.
    identities: dict = field(default_factory=dict, hash=False, compare=False)


def segments(duration, *, vocabulary=False):
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
        raise ValueError('Choose a WAV recording longer than 0 seconds and at most 1 hour 57 minutes.')
    length = VOCABULARY_SECONDS if vocabulary else CHUNK_SECONDS
    plan = []
    start = 0
    while True:
        end = min(start + length, duration)
        plan.append((start, end))
        if end == duration:
            return plan
        start = end - OVERLAP_SECONDS


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


def check_wav_digest(path, digest):
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
    kept, warnings, _ = _stitched_chunks(chunks)
    return tuple(chain.from_iterable(kept)), warnings


def stitch_identities(chunks):
    """Stitched words, warnings, and how each job-wide speaker label was established."""
    kept, warnings, identities = _stitched_chunks(chunks)
    return tuple(chain.from_iterable(kept)), warnings, identities


def _stitched_chunks(chunks):
    """Join chunks into one transcript with job-wide speaker labels.

    Chunk 1's speakers get Speaker 1, 2, ... in order of appearance. Each later
    chunk is matched against the previous chunk's job-wide labels in their
    shared minute, so chunk 3 maps to the labels chunk 2 already resolved. A
    speaker who does not speak in a shared minute gets a new, provisional label.
    """
    speakers = dict.fromkeys(w.speaker for w in chunks[0] if w.speaker is not None)
    labels = {speaker: f'Speaker {i}' for i, speaker in enumerate(speakers, 1)}
    identities = {label: {'chunk': 1, 'status': PROVISIONAL if str(speaker).startswith(RECOVERED) else FIRST,
                          'suggested': None, 'evidence': ''}
                  for speaker, label in labels.items()}
    next_label = count(len(labels) + 1)
    tail = [replace(w, speaker=labels[w.speaker]) if w.speaker is not None else w for w in chunks[0]]
    combined, warnings = [], []
    for index, chunk in enumerate(chunks[1:], 1):
        start = index * CHUNK_STEP
        incoming = [replace(w, start=w.start+start, end=w.end+start) if w.start is not None else w
                    for w in chunk]
        # Only the previous chunk participates in the next overlap.
        kept, tail, seam_warnings = _join_overlap(tail, incoming, index + 1, start, next_label, identities)
        combined.append(kept)
        warnings.extend(seam_warnings)
    combined.append(tail)
    return combined, warnings, identities


def _join_overlap(a, b, chunk_number, start, next_label, identities=None):
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
    votes, exact = defaultdict(Counter), defaultdict(Counter)
    for (_, wa), (_, wb) in pairs:
        if wa.speaker is not None and wb.speaker is not None:
            votes[wb.speaker][wa.speaker] += 1
            # The same word at the same moment of the WAV in both chunks.
            if (a_timed and b_timed and normalize(wa) and normalize(wa) == normalize(wb)
                    and abs(wa.start - wb.start) <= EXACT_SECONDS):
                exact[wb.speaker][wa.speaker] += 1
    candidates, hints = [], {}
    for speaker, counts in votes.items():
        ranked = counts.most_common()
        target, score = ranked[0]
        if score >= 5 and score / sum(counts.values()) >= .7 and (len(ranked) == 1 or score > ranked[1][1]):
            candidates.append((score, speaker, target))
        elif len(ranked) == 1 and len(exact[speaker]) == 1 and exact[speaker][target] >= MIN_EXACT_WORDS:
            # A short utterance in the overlap, such as "Okay. Now," before a new
            # question: every shared word is the same word at the same time, all
            # with one speaker on each side. Gemini heard the same voice.
            candidates.append((exact[speaker][target], speaker, target))
        elif len(ranked) == 1 and exact[speaker][target]:
            # One shared word, such as "Yes.", suggests a match for the voice check to confirm.
            hints[speaker] = target
    # One speaker per label, strongest evidence first: when Gemini merged two
    # voices under one label in the earlier chunk, only the better match maps.
    mapping, taken = {}, set()
    for score, speaker, target in sorted(candidates, key=lambda c: -c[0]):
        if target not in taken:
            mapping[speaker] = target
            taken.add(target)
    warnings = []
    for speaker in dict.fromkeys(w.speaker for w in b):
        if speaker is not None and speaker not in mapping:
            # Never matched by elimination: a voice that does not speak in the
            # shared minute may be a participant returning from an earlier chunk,
            # or a new one. The identity check compares its voice later.
            label = mapping[speaker] = f'Speaker {next(next_label)}'
            warnings.append(f'Unmatched speaker in chunk {chunk_number} assigned {label}; review the identity.')
            if identities is not None:
                hint = hints.get(speaker)
                identities[label] = {
                    'chunk': chunk_number, 'status': PROVISIONAL,
                    'suggested': hint if hint not in taken else None,
                    'evidence': (f'one word in the shared minute matched {hint}' if hint and hint not in taken else
                                 f'did not speak in the minute shared with chunk {chunk_number - 1}')}
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
    # Cut at the overlap's midpoint, unless one chunk has no words there: when the
    # earlier chunk stops before the midpoint, the later chunk is kept from where
    # it stopped, and when the later chunk starts after it, the earlier one is kept
    # up to that start. A midpoint cut would then drop words neither chunk repeats.
    # Start times only: Gemini sometimes gives a word an end time far past its start.
    a_end = max(w.start for w in a if w.start is not None)
    b_start = min(w.start for w in b if w.start is not None)
    a_cut = b_cut = midpoint
    if a_end < midpoint:
        a_cut, b_cut = math.inf, a_end
    elif b_start > midpoint:
        a_cut, b_cut = b_start, -math.inf
    a = [w for w, t in zip(a, _seam_positions(a, start)) if t < a_cut]
    b = [w for w, t in zip(b, _seam_positions(b, midpoint)) if t >= b_cut]
    joined = midpoint if a_cut == b_cut else (a_end if a_cut == math.inf else b_start)
    warnings.append(f'Uncertain overlap alignment: joined at {clock(joined)}. Review for missing or repeated words.')
    if a_end < start:
        warnings.append(f'No words were transcribed between {clock(a_end)} and {clock(start)}. '
                        'Check the audio there for missing testimony.')
    return a, b, warnings


def _gaps(words, length):
    """(last, resume) for each long silence after steady speech; resume is None at the chunk's end."""
    timed = [(w.start, i) for i, w in enumerate(words) if w.start is not None]
    times = [t for t, _ in timed]
    found = []
    for k, (t, i) in enumerate(timed):
        following = times[k + 1] if k + 1 < len(times) else None
        if (following if following is not None else length) - t <= TAIL_GAP_SECONDS:
            continue
        if sum(t - 300 <= x <= t for x in times) < TAIL_SPEECH_WORDS:
            continue  # Speech had already thinned out: a pause, not a transcript that stopped.
        if PAUSE_CUES.search(' '.join(w.text for w in words[max(0, i - 19):i + 1])):
            continue  # Announced: going off the record, a recess or a break.
        found.append((t, following))
    return found


def clock(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class AudioPipeline:
    def __init__(self, key, cache, sdk=None, *, testing=False):
        # Interactions retries 429 internally even with attempts=1 unless it is excluded.
        self.client = GeminiTranscriber(key, sdk, retry_options={
            'attempts': 1, 'http_status_codes': [408, 409, 500, 502, 503, 504]})
        self.cache = Path(cache)
        self.testing = testing

    def transcribe_segment(self, path, progress=lambda message: None, *, timing_only=False, vocabulary=()):
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
        if vocabulary:
            configs = [{'mode': {'type': 'verbatim'}, 'custom_vocabulary': list(vocabulary)}]
        else:
            speaker = {'type': 'verbatim', 'diarization_mode': 'speaker'}
            configs = [{'mode': {**speaker, 'timestamp_granularities': ['word']}}]
            if not timing_only:
                configs.append({'mode': speaker})
        for config in configs:
            for attempt in range(2):
                try:
                    response = sdk.interactions.create(model=AUDIO_MODEL,
                        input=[{'type': 'audio', 'uri': uploaded.uri, 'mime_type': 'audio/wav'}], store=False,
                        generation_config={'max_output_tokens': 16384, 'transcription_config': config},
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
                    return parse_words(response, timestamps='timestamp_granularities' in config['mode'])
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

    def run(self, path, progress=lambda message: None, *, vocabulary=()):
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
            return self._run_locked(path, plan, directory, progress, digest, normalized_vocabulary(vocabulary))

    def _segment_words(self, path, start, end, cached, progress, digest, *, timing_only=False, vocabulary=()):
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
                elif vocabulary:
                    words = self.transcribe_segment(prepared, progress, vocabulary=vocabulary)
                else:
                    words = self.transcribe_segment(prepared, progress)
            check_wav_digest(path, digest)
        words = [w if (w.start is not None and w.end is not None and 0 <= w.start <= w.end <= end - start)
                 else replace(w, start=None, end=None) for w in words]
        if not cached.exists() and (not timing_only or any(w.start is not None for w in words)):
            save_json(cached, [asdict(w) for w in words])
        return words

    def _fill_gaps(self, path, start, end, words, directory, progress, digest, index):
        """Words for a chunk whose transcript stopped, or skipped ahead, in steady speech.

        Gemini sometimes stops a chunk's transcript early, or jumps over part of
        it. A stretch of more than TAIL_GAP_SECONDS with no words, right after
        steady speech, is transcribed again from a minute before it, joined to the
        words before it like a chunk overlap, and cut where the chunk's own words
        resume. A pause announced as going off the record or a break is left alone.
        Each request is cached with the chunk.
        """
        warnings = []
        for last, resume in _gaps(words, end - start)[:MAX_REFILLS]:
            words, notes = self._refill(path, start, end, words, last, resume, directory, progress, digest, index)
            warnings.extend(notes)
        return words, warnings

    def _refill(self, path, start, end, words, last, resume, directory, progress, digest, index):
        tail = resume is None
        resume_at = end - start if tail else resume
        what = (f'Chunk {index + 1} of the transcription stopped at {clock(start + last)}' if tail else
                f'Chunk {index + 1} of the transcription skipped from {clock(start + last)} to {clock(start + resume)}')
        progress(f'{what}. Transcribing the rest of that chunk...' if tail else f'{what}. Transcribing that part again...')
        offset = max(0, math.floor(last) - OVERLAP_SECONDS)
        stop = end - start if tail else min(end - start, math.ceil(resume) + OVERLAP_SECONDS)
        cached = directory / f'chunk-{index}-rest-{offset}.json'
        try:
            again = self._segment_words(path, start + offset, start + stop, cached, progress, digest)
        except Exception:  # noqa: BLE001 - keep the completed transcript
            if tail:
                return words, [f'{what}, {clock(end - start - last)} before its end, and the rest could not be '
                               f'transcribed. Words may be missing between {clock(start + last)} and {clock(end)}.']
            return words, [f'{what}, and that part could not be transcribed. Words may be missing there.']
        # Separate speaker names until the overlap matches them to the chunk's own.
        again = [replace(w, speaker=f'{w.speaker} (rest)' if w.speaker is not None else None,
                         start=w.start + offset if w.start is not None else None,
                         end=w.end + offset if w.end is not None else None) for w in again]
        if not any(w.start is not None and last < w.start < resume_at for w in again):
            return words, []  # Nothing more was said there.
        # The chunk's own words resume after the gap: keep them, and only the new words before them.
        split = len(words) if tail else next(i for i, w in enumerate(words) if w.start is not None and w.start >= resume)
        before, after = words[:split], words[split:]
        kept, again, seam = _join_overlap(before, again, index + 1, offset, (f'R{n}' for n in count(1)))
        again = [w for w in again if w.start is None or w.start < resume_at]
        notes = [f'{what}, {clock(end - start - last)} before its end. The rest of the chunk was transcribed '
                 'again; review that part.' if tail else f'{what}. That part was transcribed again; review it.']
        if any(w.startswith('Unmatched speaker') for w in seam):
            notes.append(f'Some speakers transcribed again in chunk {index + 1} could not be matched; '
                         'review the identity.')
        if any(w.startswith('Uncertain') for w in seam):
            notes.append(f'The part of chunk {index + 1} transcribed again could not be lined up word for word. '
                         f'Review for repeated words near {clock(start + offset + OVERLAP_SECONDS // 2)}.')
        return [*kept, *again, *after], notes

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

    def _vocabulary_windows(self, path, duration, progress, digest, vocabulary):
        key = hashlib.sha256(json.dumps((digest, vocabulary), ensure_ascii=False).encode('utf-8')).hexdigest()
        directory = self.cache / AUDIO_MODEL / 'vocabulary-v1' / key
        plan = segments(duration, vocabulary=True)
        windows, warnings = [], []
        for i, (start, end) in enumerate(plan, 1):
            progress(f'Transcribing vocabulary window {i} of {len(plan)}...')
            try:
                words = self._segment_words(path, start, end, directory / f'window-{i}.json',
                                            progress, digest, vocabulary=vocabulary)
            except Exception:
                check_wav_digest(path, digest)
                warning = f'Vocabulary window {i} of {len(plan)} failed. Kept the speaker transcription for this window.'
                progress(warning)
                warnings.append(warning)
                continue
            windows.append((start, end, ' '.join(w.text for w in words)))
        return windows, warnings

    def _run_locked(self, path, plan, directory, progress, digest, vocabulary):
        chunks, timing_warnings = [], []
        for i, (start, end) in enumerate(plan):
            progress(f'Transcribing speaker and timing chunk {i+1} of {len(plan)}...')
            words = self._segment_words(path, start, end, directory / f'chunk-{i}.json', progress, digest)
            if not any(w.start is not None for w in words):
                progress(f'Recovering word timestamps for chunk {i+1} from shorter audio clips...')
                words = self._recover_timing(path, start, end, words, directory, progress, digest)
            # A later chunk only repeats this one's last minute, so a chunk that stopped
            # early, or skipped ahead, would leave a gap. Transcribe that part again.
            words, refill_warnings = self._fill_gaps(path, start, end, words, directory, progress, digest, i)
            timing_warnings.extend(refill_warnings)
            chunks.append(words)
            if not any(w.start is not None for w in words):
                timing_warnings.append(f'No word timestamps for chunk {i+1}.')
        progress('Matching speakers and joining transcript...')
        retained, warnings, identities = _stitched_chunks(chunks)
        words = tuple(chain.from_iterable(retained))
        if vocabulary:
            windows, vocabulary_warnings = self._vocabulary_windows(path, plan[-1][1], progress, digest, vocabulary)
            warnings.extend(vocabulary_warnings)
            if windows:
                progress('Matching names and firms to the speaker transcription...')
                ranges = [interval for chunk, interval in zip(retained, plan) for _ in chunk]
                words = reconcile_vocabulary(words, ranges, windows, vocabulary)
        text = render(words)
        if not text.strip():
            raise ValueError('Transcription returned no usable text.')
        check_wav_digest(path, digest)
        return Transcription(text, words, tuple(timing_warnings + warnings), int(plan[-1][1] * 1000), digest,
                             identities)
