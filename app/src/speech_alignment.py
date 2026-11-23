"""Align editable passages to timestamped speech without changing native records."""
from bisect import bisect_left, bisect_right
from functools import cached_property
from weakref import WeakKeyDictionary
from dataclasses import dataclass, replace
from hashlib import file_digest
from itertools import groupby
import math
from pathlib import Path
import re
from statistics import median

from app.src.suggestion_filter import LABEL


UNAVAILABLE = 'Too little timestamped speech matched the imported text to align this transcription.'
NO_TIMESTAMPS = 'The transcription had no usable word timestamps for audio alignment.'
WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
QA = re.compile(r'^[ \t]*[QA](?:\s{2,}|[.:][ \t]+)')
SHA256 = re.compile(r'[0-9a-f]{64}')
WAV_CHANGED = 'Audio alignment cleared because the WAV changed or is unavailable.'
MATCH_WINDOW_MS = 15000


def _tokens(text, offset=0):
    for match in WORD.finditer(text, offset):
        yield match.start(), match.group().casefold().replace('’', '').replace("'", '')


def _passages(revision):
    """Return normalized words with their displayed starts and source stroke references."""
    span_ends, refs, position = [], [], 0
    for span in revision.spans:
        if span.content:
            position += len(span.content)
            span_ends.append(position)
            refs.append(max(span.stroke_refs, default=None))

    positions, keys, strokes = [], [], []
    position = 0
    for line in revision.text.splitlines(keepends=True):
        label = LABEL.match(line) or QA.match(line)
        for index, (start, key) in enumerate(_tokens(line, label.end() if label else 0)):
            strokes.append(refs[bisect_right(span_ends, position + start)])
            positions.append(position + (start if index else 0))
            keys.append(key)
        position += len(line)
    if positions:
        positions[0] = 0
    return positions, keys, strokes


def _unique_phrases(keys):
    positions = {}
    for index, phrase in enumerate(zip(keys, keys[1:], keys[2:])):
        if len(set(phrase)) > 1:
            positions[phrase] = None if phrase in positions else index
    return positions


def _increasing(values, *, allow_equal=False):
    """Indices of the longest ordered subsequence, discarding conflicting points."""
    tails, ends, previous = [], [], []
    search = bisect_right if allow_equal else bisect_left
    for index, value in enumerate(values):
        length = search(tails, value)
        previous.append(ends[length - 1] if length else -1)
        if length == len(tails):
            tails.append(value)
            ends.append(index)
        elif value < tails[length]:
            tails[length], ends[length] = value, index
    ordered = []
    index = ends[-1] if ends else -1
    while index >= 0:
        ordered.append(index)
        index = previous[index]
    return reversed(ordered)


def _matching_pairs(keys, audio_phrases, audio_times, expected, *, learn_offset=False, playback_duration=None):
    matches = {}
    for phrase, text_index in _unique_phrases(keys).items():
        audio_index = audio_phrases.get(phrase)
        if text_index is None or audio_index is None:
            continue
        for offset in range(3):
            i, j = text_index + offset, audio_index + offset
            matches[i] = j if matches.get(i, j) == j else None
    pairs = [(i, j) for i, j in sorted(matches.items()) if j is not None and audio_times[j] is not None]
    # A distinctive phrase can still occur in the wrong place when the audio
    # and reporter omit different passages. Use the stroke clock as context.
    # The center and spread come from the candidate offsets on the first pass.
    offsets = [expected[i] - audio_times[j] for i, j in pairs if expected[i] is not None]
    center = median(offsets) if learn_offset and offsets else 0
    spread = median(abs(offset - center) for offset in offsets) if learn_offset and offsets else 0
    window = max(MATCH_WINDOW_MS, 6 * spread)
    matched = {i for i, j in pairs if expected[i] is None
               or abs(expected[i] - audio_times[j] - center) <= window}
    if playback_duration is not None and len(matched) < len(pairs):
        bounds = _shared_stroke_bounds(expected, playback_duration, matched)
        matched.update(i for i, j in pairs if i in bounds and bounds[i][0] <= audio_times[j] <= bounds[i][1])
    pairs = [(i, j) for i, j in pairs if i in matched]
    ordered = [pairs[k] for k in _increasing([j for _, j in pairs])]
    return [ordered[k] for k in _increasing([audio_times[j] for _, j in ordered], allow_equal=True)]


def _matches(keys, audio_phrases, audio_times, expected, *, learn_offset=False, playback_duration=None):
    pairs = _matching_pairs(keys, audio_phrases, audio_times, expected,
                            learn_offset=learn_offset, playback_duration=playback_duration)
    return {i: audio_times[j] for i, j in pairs}


def recover_word_times(words, observations):
    """Copy measured times from matching phrases onto the original transcription."""
    if not observations:
        return words

    def keys(items):
        return [''.join(key for _, key in _tokens(word.text)) for word in items]

    # A cached untimed annotation can contain an entire speaker turn.
    recovered = [replace(w, text=token) for w in words for token in w.text.split()]
    times = [round(w.start * 1000) if w.start is not None else None for w in observations]
    pairs = _matching_pairs(keys(recovered), _unique_phrases(keys(observations)), times, [None] * len(recovered))
    for i, j in pairs:
        observed = observations[j]
        recovered[i] = replace(recovered[i], start=observed.start, end=observed.end)
    return recovered if pairs else words


def _lerp(left, right, fraction):
    return round(left + fraction * (right - left))


def _between(raw, start, stop, left, right):
    """Use original spacing where available, filling gaps in the original clock by position."""
    low, high = raw[start], raw[stop]
    if low is None or high is None or high <= low:
        return [_lerp(left, right, (i - start) / (stop - start)) for i in range(start + 1, stop)]
    points = [(start, left)]
    for i in range(start + 1, stop):
        if raw[i] is not None:
            time = _lerp(left, right, (raw[i] - low) / (high - low))
            points.append((i, max(points[-1][1], min(right, time))))
    points.append((stop, right))
    times = []
    for (begin, a), (end, b) in zip(points, points[1:]):
        times.extend(_lerp(a, b, (i - begin) / (end - begin)) for i in range(begin + 1, end + 1))
    return times[:-1]


def _timeline(raw, anchors, duration):
    if not anchors:
        # Retain corrected source passage times when none of this revision's
        # wording is recognizable. Copied source associations can move backward.
        known = [(i, time) for i, time in enumerate(raw) if time is not None]
        anchors = dict(known[k] for k in _increasing([time for _, time in known], allow_equal=True))
    if not anchors:
        return (0,) * len(raw)

    points = list(anchors.items())
    first, left = points[0]
    last, right = points[-1]
    times = [left] * len(raw)
    for i in range(first - 1, -1, -1):
        if raw[i] is not None and raw[first] is not None:
            times[i] = max(0, min(times[i + 1], left + raw[i] - raw[first]))
        else:
            times[i] = times[i + 1]
    for (start, a), (stop, b) in zip(points, points[1:]):
        times[start + 1:stop] = _between(raw, start, stop, a, b)
        times[stop] = b
    for i in range(last + 1, len(raw)):
        if raw[i] is not None and raw[last] is not None:
            times[i] = min(duration, max(times[i - 1], right + raw[i] - raw[last]))
        else:
            times[i] = times[i - 1]
    return tuple(times)


@dataclass(frozen=True)
class SpeechAlignment:
    wav_sha256: str
    duration_ms: int
    stroke_ms: tuple[int, ...]
    words: tuple[tuple[str, int | None], ...]

    @classmethod
    def restore(cls, record, stroke_count):
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ValueError('Invalid saved speech alignment.')
        digest, duration, strokes, words = (record.get(key) for key in
            ('wav_sha256', 'duration_ms', 'stroke_ms', 'words'))
        if (not isinstance(digest, str) or not SHA256.fullmatch(digest)
                or type(duration) is not int or duration <= 0):
            raise ValueError('Invalid saved speech alignment.')

        def valid(time):
            return type(time) is int and 0 <= time <= duration

        if (not isinstance(strokes, (list, tuple)) or len(strokes) not in (0, stroke_count)
                or any(not valid(t) for t in strokes)
                or any(a > b for a, b in zip(strokes, strokes[1:]))
                or not isinstance(words, (list, tuple)) or not words
                or any(not isinstance(w, (list, tuple)) or len(w) != 2 or not isinstance(w[0], str)
                       or (w[1] is not None and not valid(w[1])) for w in words)):
            raise ValueError('Invalid saved speech alignment.')
        return cls(digest, duration, tuple(strokes), tuple(tuple(w) for w in words))

    def playback(self):
        return SpeechPlayback(self)

    def matches_wav(self, path):
        if path:
            try:
                with Path(path).open('rb') as stream:
                    return file_digest(stream, 'sha256').hexdigest() == self.wav_sha256
            except OSError:
                pass
        return False

    def export_strokes(self, revision):
        """Use the final wording at the source groups CaseCAT actually serializes."""
        if not self.stroke_ms:
            return ()
        _, keys, refs = _passages(revision)
        matches = _matches(keys, _unique_phrases([key for key, _ in self.words]),
                           [time for _, time in self.words], _at_strokes(refs, self.stroke_ms))
        anchors = _stroke_anchors(refs, matches)
        if len(set(anchors.values())) < 2:
            return self.stroke_ms
        return _timeline(self.stroke_ms, anchors, self.duration_ms)


def _at_strokes(refs, times):
    return [times[ref] if times and ref is not None else None for ref in refs]


def _shared_stroke_bounds(times, duration, matched):
    """Find the recording interval for words that share one stroke time."""
    bounds = {}
    start = 0
    for time, group in groupby(times):
        end = start + sum(1 for _ in group)
        # An isolated phrase from elsewhere in the recording is insufficient.
        bracketed = start - 1 in matched and end in matched
        if time is not None and end - start > 1 and (bracketed or not matched.isdisjoint(range(start, end))):
            before = times[start - 1] if start else 0
            after = times[end] if end < len(times) else duration
            interval = (min(before, time) if before is not None else time,
                        max(after, time) if after is not None else time)
            bounds.update(dict.fromkeys(range(start, end), interval))
        start = end
    return bounds


def _stroke_anchors(refs, matches):
    by_stroke = {}
    for i, time in matches.items():
        if refs[i] is not None:
            by_stroke.setdefault(refs[i], time)
    pairs = sorted(by_stroke.items())
    return dict(pairs[i] for i in _increasing([time for _, time in pairs], allow_equal=True))


def align_speech(revision, native_times, words, duration_ms, wav_sha256):
    audio = []
    for word in words:
        time = None
        if (word.start is not None and word.end is not None and math.isfinite(word.start)
                and math.isfinite(word.end) and 0 <= word.start <= word.end <= duration_ms / 1000):
            time = round(word.start * 1000)
        audio.extend((key, time) for _, key in _tokens(word.text))

    if not any(time is not None for _, time in audio):
        # No speech correction means playback and export use the CaseCAT stroke timing.
        return None

    _, keys, refs = _passages(revision)
    matches = _matches(keys, _unique_phrases([key for key, _ in audio]),
                       [time for _, time in audio], _at_strokes(refs, native_times), learn_offset=True)
    # A short match in a long job is weak evidence for retiming the entire job.
    if len(matches) < max(3, math.ceil(len(keys) / 10)) or len(set(matches.values())) < 2:
        return None
    anchors = _stroke_anchors(refs, matches)
    # Spoken words can cover a whole passage even if it has only one stroke.
    stroke_ms = _timeline(native_times, anchors, duration_ms) if len(set(anchors.values())) >= 2 else ()
    return SpeechAlignment(wav_sha256, duration_ms, stroke_ms, tuple(audio))


@dataclass(frozen=True)
class _WordTimes:
    """Small immutable blocks share all unchanged word timings across undo snapshots."""
    blocks: tuple  # (text origin, relative word starts, absolute audio times)
    length: int

    @staticmethod
    def blocks_of(positions, times):
        for i in range(0, len(positions), 256):
            origin = positions[i]
            yield origin, tuple(p-origin for p in positions[i:i+256]), tuple(times[i:i+256])

    @cached_property
    def starts(self):
        return tuple(origin for origin, _, _ in self.blocks)

    @cached_property
    def first_times(self):
        return tuple(times[0] for _, _, times in self.blocks)

    def at_position(self, position):
        i = bisect_right(self.starts, position)-1
        if i >= 0:
            origin, starts, times = self.blocks[i]
            return times[bisect_right(starts, position-origin)-1]
        return None

    def at_time(self, time):
        i = bisect_right(self.first_times, time)-1
        if i < 0:
            return None
        origin, starts, times = self.blocks[i]
        j = bisect_right(times, time)-1
        stop = self.starts[i+1] if i+1 < len(self.blocks) else self.length
        return origin+starts[j], origin+starts[j+1] if j+1 < len(starts) else stop

    def replace(self, start, end, positions, times, delta):
        # Repack the two boundary blocks. Shift the origins of later blocks
        # without copying their word arrays or retaining the previous revision.
        first = max(0, bisect_right(self.starts, start)-1)
        stop = bisect_right(self.starts, end)
        left, right = [], []
        for origin, starts, clocks in self.blocks[first:stop]:
            a, b = bisect_left(starts, start-origin), bisect_left(starts, end-origin)
            left.extend((origin+p, t) for p, t in zip(starts[:a], clocks[:a]))
            right.extend((origin+p+delta, t) for p, t in zip(starts[b:], clocks[b:]))
        middle = [*left, *zip(positions, times), *right]
        starts, clocks = zip(*middle) if middle else ((), ())
        suffix = ((origin+delta, p, t) for origin, p, t in self.blocks[stop:])
        return _WordTimes((*self.blocks[:first], *self.blocks_of(starts, clocks), *suffix), self.length+delta)

    @cached_property
    def ranges(self):
        words = [(origin+p, t) for origin, starts, clocks in self.blocks for p, t in zip(starts, clocks)]
        return tuple((a, b, t) for (a, t), (b, _) in zip(words, [*words[1:], (self.length, 0)]))


def _nearby_words(revision, start, stop):
    """Tokenize the affected paragraphs, retaining actual and displayed starts."""
    result = []
    for line in revision.text[start:stop].splitlines(keepends=True):
        label = LABEL.match(line) or QA.match(line)
        for index, (pos, key) in enumerate(_tokens(line, label.end() if label else 0)):
            actual = start+pos
            span = revision.spans[bisect_right(revision._span_ends, actual)]
            result.append((actual if index else start, actual, key, max(span.stroke_refs, default=None)))
        start += len(line)
    return result


class SpeechPlayback:
    """Project the speech map onto the current revision, including edits and undo."""
    def __init__(self, alignment):
        self.alignment = alignment
        self._phrases = _unique_phrases([key for key, _ in alignment.words])
        self._times = [time for _, time in alignment.words]

    def _cached(self, revision):
        return revision.__dict__.get('_speech_indexes', {}).get(self)

    def _remember(self, revision, index):
        # Keep the projection as long as its revision and WAV are alive. Using
        # the playback object as key avoids hashing every span of a revision.
        revision.__dict__.setdefault('_speech_indexes', WeakKeyDictionary())[self] = index
        return index

    def _index(self, revision):
        cached = self._cached(revision)
        if cached is not None:
            return cached
        positions, keys, refs = _passages(revision)
        raw = _at_strokes(refs, self.alignment.stroke_ms)
        matches = _matches(keys, self._phrases, self._times, raw,
                           playback_duration=self.alignment.duration_ms)
        if not keys and self.alignment.stroke_ms:
            position = 0
            for span in revision.spans:
                if span.content:
                    positions.append(position)
                    ref = max(span.stroke_refs, default=None)
                    raw.append(self.alignment.stroke_ms[ref] if ref is not None else None)
                    position += len(span.content)
        if not matches and all(time is None for time in raw):
            positions, raw = [], []
        times = _timeline(raw, matches, self.alignment.duration_ms)
        return self._remember(revision, _WordTimes(tuple(_WordTimes.blocks_of(positions, times)), len(revision.text)))

    def track_edit(self, before, after, start, end, replacement):
        """Update a warm speech index for one exact contiguous native edit."""
        previous = self._cached(before)
        if previous is None or not previous.blocks or before is after or self._cached(after) is not None:
            return
        if not 0 <= start <= end <= len(before.text) or before.text[:start]+replacement+before.text[end:] != after.text:
            return  # A linked fill can change several separated occurrences.
        delta = len(replacement)-(end-start)
        # Include neighboring paragraphs for the measured three-word phrases,
        # and parse speaker / Q/A labels from genuine paragraph boundaries.
        lo = before.text.rfind('\n', 0, start)+1
        boundary = before.text.find('\n', end)
        hi = len(before.text) if boundary < 0 else boundary+1
        for _ in range(2):
            lo = before.text.rfind('\n', 0, max(lo-1, 0))+1
            boundary = before.text.find('\n', hi)
            hi = len(before.text) if boundary < 0 else boundary+1
        old = _nearby_words(before, lo, hi)
        new = _nearby_words(after, lo, hi+delta)
        old_times = {p: (key, previous.at_position(display)) for display, p, key, _ in old}
        fixed, amended = {}, {}
        for i, (_, p, key, _) in enumerate(new):
            old_position = p-delta if p >= start+len(replacement) else p
            if old_position in old_times:
                old_key, time = old_times[old_position]
                if time is None:
                    continue
                if key == old_key and (p < start or p >= start+len(replacement)):
                    fixed[i] = time
                elif p <= start and old_position == p:
                    amended[i] = time
        positions = [display for display, _, _, _ in new]
        if positions and not lo:
            positions[0] = 0
        raw = _at_strokes([ref for _, _, _, ref in new], self.alignment.stroke_ms)
        measured = _matches([key for _, _, key, _ in new], self._phrases, self._times, raw,
                            playback_duration=self.alignment.duration_ms)
        lower = previous.at_position(lo-1) if lo else None
        upper = previous.at_position(hi) if hi < len(before.text) else None
        # A newly recognizable word gets its recording time. A partial word
        # being typed keeps the previous word's passage until then.
        for candidates in (measured, amended):
            retained = sorted(fixed)
            for i, time in candidates.items():
                j = bisect_left(retained, i)
                left = fixed[retained[j-1]] if j else lower
                right = fixed[retained[j]] if j < len(retained) else upper
                if i not in fixed and (left is None or time >= left) and (right is None or time <= right):
                    fixed[i] = time
        if not positions and not lo and hi == len(before.text):
            return  # Let the native punctuation-only stroke fallback handle this revision.
        if positions and not fixed and all(t is None for t in raw):
            # New, unmeasured words stay at the previously audible passage.
            fixed[0] = previous.at_position(start) or 0
        times = _timeline(raw, dict(sorted(fixed.items())), self.alignment.duration_ms)
        times = [max(lower or 0, min(t, upper if upper is not None else self.alignment.duration_ms)) for t in times]
        self._remember(after, previous.replace(lo, hi, positions, times, delta))

    def ranges(self, revision):
        return self._index(revision).ranges

    def position_ms(self, revision, position):
        if not 0 <= position <= len(revision.text):
            raise ValueError('Playback position exceeds the transcript.')
        return self._index(revision).at_position(position)

    def range_at(self, revision, milliseconds):
        return self._index(revision).at_time(milliseconds)
