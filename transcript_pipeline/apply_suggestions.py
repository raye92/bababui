from __future__ import annotations

import copy

from transcript_pipeline.models import (
    AppliedTranscript,
    Segment,
    Suggestion,
    SuggestionStatus,
    TranscriptDocument,
    iter_segments_by_id,
    suggestion_sort_key,
    validate_suggestions,
)
from transcript_pipeline.segment_renderer import render_segments


def _copy_segments(document: TranscriptDocument) -> dict[str, Segment]:
    return {
        segment.id: copy.copy(segment)
        for segment in document.segments
    }


def apply_suggestions(
    document: TranscriptDocument,
    suggestions: list[Suggestion],
) -> AppliedTranscript:
    """Apply only accepted suggestions to a working copy of the document."""
    accepted = [
        suggestion
        for suggestion in suggestions
        if suggestion.status == SuggestionStatus.ACCEPTED
    ]
    pending_count = sum(
        1 for suggestion in suggestions if suggestion.status == SuggestionStatus.PENDING
    )

    if not accepted:
        return AppliedTranscript(
            source_text=document.source_text,
            working_text=render_segments(document),
            applied_suggestion_ids=[],
            skipped_pending_count=pending_count,
        )

    validate_suggestions(document, accepted)

    segments = _copy_segments(document)
    for suggestion in sorted(accepted, key=suggestion_sort_key, reverse=True):
        segment = segments[suggestion.location.segment_id]
        if suggestion.location.field == "speaker":
            segment.speaker = suggestion.replacement_text
        else:
            start = suggestion.location.start_offset
            end = suggestion.location.end_offset
            segment.text = (
                segment.text[:start]
                + suggestion.replacement_text
                + segment.text[end:]
            )

    working_document = TranscriptDocument(
        source_text=document.source_text,
        segments=list(segments.values()),
        metadata=dict(document.metadata),
    )

    return AppliedTranscript(
        source_text=document.source_text,
        working_text=render_segments(working_document),
        applied_suggestion_ids=[suggestion.id for suggestion in accepted],
        skipped_pending_count=pending_count,
    )
