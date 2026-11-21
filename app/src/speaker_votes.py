"""Second-source checks for speaker attribution.

Gemini's speaker label alone never changes the reporter's label. When the AI
label disagrees with an existing label, the voice and the context each vote:

- keep: the voice or the context supports the reporter's label, and nothing
  else agrees with Gemini. No change is proposed.
- suggest: the voice or the context agrees with Gemini, and nothing supports
  the reporter's label.
- flag: anything else. The change stays reviewable as "Needs review".

Context votes use only reliable cues, such as an objection or a turn that
addresses counsel. Short courtesies such as "Thank you." never vote, because
anyone can say them. Voice votes compare the turn's median pitch with pitch
profiles built from this job's own paragraphs, and abstain when the two
speakers' voices are not clearly separated.
"""
import importlib.util
import re
import wave

KEEP, FLAG, SUGGEST = 'keep', 'flag', 'suggest'
DECISIONS = frozenset((KEEP, FLAG, SUGGEST))

ATTORNEY = re.compile(r'(?:MR|MS|MRS|MISS)\.\s', re.I)
WITNESS = 'the witness'
OBJECTION = re.compile(r'objection\b')
ADDRESSES_COUNSEL = re.compile(r'counsel\b\s*[,.]')
ADDRESSES_DOCTOR = re.compile(r'(?:doctor|dr\.)(?:\s+[\w\'-]+)?\s*,')
QA = re.compile(r'^[ \t]*([QA])(?:[ \t]+|$)')

# Voice thresholds, in semitones. Starting values; tune them on reviewed jobs.
MIN_SEPARATION = 3.0
MIN_VOICED_FRAMES = 8
PROFILE_TURNS = 24
MIN_PROFILE_TURNS = 4
PROFILE_SECONDS = (1.0, 4.0)
TURN_SECONDS = (0.25, 6.0)


def name_key(name):
    return ' '.join((name or '').split()).casefold()


def decide(current, proposed, *, voice=None, context=None):
    """Combine Gemini's dissent with the voice and context votes."""
    votes = [vote for vote in (voice, context) if vote]
    support = sum(name_key(vote) == name_key(current) for vote in votes)
    dissent = 1 + sum(name_key(vote) == name_key(proposed) for vote in votes)
    if support and dissent == 1:
        return KEEP
    if not support and dissent >= 2:
        return SUGGEST
    return FLAG


def is_attorney(name):
    return bool(ATTORNEY.match(name or ''))


def context_vote(body, current, proposed, examiner=None):
    """Return the name that the turn's opening words allow, or None."""
    text = (body or '').strip().casefold()
    if OBJECTION.match(text):
        allowed = lambda name: is_attorney(name) and name_key(name) != name_key(examiner)
    elif ADDRESSES_COUNSEL.match(text):
        allowed = is_attorney
    elif ADDRESSES_DOCTOR.match(text):
        allowed = lambda name: name_key(name) != WITNESS
    else:
        return None
    keep, change = allowed(current), allowed(proposed)
    if keep and not change:
        return current
    if change and not keep:
        return proposed
    return None


def speech_turns(paragraphs):
    """Name each speech paragraph from existing labels, BY lines and Q/A prefixes.

    `paragraphs` are suggestion_filter._paragraphs tuples. Returns
    {index: (name, body position)}; BY lines are not speech.
    """
    names = {name_key(p[2]['name']): p[2]['name'].strip() for p in paragraphs if p[2]}
    witness = names.get(WITNESS)
    turns, examiner = {}, None
    for index, (offset, line, label, _) in enumerate(paragraphs):
        if label:
            name = label['name'].strip()
            body = line[label.end():]
            if 'BY' in label['prefix'].upper() and not body.strip():
                examiner = None if name.upper().startswith('SPEAKER') else name
                continue
            if name.upper().startswith('SPEAKER') or not body.strip():
                continue
            turns[index] = (name, offset + label.end() + len(body) - len(body.lstrip()))
        elif (match := QA.match(line)) and line[match.end():].strip():
            name = examiner if match[1] == 'Q' else witness
            if name:
                turns[index] = (name, offset + match.end())
    return turns


def _read(path, start_ms, end_ms):
    """Return mono float samples resampled to 8 kHz, or None."""
    import numpy as np
    try:
        with wave.open(str(path), 'rb') as stream:
            rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
            total = stream.getnframes()
            a = max(0, int(start_ms * rate / 1000))
            b = min(total, int(end_ms * rate / 1000))
            if b <= a or stream.getcomptype() != 'NONE':
                return None
            stream.setpos(a)
            raw = stream.readframes(b - a)
    except (OSError, EOFError, wave.Error):
        return None
    if width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        x = np.frombuffer(raw, '<i2').astype(np.float32) / 32768
    elif width == 3:
        b3 = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b3[:, 0] | (b3[:, 1] << 8) | (b3[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float32) / (1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, '<i4').astype(np.float32) / (1 << 31)
    else:
        return None
    if channels > 1:
        x = x[:len(x) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate != 8000 and len(x):
        k = max(1, round(rate / 8000))
        if k > 1:
            x = np.convolve(x, np.ones(k, np.float32) / k, mode='same')
        x = np.interp(np.arange(0, len(x) * 8000 / rate) * rate / 8000, np.arange(len(x)), x).astype(np.float32)
    return x


def pitch_semitones(x, rate=8000, fmin=60.0, fmax=400.0, threshold=0.15):
    """YIN pitch per voiced 40 ms frame, 10 ms apart, in semitones above 55 Hz."""
    import numpy as np
    if x is None:
        return np.array([])
    frame, hop = int(rate * 0.04), int(rate * 0.01)
    tmin, tmax = int(rate / fmax), int(rate / fmin)
    if len(x) < frame + tmax + 1:
        return np.array([])
    starts = np.arange(0, len(x) - frame - tmax, hop)
    rms = np.sqrt(np.array([np.mean(x[s:s + frame] ** 2) for s in starts]))
    if not len(rms) or rms.max() < 3e-3:
        return np.array([])
    taus = np.arange(1, tmax + 1)
    result = []
    for s in starts[rms >= max(0.1 * rms.max(), 3e-3)]:
        segment = x[s:s + frame + tmax].astype(np.float64)
        window = segment[:frame]
        energy = np.concatenate(([0.0], np.cumsum(segment ** 2)))
        sliding = energy[taus + frame] - energy[taus]
        cross = np.correlate(segment, window, mode='valid')[1:tmax + 1]
        difference = np.maximum(np.sum(window ** 2) + sliding - 2 * cross, 0)
        normalized = difference * taus / np.maximum(np.cumsum(difference), 1e-12)
        below = np.nonzero(normalized[tmin - 1:] < threshold)[0]
        if not len(below):
            continue
        i = below[0] + tmin - 1
        while i + 1 < len(normalized) and normalized[i + 1] < normalized[i]:
            i += 1
        tau = float(taus[i])
        if 0 < i < len(normalized) - 1:
            a, b, c = normalized[i - 1], normalized[i], normalized[i + 1]
            if a - 2 * b + c:
                tau += 0.5 * (a - c) / (a - 2 * b + c)
        result.append(12 * np.log2(rate / tau / 55.0))
    return np.array(result)


class VoiceCheck:
    """Compare a turn's pitch with this job's own pitch profiles."""

    def __init__(self, revision, playback, wav_path, alignment=None):
        self.revision, self.playback, self.wav_path = revision, playback, wav_path
        self.alignment = alignment
        self._verified = alignment is None
        self._profiles = None
        self._pitches = {}

    @classmethod
    def create(cls, revision, alignment, wav_path):
        """Return a check when numpy, a WAV and its speech alignment exist."""
        if alignment is None or not wav_path:
            return None
        if importlib.util.find_spec('numpy') is None:
            return None
        return cls(revision, alignment.playback(), wav_path, alignment)

    def _available(self):
        if not self._verified:
            # Times from a different recording would compare the wrong speech.
            self._verified = True
            if not self.alignment.matches_wav(self.wav_path):
                self.playback = None
        return self.playback is not None

    def _windows(self, paragraphs):
        turns = speech_turns(paragraphs)
        order = sorted(turns)
        times = {}
        for index in order:
            try:
                times[index] = self.playback.position_ms(self.revision, turns[index][1])
            except ValueError:
                times[index] = None
        windows = {}
        for i, index in enumerate(order):
            start = times[index]
            if start is None:
                continue
            # The last turn runs until the cap; reads stop at the end of the WAV.
            end = times[order[i + 1]] if i + 1 < len(order) else start + TURN_SECONDS[1] * 1000
            if end is not None and end > start:
                windows[index] = (turns[index][0], start, end)
        return windows

    def _pitch(self, window, cap):
        import numpy as np
        _, start, end = window
        if (end - start) / 1000 < TURN_SECONDS[0]:
            return None
        key = (start, end, cap)
        if key not in self._pitches:
            frames = pitch_semitones(_read(self.wav_path, start, min(end, start + cap * 1000)))
            self._pitches[key] = float(np.median(frames)) if len(frames) >= MIN_VOICED_FRAMES else None
        return self._pitches[key]

    def _build(self, paragraphs):
        import numpy as np
        self._windows_by_index = windows = self._windows(paragraphs)
        by_name = {}
        for index, window in windows.items():
            if (window[2] - window[1]) / 1000 >= PROFILE_SECONDS[0]:
                by_name.setdefault(name_key(window[0]), []).append(window)
        profiles = {}
        for key, items in by_name.items():
            picks = [items[round(i)] for i in np.linspace(0, len(items) - 1, min(PROFILE_TURNS, len(items)))]
            values = [v for v in (self._pitch(w, PROFILE_SECONDS[1]) for w in picks) if v is not None]
            if len(values) >= MIN_PROFILE_TURNS:
                center = float(np.median(values))
                spread = max(0.5, 1.4826 * float(np.median(np.abs(np.array(values) - center))))
                profiles[key] = (center, spread)
        self._profiles = profiles

    def vote(self, paragraphs, index, current, proposed, *, byline=False):
        """Return the closer of two names for paragraph `index`, or None."""
        if not self._available():
            return None
        if self._profiles is None:
            self._build(paragraphs)
        a, b = self._profiles.get(name_key(current)), self._profiles.get(name_key(proposed))
        if not a or not b:
            return None
        separation = abs(a[0] - b[0])
        if separation < max(MIN_SEPARATION, 2 * (a[1] + b[1])):
            return None
        if byline:
            # A BY line has no speech of its own; its question follows it.
            following = [i for i in self._windows_by_index if i > index]
            index = min(following, default=None)
        window = self._windows_by_index.get(index)
        if window is None:
            return None
        pitch = self._pitch(window, TURN_SECONDS[1])
        if pitch is None:
            return None
        near, far = abs(pitch - a[0]), abs(pitch - b[0])
        if far - near >= separation / 2 and near <= max(MIN_SEPARATION, separation / 2):
            return current
        if near - far >= separation / 2 and far <= max(MIN_SEPARATION, separation / 2):
            return proposed
        return None


def checks(paragraphs, index, current, proposed, *, voice=None):
    """Collect JSON-safe votes for one disputed label and decide it."""
    _, line, label, _ = paragraphs[index]
    body = line[label.end():]
    examiner = None
    for previous in reversed(paragraphs[:index]):
        found = previous[2]
        if found and 'BY' in found['prefix'].upper() and not previous[1][found.end():].strip():
            examiner = found['name'].strip()
            break
    byline = 'BY' in label['prefix'].upper() and not body.strip()
    votes = {
        'voice': voice.vote(paragraphs, index, current, proposed, byline=byline) if voice else None,
        'context': None if byline else context_vote(body, current, proposed, examiner),
    }
    return decide(current, proposed, **votes), votes
