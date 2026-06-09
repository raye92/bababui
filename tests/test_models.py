import pytest

from transcript_pipeline.models import (
    Location,
    ReviewSession,
    Segment,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
    TranscriptDocument,
    validate_suggestions,
)


def _document() -> TranscriptDocument:
    return TranscriptDocument(
        source_text="John: Hello",
        segments=[
            Segment(id="seg-00001", speaker="John", text="Hello", raw_line_start=1),
        ],
    )


def _suggestion(**overrides) -> Suggestion:
    defaults = {
        "id": "sug-1",
        "type": SuggestionType.SPEAKER_CORRECTION,
        "original_text": "John",
        "replacement_text": "MR. SMITH",
        "confidence": 0.9,
        "reason": "test",
        "location": Location(segment_id="seg-00001", field="speaker"),
    }
    defaults.update(overrides)
    return Suggestion(**defaults)


def test_review_session_status_helpers():
    session = ReviewSession(
        document=_document(),
        suggestions=[
            _suggestion(id="a", status=SuggestionStatus.PENDING),
            _suggestion(id="b", status=SuggestionStatus.ACCEPTED),
            _suggestion(id="c", status=SuggestionStatus.REJECTED),
        ],
    )

    assert session.pending_count() == 1
    assert len(session.accepted()) == 1
    assert len(session.rejected()) == 1


def test_review_session_resolve_and_bulk_actions():
    session = ReviewSession(
        document=_document(),
        suggestions=[
            _suggestion(id="a"),
            _suggestion(id="b"),
        ],
    )

    session.resolve("a", SuggestionStatus.ACCEPTED)
    session.accept_all_pending()

    assert session.suggestions[0].status == SuggestionStatus.ACCEPTED
    assert session.suggestions[1].status == SuggestionStatus.ACCEPTED

    session.reject_all_pending()
    assert all(s.status == SuggestionStatus.ACCEPTED for s in session.suggestions)


def test_validate_suggestions_rejects_mismatched_original_text():
    document = _document()
    suggestion = _suggestion(original_text="Jane")

    with pytest.raises(ValueError, match="does not match source"):
        validate_suggestions(document, [suggestion])
