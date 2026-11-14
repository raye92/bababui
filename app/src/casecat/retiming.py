"""Encode speech timing in a CaseCAT export copy with PCM audio."""
from bisect import bisect_right
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import PureWindowsPath
import struct
import wave

from .anchors import Revision
from .codec import records, u32
from .structure import group_targets
from .timing import AudioMap, raw_recording_events, recording_events


class AudioExportError(ValueError):
    """The job can still be exported with its source audio timing."""


def _recording_clocks(events, times, duration):
    """Convert WAV milliseconds back to centisecond clocks, skipping pauses."""
    active = [i for i, (_, _, paused) in enumerate(events) if not paused]
    starts = [events[i][1] for i in active]
    tail = events[-1][1] - 1 if events[-1][2] else duration // 10
    clocks = []
    for time in times:
        if not 0 <= time <= duration:
            raise AudioExportError('Corrected timing falls outside the bundled WAV.')
        elapsed_cs = time // 10
        if elapsed_cs > tail:
            raise AudioExportError('Corrected timing falls outside the native recording intervals.')
        start, elapsed, _ = events[active[bisect_right(starts, elapsed_cs) - 1]]
        clocks.append(start + elapsed_cs - elapsed)
    if clocks and clocks[-1] > 0xffffffff:
        raise AudioExportError('Corrected timing exceeds the supported native clock range.')
    return tuple(clocks)


def _rewrite_strokes(native, notes, clocks):
    # CaseCAT can reuse a stroke in another passage. Its copy must remain
    # byte-identical to the companion note, including the recorded clock.
    result, rewritten_notes = bytearray(native), bytearray(notes)
    note, occurrence = 640, 0
    start, length = u32(native, 532), u32(native, 536)
    for offset, raw in records(native, start, start + length):
        if raw[0] != 0x13:
            continue
        for i in range(3, len(raw), 8):
            original = raw[i:i + 8]
            at = offset + i + 4
            if original != notes[note:note + 8]:
                raise AudioExportError('This job contains copied strokes whose CaseCAT timing cannot be verified.')
            struct.pack_into('<I', result, at, clocks[occurrence])
            struct.pack_into('<I', rewritten_notes, note + 4, clocks[occurrence])
            note += 8
            occurrence += 1
    if note != len(notes) or occurrence != len(clocks):
        raise AudioExportError('The native transcript and notes disagree about stroke order.')
    return result, bytes(rewritten_notes)


def _normalize_markers(native, events, byte_rate):
    # CorrectForDrift scales each stroke by the PCM/native ratio of its active
    # marker. The new stroke clocks already account for drift and reporter lag.
    # With a unit ratio, the two conversions do not compound one another.
    start, length = u32(native, 532), u32(native, 536)
    native_map = AudioMap(events, (), 0)
    for offset, raw in records(native, start, start + length):
        if raw[:2] != b'\x15\x08':
            continue
        if len(raw) != 14 or raw[:6] != b'\x15\x08\x08\0\0\0':
            raise AudioExportError('Unsupported CaseCAT audio marker.')
        elapsed = native_map.elapsed_centiseconds(u32(raw, 6))
        if elapsed is None or elapsed <= 0 or elapsed * byte_rate % 100:
            raise AudioExportError('The PCM marker cannot be represented at native clock precision.')
        pcm = elapsed * byte_rate // 100
        if pcm > 0xffffffff:
            raise AudioExportError('The PCM marker exceeds the native file offset range.')
        struct.pack_into('<I', native, offset + 10, pcm)


def _check_recording(native, metadata, name):
    start, length = struct.unpack_from('<II', native, 556)
    end = start + length
    if not start or length < 264 or end > len(native):
        raise AudioExportError('The CaseCAT audio section is unavailable.')
    paths, sep, padding = native[start:start + 260].partition(b'\0\0')
    basename = PureWindowsPath(name).name.casefold()
    if (not sep or any(padding) or any(PureWindowsPath(p.decode('cp1252')).name.casefold() != basename
                                      for p in paths.split(b'\0'))):
        raise AudioExportError('The audio section does not reference the bundled WAV.')
    count = u32(native, start + 260)
    if length != 264 + count * 12:
        raise AudioExportError('The CaseCAT audio section has an unsupported layout.')
    rows = tuple(struct.iter_unpack('<III', native[start + 264:end]))
    if rows != tuple((paused, clock, elapsed) for clock, elapsed, paused in raw_recording_events(metadata)):
        raise AudioExportError('The transcript and job metadata use different recording clocks.')


def retime_export(bundle, job, native, metadata, alignment):
    if not job.audio_member:
        raise AudioExportError('The ZIP contains no WAV to carry corrected timing.')
    wav = bundle.read(job.audio_member)
    if sha256(wav).hexdigest() != alignment.wav_sha256:
        raise AudioExportError('The ZIP contains a different WAV than the one used for alignment.')
    if metadata is None:
        raise AudioExportError('The ZIP contains no CaseCAT recording metadata.')
    try:
        if len(alignment.stroke_ms) != len(job.stroke_clocks):
            raise AudioExportError('The alignment does not cover this job’s stroke records.')
        _check_recording(native, metadata, job.audio_member)
        events = recording_events(metadata)
        with wave.open(BytesIO(wav), 'rb') as source:
            original = AudioMap.from_recording(bundle, job, source)
            byte_rate = source.getframerate() * source.getnchannels() * source.getsampwidth()

        targets = job.baseline
        if job.revision != job.baseline:
            targets = Revision(tuple(replace(span, content=text) for span, text in
                                     zip(job.baseline.spans, group_targets(job))))
        times = alignment.export_strokes(targets)
        clocks = _recording_clocks(events, times, original.duration_ms)
        native, notes = _rewrite_strokes(native, job.notes_bytes, clocks)
        _normalize_markers(native, events, byte_rate)
    except AudioExportError:
        raise
    except (ValueError, OSError, wave.Error, EOFError, struct.error) as exc:
        raise AudioExportError(str(exc)) from exc
    # Verify the reimport against independently decoded timing, rounded to a
    # centisecond, and ensure the ZIP writer keeps the exact rewritten notes.
    return bytes(native), notes, tuple(t // 10 * 10 for t in times)
