"""WAV transcription and timestamp-aware, best-effort speaker stitching."""
from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, replace
from difflib import SequenceMatcher
import hashlib
from itertools import chain, count
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from app.src.speech_alignment import recover_word_times
from app.src.transcription_output import OutputError, SegmentOutput
from app.src.vocabulary_reconciliation import normalized_vocabulary, reconcile_vocabulary
from shared import media
from shared.transcription import GeminiTranscriber
from shared.storage import atomic_bytes, atomic_copy, file_lock


AUDIO_MODEL = 'gemini-3.5-transcribe'
CHUNK_SECONDS = 30 * 60
OVERLAP_SECONDS = 60
OVERLAP_DRIFT_SECONDS = 10
CHUNK_STEP = CHUNK_SECONDS - OVERLAP_SECONDS
MAX_DURATION = CHUNK_SECONDS + 3 * CHUNK_STEP
VOCABULARY_SECONDS = 60 * 60
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


def parse_words(response, *, timestamps=True, partial=False):
    words = []
    for step in getattr(response, 'steps', None) or []:
        if getattr(step, 'type', None) != 'model_output':
            continue
        for block in getattr(step, 'content', None) or []:
            if getattr(block, 'type', None) != 'text':
                continue
            if not isinstance(getattr(block, 'text', None), str):
                if partial:
                    continue
                raise ValueError('Invalid transcription text block.')
            raw = block.text.encode('utf-8')
            annotations = [a for a in (getattr(block, 'annotations', None) or [])
                           if getattr(a, 'type', None) == 'word_info']
            if raw.strip() and not annotations:
                words.extend(Word(token, None, None, None) for token in block.text.split())
            for i, a in enumerate(annotations):
                start, end = getattr(a, 'start_index', None), getattr(a, 'end_index', None)
                try:
                    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(raw):
                        raise ValueError('Invalid transcription word offsets.')
                    if i and start < annotations[i-1].end_index:
                        raise ValueError('Transcription word offsets are out of order.')
                    if partial:
                        raw[start:end].decode('utf-8')
                except ValueError:
                    if not partial:
                        raise
                    annotations = annotations[:i]
                    break
            if partial and annotations:
                # A truncated text block can end with an unannotated word fragment.
                raw = raw[:annotations[-1].end_index]
            for i, a in enumerate(annotations):
                # Include punctuation between annotations, using the original UTF-8 text.
                next_start = annotations[i+1].start_index if i+1 < len(annotations) else len(raw)
                begin = 0 if i == 0 else a.start_index
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
    if not words and not partial:
        raise ValueError('No speech was returned.')
    return words


def wav_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_wav_digest(path, digest, message='The WAV changed during transcription. Run BABABUI again.'):
    if wav_sha256(path) != digest:
        raise ValueError(message)


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
    kept, warnings = _stitched_chunks(chunks)
    return tuple(chain.from_iterable(kept)), warnings


def _number_speakers(words):
    speakers = dict.fromkeys(w.speaker for w in words if w.speaker is not None)
    labels = {speaker: f'Speaker {i}' for i, speaker in enumerate(speakers, 1)}
    return [replace(w, speaker=labels[w.speaker]) if w.speaker is not None else w for w in words], labels


def _shift_words(words, offset):
    return [replace(w, start=w.start + offset, end=w.end + offset) if w.start is not None else w
            for w in words]


def _bounded_words(words, duration):
    return [w if w.start is not None and w.end is not None and 0 <= w.start <= w.end <= duration
            else replace(w, start=None, end=None) for w in words]


@dataclass
class _OverlapReview:
    # These labels are local to the join until recording-wide stitching finishes.
    unmatched: list[str] = field(default_factory=list)
    cut: float | None = None
    untimed: bool = False

    def warnings(self, chunk_number, *, labels=None, offset=0):
        speakers = self.unmatched if labels is None else [labels[s] for s in self.unmatched if s in labels]
        warnings = [f'Unmatched speaker in chunk {chunk_number} assigned {s}; review the identity.'
                    for s in speakers]
        if self.cut is not None:
            minutes, seconds = divmod(int(offset + self.cut), 60)
            warnings.append(f'Uncertain overlap alignment: joined at {minutes}:{seconds:02d}. Review for missing or repeated words.')
        if self.untimed:
            warnings.append('Could not match the overlap without timestamps. Both chunks were kept. Review for repeated words.')
        return warnings


class _ResumedWords(list[Word]):
    """A segment word list with review notes for its internal join."""
    def __init__(self, words, review):
        super().__init__(words)
        self.review = review


def _stitched_chunks(chunks, continuation_reviews=()):
    tail, labels = _number_speakers(chunks[0])
    next_label = count(len(labels) + 1)
    combined = []
    warnings = continuation_reviews[0].warnings(1, labels=labels) if continuation_reviews else []
    for index, chunk in enumerate(chunks[1:], 1):
        start = index * CHUNK_STEP
        incoming = _shift_words(chunk, start)
        # Only the previous chunk participates in the next overlap.
        review = _OverlapReview()
        kept, tail, labels = _join_overlap(tail, incoming, start, start + OVERLAP_SECONDS, next_label, review)
        combined.append(kept)
        warnings.extend(review.warnings(index + 1))
        if continuation_reviews:
            warnings.extend(continuation_reviews[index].warnings(index + 1, labels=labels, offset=start))
    combined.append(tail)
    return combined, list(dict.fromkeys(warnings))


def _word_key(word):
    return re.sub(r'[^\w]', '', word.text.casefold())


def _join_overlap(a, b, start, end, next_label, review):
    midpoint = (start + end) / 2
    a_timed = any(w.start is not None for w in a)
    left = [(i, w) for i, w in enumerate(a) if w.start is not None and start <= w.start < end]
    right = [(i, w) for i, w in enumerate(b) if w.start is not None and start <= w.start < end]
    # Later timed words cannot locate an untimed opening turn in the shared minute.
    b_timed = bool(right) or bool(b and b[0].start is not None)
    # Search near the edge of an untimed chunk for the repeated minute.
    if not a_timed:
        left = list(enumerate(a[-400:], max(0, len(a) - 400)))
    if not b_timed:
        for i, w in enumerate(b[:400]):
            if w.start is not None:
                break
            right.append((i, w))
    left_text = [_word_key(w) for _, w in left]
    right_text = [_word_key(w) for _, w in right]
    matcher = SequenceMatcher(None, left_text, right_text, autojunk=False)
    pairs = []
    if a_timed and b_timed:
        for match in matcher.get_matching_blocks():
            if match.size >= 3:
                pairs.extend((left[match.a+k], right[match.b+k]) for k in range(match.size)
                             if left_text[match.a+k]
                             and abs(left[match.a+k][1].start-right[match.b+k][1].start) <= OVERLAP_DRIFT_SECONDS)
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
    for speaker in dict.fromkeys(w.speaker for w in b):
        if speaker is not None and speaker not in mapping:
            mapping[speaker] = f'Speaker {next(next_label)}'
            review.unmatched.append(mapping[speaker])
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
        return a[:ia], b[ib:], mapping
    if not (a_timed and b_timed):
        review.untimed = True
        return a, b, mapping
    if not left or not right:
        # Only one recording of the words in the overlap. A midpoint cut would lose them.
        review.cut = end if not right else start
        return a, b, mapping
    a = [w for w, t in zip(a, _seam_positions(a, start)) if t < midpoint]
    b = [w for w, t in zip(b, _seam_positions(b, midpoint)) if t >= midpoint]
    review.cut = midpoint
    return a, b, mapping


def _merge_continuation(prefix, resumed, start):
    cutoff = prefix[-1].end
    later = {i for i, w in enumerate(resumed) if w.end is not None and w.end > cutoff and _word_key(w)}
    if not later:
        return None
    if all(resumed[i].start <= cutoff + OVERLAP_DRIFT_SECONDS for i in later):
        # A slightly later timestamp on a repeated word is not evidence of new speech.
        overlap = [w for w in prefix if w.start is not None and w.end >= start]
        matcher = SequenceMatcher(None, [_word_key(w) for w in overlap], [_word_key(w) for w in resumed],
                                  autojunk=False)
        for a, b, size in matcher.get_matching_blocks():
            for k in range(size):
                i = b + k
                if i in later and abs(overlap[a + k].start - resumed[i].start) <= OVERLAP_DRIFT_SECONDS:
                    later.remove(i)
        if not later:
            return None

    numbered, labels = _number_speakers(prefix)
    review = _OverlapReview()
    kept, tail, _ = _join_overlap(numbered, resumed, start, cutoff, count(len(labels) + 1), review)
    if review.untimed:
        return None  # The complete speaker-only pass can resolve ambiguous repeated wording.
    return _ResumedWords(chain(kept, tail), review)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class AudioPipeline:
    def __init__(self, key, cache, sdk=None, *, output=None, legacy_cache=None, cache_mode='reuse'):
        # Interactions retries 429 internally even with attempts=1 unless it is excluded.
        self.client = GeminiTranscriber(key, sdk, retry_options={
            'attempts': 1, 'http_status_codes': [408, 409, 500, 502, 503, 504]})
        self.cache = Path(cache)
        self.legacy_cache = Path(legacy_cache) if legacy_cache else None
        self.cache_mode = cache_mode
        self.output = output

    def _upload(self, path):
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
        return uploaded.uri

    def _request(self, uri, config, progress, segment, kind='response'):
        sdk = self.client.client()
        for attempt in range(2):
            try:
                raw = sdk.interactions.with_raw_response.create(model=AUDIO_MODEL,
                    input=[{'type': 'audio', 'uri': uri, 'mime_type': 'audio/wav'}], store=True,
                    generation_config={'max_output_tokens': 16384, 'transcription_config': config},
                    automatic_continuation=False, timeout=1800)
                break
            except Exception as exc:
                status_code = getattr(exc, 'status_code', getattr(exc, 'code', None))
                error_response = getattr(exc, 'response', None)
                if segment and error_response is not None:
                    segment.response(f'{kind} - HTTP {status_code} attempt {attempt+1}', error_response.text)
                if status_code != 429 or attempt:
                    raise
                progress('Transcription rate limit reached (429). Waiting 60 seconds before retrying this chunk...')
                time.sleep(60)
                progress('Retrying transcription for this chunk...')
        if segment is not None:
            segment.response(f'{kind} (retry)' if attempt else kind, raw.text())
        response = raw.parse()
        status = getattr(response.status, 'value', response.status)
        if status not in ('completed', 'incomplete'):
            raise ValueError('Transcription did not complete; existing text was preserved.')
        return status, response

    def transcribe_segment(self, path, progress=lambda message: None, *, timing_only=False, vocabulary=(), segment=None):
        uri = self._upload(path)
        speaker = {'type': 'verbatim', 'diarization_mode': 'speaker'}
        timed_config = {'mode': {**speaker, 'timestamp_granularities': ['word']}}
        config = {'mode': {'type': 'verbatim'}, 'custom_vocabulary': list(vocabulary)} if vocabulary else timed_config
        status, response = self._request(uri, config, progress, segment)
        if status == 'completed':
            try:
                return parse_words(response, timestamps=not vocabulary)
            except ValueError:
                if timing_only:
                    return []  # A short clip can be silent or have unusable annotations.
                raise
        if timing_only:
            return []
        if vocabulary:
            raise ValueError('Transcription did not complete; existing text was preserved.')

        prefix = parse_words(response, partial=True)
        resumed = []
        if any(w.start is not None for w in prefix):
            duration = media.probe(path)
            prefix = _bounded_words(prefix, duration)
            while prefix and prefix[-1].end is None:
                prefix.pop()
            if prefix and OVERLAP_SECONDS < prefix[-1].end < duration:
                cutoff = prefix[-1].end
                start = cutoff - OVERLAP_SECONDS
                progress('Resuming incomplete transcription with one minute of overlap...')
                complete, resumed = self._continue_segment(path, start, duration, timed_config, progress, segment)
                if complete:
                    merged = _merge_continuation(prefix, resumed, start)
                    if merged is not None:
                        return merged

        progress('Retrying the full chunk with speaker labels only...')
        status, fallback = self._request(uri, {'mode': speaker}, progress, segment, 'speaker fallback response')
        if status != 'completed':
            raise ValueError('Transcription did not complete; existing text was preserved.')
        words = parse_words(fallback, timestamps=False)
        # Keep the first measurement where both requests timed the same wording.
        return recover_word_times(recover_word_times(words, resumed), prefix)

    def _continue_segment(self, path, start, duration, config, progress, segment):
        try:
            with tempfile.TemporaryDirectory(prefix='bababui-audio-') as temporary:
                clip = Path(temporary) / 'continuation.wav'
                media.prepare(path, {'start': start, 'end': duration}, clip)
                status, response = self._request(self._upload(clip), config, progress, segment, 'continuation response')
        except OutputError:
            raise
        except Exception:
            # The original upload is still available for the full-chunk fallback.
            return False, []
        try:
            words = parse_words(response, partial=status == 'incomplete')
        except ValueError:
            # A malformed tail disqualifies the join but earlier timings can still support the fallback.
            status = 'incomplete'
            words = parse_words(response, partial=True)
        return status == 'completed', _shift_words(_bounded_words(words, duration - start), start)

    def run(self, path, progress=lambda message: None, *, vocabulary=(), expected_digest=None):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() != '.wav':
            raise ValueError('Choose an existing .wav file.')
        digest = wav_sha256(path)
        if expected_digest is not None and expected_digest != digest:
            raise ValueError('The WAV changed before processing. Run BABABUI again.')
        progress('Validating WAV...')
        duration = media.probe(path)
        plan = segments(duration)
        directory = self._recording_directory(digest)
        vocabulary = normalized_vocabulary(vocabulary)
        with file_lock(directory / 'cache.lock'):
            if self.cache_mode == 'clean':
                progress('Clearing cached files for this recording...')
                self._clear_recording_cache(directory, vocabulary)
            return self._run_locked(path, plan, directory, progress, digest, vocabulary)

    def _recording_directory(self, digest):
        return self.cache / AUDIO_MODEL / 'overlap-v1' / digest

    @staticmethod
    def _vocabulary_key(digest, vocabulary):
        return hashlib.sha256(json.dumps((digest, vocabulary), ensure_ascii=False).encode('utf-8')).hexdigest()

    def _clear_vocabulary_cache(self, key):
        for root in (self.cache, self.legacy_cache):
            if root is not None:
                directory = root / AUDIO_MODEL / 'vocabulary-v1' / key
                if directory.exists():
                    self._remove_cache_path(root, directory)

    @staticmethod
    def _vocabulary_keys(directory):
        path = directory / 'vocabulary-keys.txt'
        if not path.exists():
            return set()
        keys = set(path.read_text(encoding='ascii').splitlines())
        if any(not re.fullmatch('[0-9a-f]{64}', key) for key in keys):
            raise ValueError('Invalid vocabulary cache index for this recording.')
        return keys

    @staticmethod
    def _remove_cache_path(root, path):
        # Only remove entries under the intended cache, including on Windows junctions.
        relative = path.relative_to(root)
        if path.resolve() != root.resolve() / relative:
            raise ValueError('The recording cache points outside its expected directory.')
        if path.is_symlink() or not path.is_dir():
            path.unlink()
        else:
            shutil.rmtree(path)

    def _clear_recording_cache(self, directory, vocabulary):
        relative = directory.relative_to(self.cache)
        old = self.legacy_cache / relative if self.legacy_cache else None
        roots = [self.cache]
        legacy_lock = nullcontext()
        if old and old.is_dir() and old.resolve() != directory.resolve():
            roots.append(self.legacy_cache)
            legacy_lock = file_lock(old / 'cache.lock')
        with legacy_lock:
            keys = {self._vocabulary_key(directory.name, vocabulary)} if vocabulary else set()
            for root in roots:
                keys.update(self._vocabulary_keys(root / relative))
            for key in keys:
                self._clear_vocabulary_cache(key)
            # Older vocabulary directories have opaque keys and no recording ID.
            # Discard any unindexed variant when its names next identify it.
            (directory / 'clean-start').touch()
            for root in roots:
                for entry in (root / relative).iterdir():
                    if entry.name not in ('cache.lock', 'clean-start'):
                        self._remove_cache_path(root, entry)

    def _segment_words(self, path, start, end, cached, progress, digest, *, label, timing_only=False, vocabulary=(),
                       continuation_reviews=None):
        review = _OverlapReview()
        review_path = cached.with_name('review-' + cached.name)
        reuse = self.cache_mode in ('reuse', 'saved')
        if (reuse and self.legacy_cache and not cached.exists()
                and not (self._recording_directory(digest) / 'clean-start').exists()):
            old = self.legacy_cache / cached.relative_to(self.cache)
            if old.is_file():
                for sidecar in (old.with_name(review_path.name), old.with_suffix('.responses')):
                    if sidecar.is_file():
                        atomic_copy(sidecar, cached.with_name(sidecar.name))
                atomic_copy(old, cached)
        segment = SegmentOutput(self.output, label)
        cache_hit = reuse and cached.exists()
        if cache_hit:
            segment.restore_responses(cached)
            words = [Word(**w) for w in json.loads(cached.read_text(encoding='utf-8'))]
            if continuation_reviews is not None and review_path.exists():
                review = _OverlapReview(**json.loads(review_path.read_text(encoding='utf-8')))
        elif self.cache_mode == 'saved':
            if timing_only:
                return None
            raise ValueError('No saved transcription is available for this recording. Select Transcription to create one.')
        else:
            with tempfile.TemporaryDirectory(prefix='bababui-audio-') as temporary:
                prepared = Path(temporary) / 'segment.wav'
                media.prepare(path, {'start': start, 'end': end}, prepared)
                if timing_only:
                    try:
                        words = self.transcribe_segment(prepared, progress, timing_only=True, segment=segment)
                    except OutputError:
                        raise
                    except Exception:
                        # A failed optional API call must leave the completed transcript usable.
                        progress('Word timing request failed. Keeping the completed transcription.')
                        return None
                elif vocabulary:
                    words = self.transcribe_segment(prepared, progress, vocabulary=vocabulary, segment=segment)
                else:
                    words = self.transcribe_segment(prepared, progress, segment=segment)
                    if isinstance(words, _ResumedWords):
                        review = words.review
            check_wav_digest(path, digest)
        words = _bounded_words(words, end - start)
        usable = not timing_only or any(w.start is not None for w in words)
        if not cache_hit and usable:
            # The word list marks a complete entry. A refresh must not leave
            # old words paired with new sidecars if publishing is interrupted.
            if self.cache_mode == 'refresh':
                cached.unlink(missing_ok=True)
            if continuation_reviews is not None:
                # Publish review information before the word list marks this chunk complete.
                if review.unmatched or review.cut is not None:
                    save_json(review_path, asdict(review))
                else:
                    review_path.unlink(missing_ok=True)
            segment.cache_responses(cached)
            save_json(cached, [asdict(w) for w in words])
        if self.output and (cache_hit or usable):
            self.output.copy(f' - {label}.json', cached)
        if continuation_reviews is not None:
            continuation_reviews.append(review)
        return words

    def _recover_timing(self, path, start, end, words, directory, progress, digest):
        observations = []
        step = min(TIMING_CLIP_SECONDS, math.ceil((end - start) / 2))
        for offset in range(0, math.ceil(end - start), step):
            clip_start, clip_end = start + offset, min(start + offset + step, end)
            cached = directory / 'word-timing' / f'{clip_start}-{clip_end}.json'
            clip = self._segment_words(path, clip_start, clip_end, cached, progress, digest, timing_only=True,
                                       label=f'timing clip {clip_start:g}-{clip_end:g}s')
            if clip is None:
                break
            observations.extend(_shift_words(clip, offset))
        return recover_word_times(words, observations)

    def _vocabulary_windows(self, path, duration, progress, digest, vocabulary):
        key = self._vocabulary_key(digest, vocabulary)
        recording = self._recording_directory(digest)
        keys = self._vocabulary_keys(recording)
        if key not in keys:
            if (recording / 'clean-start').exists():
                self._clear_vocabulary_cache(key)
            keys.add(key)
            atomic_bytes(recording / 'vocabulary-keys.txt', '\n'.join(sorted(keys)).encode('ascii'))
        directory = self.cache / AUDIO_MODEL / 'vocabulary-v1' / key
        plan = segments(duration, vocabulary=True)
        windows, warnings = [], []
        for i, (start, end) in enumerate(plan, 1):
            progress(f'Transcribing vocabulary window {i} of {len(plan)}...')
            try:
                words = self._segment_words(path, start, end, directory / f'window-{i}.json',
                                            progress, digest, vocabulary=vocabulary, label=f'vocabulary window {i}')
            except OutputError:
                raise
            except Exception:
                check_wav_digest(path, digest)
                warning = f'Vocabulary window {i} of {len(plan)} failed. Kept the speaker transcription for this window.'
                progress(warning)
                warnings.append(warning)
                continue
            windows.append((start, end, ' '.join(w.text for w in words)))
        return windows, warnings

    def _run_locked(self, path, plan, directory, progress, digest, vocabulary):
        chunks, timing_warnings, continuation_reviews = [], [], []
        for i, (start, end) in enumerate(plan):
            progress(f'Transcribing speaker and timing chunk {i+1} of {len(plan)}...')
            words = self._segment_words(path, start, end, directory / f'chunk-{i}.json', progress, digest,
                                        label=f'chunk {i+1}', continuation_reviews=continuation_reviews)
            if not any(w.start is not None for w in words):
                progress(f'Recovering word timestamps for chunk {i+1} from shorter audio clips...')
                words = self._recover_timing(path, start, end, words, directory, progress, digest)
            chunks.append(words)
            if not any(w.start is not None for w in words):
                timing_warnings.append(f'No word timestamps for chunk {i+1}.')
        progress('Matching speakers and joining transcript...')
        retained, warnings = _stitched_chunks(chunks, continuation_reviews)
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
        return Transcription(text, words, tuple(timing_warnings + warnings), int(plan[-1][1] * 1000), digest)
