"""Native recording clocks and PCM drift correction, independent of Qt.

Clock and elapsed values use centiseconds. Audio marker offsets are PCM bytes.
The conversion was checked against CaseCAT 22.1's audio API on local copies.
"""
from bisect import bisect_right
from dataclasses import dataclass
import struct
import wave
import xml.etree.ElementTree as ET


def recording_events(xml):
    try:
        root = ET.fromstring(xml)
        fields = []
        for name in ('Timestamp', 'ElapsedTime', 'Pause'):
            prefix = f'Read-Audio-{name}-'
            values = {}
            for node in root.iter():
                if node.tag.startswith(prefix):
                    index = int(node.tag[len(prefix):])
                    if index in values:
                        raise ValueError('Duplicate recording event.')
                    values[index] = int(node.attrib['sgpref-val'])
            fields.append(values)
        count = len(fields[0])
        if not count or any(set(f) != set(range(count)) for f in fields):
            raise ValueError('Incomplete recording events.')
        events = tuple(zip(*(tuple(f[i] for i in range(count)) for f in fields)))
        if events[0][1:] != (0, 0):
            raise ValueError('Unsupported recording start.')
        for i, (clock, elapsed, paused) in enumerate(events):
            if clock < 0 or elapsed < 0 or paused not in (0, 1):
                raise ValueError('Invalid recording event.')
            if i:
                previous, before, was_paused = events[i-1]
                expected = before if was_paused else before + clock - previous
                if clock <= previous or paused == was_paused or elapsed != expected:
                    raise ValueError('Inconsistent recording events.')
        return events
    except (ET.ParseError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'Native recording timing is unavailable: {exc}') from exc


@dataclass
class AudioMap:
    events: tuple
    stroke_ms: tuple
    duration_ms: int
    _revision: object = None
    _ranges: tuple = ()

    def elapsed_centiseconds(self, clock):
        i = bisect_right(self.events, (clock, float('inf'), 1)) - 1
        if i < 0:
            return None
        start, elapsed, paused = self.events[i]
        return None if paused else elapsed + clock - start

    @classmethod
    def from_job(cls, bundle, job, wav_path):
        metadata = bundle.member(job.key + '.sgxml')
        if not metadata:
            raise ValueError('Native recording metadata is missing.')
        events = recording_events(bundle.read(metadata))
        with wave.open(str(wav_path), 'rb') as source:
            if source.getcomptype() != 'NONE':
                raise ValueError('Native timing currently requires PCM WAV audio.')
            byte_rate = source.getframerate() * source.getnchannels() * source.getsampwidth()
            duration = source.getnframes() * 1000 // source.getframerate()
        result = cls(events, (), duration)
        markers = []
        for span in job.baseline.spans:
            for value in span.audio:
                raw = bytes.fromhex(value)
                if len(raw) != 14 or raw[:6] != b'\x15\x08\x08\0\0\0':
                    raise ValueError('Unsupported native audio marker.')
                clock, byte_offset = struct.unpack_from('<II', raw, 6)
                elapsed = result.elapsed_centiseconds(clock)
                if elapsed is None or elapsed <= 0 or (markers and clock < markers[-1][0]):
                    raise ValueError('Unsupported native audio marker clock.')
                markers.append((clock, elapsed, byte_offset * 100 // byte_rate))
        if not markers:
            raise ValueError('No native audio synchronization markers were found.')
        clocks = [m[0] for m in markers]
        times = []
        for clock in job.stroke_clocks:
            elapsed = result.elapsed_centiseconds(clock)
            marker = bisect_right(clocks, clock) - 1
            if elapsed is None or marker < 0:
                times.append(None)
                continue
            _, reference, audio = markers[marker]
            # The native API truncates centiseconds after its double ratio.
            corrected = int((audio / reference) * elapsed) if audio else elapsed
            milliseconds = corrected * 10
            times.append(milliseconds if 0 <= milliseconds <= duration else None)
        result.stroke_ms = tuple(times)
        return result

    def ranges(self, revision):
        if self._revision is not revision:
            ranges, position = [], 0
            for span in revision.spans:
                end = position + len(span.content)
                if span.content and span.stroke_refs:
                    # Matches the writer's final affected source-group placement.
                    ref = max(span.stroke_refs)
                    time = self.stroke_ms[ref] if ref < len(self.stroke_ms) else None
                    if time is not None:
                        if ranges and ranges[-1][1] == position and ranges[-1][2] == time:
                            ranges[-1] = (ranges[-1][0], end, time)
                        else:
                            ranges.append((position, end, time))
                position = end
            self._revision, self._ranges = revision, tuple(ranges)
        return self._ranges

    def position_ms(self, revision, position):
        if not 0 <= position <= len(revision.text):
            raise ValueError('Playback position exceeds the transcript.')
        ranges = self.ranges(revision)
        for start, end, time in ranges:
            if start <= position < end or position == end == len(revision.text):
                return time
        return None

    def range_at(self, revision, milliseconds):
        eligible = [(time, start, end) for start, end, time in self.ranges(revision)
                    if time <= milliseconds]
        if not eligible:
            return None
        _, start, end = max(eligible)
        return start, end
