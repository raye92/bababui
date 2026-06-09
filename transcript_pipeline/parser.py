import re

from transcript_pipeline.models import Segment, TranscriptDocument

# HH:MM:SS Speaker Name: utterance text
_SPEAKER_LINE = re.compile(
    r"^(?:(\d{1,2}:\d{2}:\d{2})\s+)?([^:]+?):\s*(.*)$"
)


def parse_zoom_transcript(
    source_text: str,
    metadata: dict | None = None,
) -> TranscriptDocument:
    """Parse a Zoom transcript into locatable segments.

    Speaker lines look like:
        00:01:23 John Smith: Good morning.
    Continuation lines without a speaker label append to the previous segment.
    """
    lines = source_text.splitlines()
    segments: list[Segment] = []
    current: Segment | None = None
    segment_index = 0

    for line_number, raw_line in enumerate(lines, start=1):
        match = _SPEAKER_LINE.match(raw_line.strip())
        if match:
            timestamp, speaker, text = match.groups()
            segment_index += 1
            current = Segment(
                id=f"seg-{segment_index:05d}",
                speaker=speaker.strip(),
                text=text.strip(),
                raw_line_start=line_number,
                timestamp=timestamp,
            )
            segments.append(current)
            continue

        stripped = raw_line.strip()
        if not stripped:
            continue

        if current is None:
            segment_index += 1
            current = Segment(
                id=f"seg-{segment_index:05d}",
                speaker=None,
                text=stripped,
                raw_line_start=line_number,
            )
            segments.append(current)
            continue

        if current.text:
            current.text = f"{current.text} {stripped}"
        else:
            current.text = stripped

    return TranscriptDocument(
        source_text=source_text,
        segments=segments,
        metadata=dict(metadata or {}),
    )


def serialize_zoom_segment(segment: Segment) -> str:
    """Serialize one segment back to Zoom transcript line format."""
    if segment.speaker:
        prefix = f"{segment.timestamp} " if segment.timestamp else ""
        return f"{prefix}{segment.speaker}: {segment.text}"
    return segment.text


def serialize_zoom_transcript(document: TranscriptDocument) -> str:
    """Rebuild the canonical Zoom transcript string from segments."""
    return "\n".join(serialize_zoom_segment(segment) for segment in document.segments)


def sync_document_source_text(document: TranscriptDocument) -> str:
    """Update document.source_text from segments and return it."""
    document.source_text = serialize_zoom_transcript(document)
    return document.source_text
