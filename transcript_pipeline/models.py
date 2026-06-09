from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class SuggestionType(str, Enum):
    SPEAKER_CORRECTION = "speaker_correction"
    PUNCTUATION = "punctuation"
    CAPITALIZATION = "capitalization"
    FORMATTING = "formatting"
    TERMINOLOGY = "terminology"
    OTHER = "other"


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Location:
    segment_id: str
    start_offset: int = 0
    end_offset: int = 0
    field: str = "text"
    line_number: int | None = None
    context_before: str = ""
    context_after: str = ""


@dataclass
class Suggestion:
    id: str
    type: SuggestionType
    original_text: str
    replacement_text: str
    confidence: float
    reason: str
    location: Location
    status: SuggestionStatus = SuggestionStatus.PENDING


@dataclass
class Segment:
    id: str
    speaker: str | None
    text: str
    raw_line_start: int
    timestamp: str | None = None


@dataclass
class TranscriptDocument:
    source_text: str
    segments: list[Segment]
    metadata: dict = field(default_factory=dict)


@dataclass
class AppliedTranscript:
    source_text: str
    working_text: str
    applied_suggestion_ids: list[str]
    skipped_pending_count: int


@dataclass
class ReviewSession:
    document: TranscriptDocument
    suggestions: list[Suggestion]

    def pending(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.PENDING]

    def accepted(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.ACCEPTED]

    def rejected(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.status == SuggestionStatus.REJECTED]

    def pending_count(self) -> int:
        return len(self.pending())

    def resolve(self, suggestion_id: str, status: SuggestionStatus) -> None:
        for suggestion in self.suggestions:
            if suggestion.id == suggestion_id:
                suggestion.status = status
                return
        raise KeyError(f"Suggestion not found: {suggestion_id}")

    def accept_all_pending(self) -> None:
        for suggestion in self.pending():
            suggestion.status = SuggestionStatus.ACCEPTED

    def reject_all_pending(self) -> None:
        for suggestion in self.pending():
            suggestion.status = SuggestionStatus.REJECTED

    def summary(self) -> dict[str, int]:
        counts = {status.value: 0 for status in SuggestionStatus}
        for suggestion in self.suggestions:
            counts[suggestion.status.value] += 1
        return counts


def suggestion_sort_key(suggestion: Suggestion) -> tuple[str, str, int]:
    """Sort suggestions by document position (segment, field, offset)."""
    field_order = 0 if suggestion.location.field == "speaker" else 1
    return (
        suggestion.location.segment_id,
        str(field_order),
        suggestion.location.start_offset,
    )


def iter_segments_by_id(document: TranscriptDocument) -> dict[str, Segment]:
    return {segment.id: segment for segment in document.segments}


def validate_suggestions(document: TranscriptDocument, suggestions: Iterable[Suggestion]) -> None:
    segments = iter_segments_by_id(document)
    for suggestion in suggestions:
        segment = segments.get(suggestion.location.segment_id)
        if segment is None:
            raise ValueError(f"Unknown segment id: {suggestion.location.segment_id}")

        if suggestion.location.field == "speaker":
            current = segment.speaker or ""
        else:
            current = segment.text[
                suggestion.location.start_offset : suggestion.location.end_offset
            ]

        if current != suggestion.original_text:
            raise ValueError(
                f"Suggestion {suggestion.id} original_text does not match source: "
                f"expected {suggestion.original_text!r}, found {current!r}"
            )
