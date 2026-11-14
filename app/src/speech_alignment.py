"""Align editable passages to timestamped speech without changing native records."""
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import file_digest
import math
from pathlib import Path
import re
from statistics import median

from app.src.suggestion_filter import LABEL


UNAVAILABLE = 'Audio alignment unavailable: too little speech matched the imported text.'
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


def _matches(keys, audio_phrases, audio_times, expected, *, learn_offset=False):
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
    pairs = [(i, j) for i, j in pairs if expected[i] is None
             or abs(expected[i] - audio_times[j] - center) <= window]
    ordered = [pairs[k] for k in _increasing([j for _, j in pairs])]
    return {ordered[k][0]: audio_times[ordered[k][1]]
            for k in _increasing([audio_times[j] for _, j in ordered], allow_equal=True)}


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

        if (not isinstance(strokes, (list, tuple)) or len(strokes) != stroke_count
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
        _, keys, refs = _passages(revision)
        matches = _matches(keys, _unique_phrases([key for key, _ in self.words]),
                           [time for _, time in self.words], _at_strokes(refs, self.stroke_ms))
        anchors = _stroke_anchors(refs, matches)
        if len(set(anchors.values())) < 2:
            return self.stroke_ms
        return _timeline(self.stroke_ms, anchors, self.duration_ms)


def _at_strokes(refs, times):
    return [times[ref] if ref is not None else None for ref in refs]


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

    _, keys, refs = _passages(revision)
    matches = _matches(keys, _unique_phrases([key for key, _ in audio]),
                       [time for _, time in audio], _at_strokes(refs, native_times), learn_offset=True)
    # A short match in a long job is weak evidence for retiming the entire job.
    if len(matches) < max(3, math.ceil(len(keys) / 10)):
        return None
    anchors = _stroke_anchors(refs, matches)
    if len(set(anchors.values())) < 2:
        return None
    return SpeechAlignment(wav_sha256, duration_ms, _timeline(native_times, anchors, duration_ms), tuple(audio))


class SpeechPlayback:
    """Project the speech map onto the current revision, including edits and undo."""
    def __init__(self, alignment):
        self.alignment = alignment
        self._phrases = _unique_phrases([key for key, _ in alignment.words])
        self._times = [time for _, time in alignment.words]
        self._cache = OrderedDict()

    def _index(self, revision):
        key = id(revision)
        if key not in self._cache:
            positions, keys, refs = _passages(revision)
            raw = _at_strokes(refs, self.alignment.stroke_ms)
            matches = _matches(keys, self._phrases, self._times, raw)
            if not keys:
                position = 0
                for span in revision.spans:
                    if span.content:
                        positions.append(position)
                        ref = max(span.stroke_refs, default=None)
                        raw.append(self.alignment.stroke_ms[ref] if ref is not None else None)
                        position += len(span.content)
            times = _timeline(raw, matches, self.alignment.duration_ms)
            ranges = tuple(zip(positions, [*positions[1:], len(revision.text)], times))
            self._cache[key] = revision, positions, times, ranges
            if len(self._cache) > 4:
                self._cache.popitem(last=False)
        self._cache.move_to_end(key)
        return self._cache[key]

    def ranges(self, revision):
        return self._index(revision)[3]

    def position_ms(self, revision, position):
        if not 0 <= position <= len(revision.text):
            raise ValueError('Playback position exceeds the transcript.')
        _, positions, times, _ = self._index(revision)
        i = bisect_right(positions, position) - 1
        return times[i] if i >= 0 else None

    def range_at(self, revision, milliseconds):
        _, _, times, ranges = self._index(revision)
        i = bisect_right(times, milliseconds) - 1
        return ranges[i][:2] if i >= 0 else None
