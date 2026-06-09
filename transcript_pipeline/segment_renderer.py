from transcript_pipeline.models import Segment, TranscriptDocument


def render_segment(segment: Segment) -> str:
    if segment.speaker:
        return f"{segment.speaker}: {segment.text}".strip()
    return segment.text.strip()


def render_segments(document: TranscriptDocument) -> str:
    return "\n\n".join(render_segment(segment) for segment in document.segments)
