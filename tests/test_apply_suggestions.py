from transcript_pipeline.apply_suggestions import apply_suggestions
from transcript_pipeline.models import (
    Location,
    Segment,
    Suggestion,
    SuggestionStatus,
    SuggestionType,
    TranscriptDocument,
)
from transcript_pipeline.parser import parse_zoom_transcript


def _speaker_suggestion(
    segment_id: str,
    original: str,
    replacement: str,
    *,
    status: SuggestionStatus = SuggestionStatus.ACCEPTED,
) -> Suggestion:
    return Suggestion(
        id=f"sug-{segment_id}",
        type=SuggestionType.SPEAKER_CORRECTION,
        original_text=original,
        replacement_text=replacement,
        confidence=0.9,
        reason="test",
        location=Location(segment_id=segment_id, field="speaker"),
        status=status,
    )


def test_apply_suggestions_changes_only_accepted():
    document = TranscriptDocument(
        source_text="John: Hello",
        segments=[Segment(id="seg-00001", speaker="John", text="Hello", raw_line_start=1)],
    )
    suggestions = [
        _speaker_suggestion("seg-00001", "John", "MR. SMITH", status=SuggestionStatus.ACCEPTED),
        Suggestion(
            id="sug-text",
            type=SuggestionType.PUNCTUATION,
            original_text="Hello",
            replacement_text="Hello.",
            confidence=0.8,
            reason="test",
            location=Location(
                segment_id="seg-00001",
                start_offset=0,
                end_offset=5,
                field="text",
            ),
            status=SuggestionStatus.REJECTED,
        ),
    ]

    result = apply_suggestions(document, suggestions)

    assert "MR. SMITH: Hello" in result.working_text
    assert "MR. SMITH: Hello." not in result.working_text
    assert result.applied_suggestion_ids == ["sug-seg-00001"]


def test_apply_suggestions_leaves_source_unchanged():
    source = "00:00:01 John Smith: Hello."
    document = parse_zoom_transcript(source)
    suggestions = generate_accepted_speaker_fix(document)

    apply_suggestions(document, suggestions)

    assert document.segments[0].speaker == "John Smith"


def test_apply_suggestions_reports_pending_count():
    document = parse_zoom_transcript("00:00:01 John Smith: Hello.")
    suggestions = [
        _speaker_suggestion("seg-00001", "John Smith", "MR. SMITH", status=SuggestionStatus.PENDING),
    ]

    result = apply_suggestions(document, suggestions)

    assert result.skipped_pending_count == 1
    assert "John Smith: Hello." in result.working_text


def generate_accepted_speaker_fix(document: TranscriptDocument) -> list[Suggestion]:
    return [
        _speaker_suggestion(
            document.segments[0].id,
            document.segments[0].speaker or "",
            "MR. SMITH",
        )
    ]


def test_apply_suggestions_integration_with_zoom_sample():
    from pathlib import Path

    samples = Path(__file__).resolve().parents[1] / "samples"
    source = (samples / "zoom_sample.txt").read_text(encoding="utf-8")
    document = parse_zoom_transcript(source)

    suggestions = [
        _speaker_suggestion("seg-00001", "John Smith", "MR. SMITH"),
        _speaker_suggestion("seg-00002", "John Smith", "MR. SMITH"),
        _speaker_suggestion("seg-00003", "Mary Johnson", "MS. JOHNSON"),
        _speaker_suggestion("seg-00004", "Speaker 2", "THE COURT"),
        _speaker_suggestion("seg-00005", "John Smith", "MR. SMITH"),
    ]

    result = apply_suggestions(document, suggestions)

    assert "MR. SMITH: Good morning, everyone." in result.working_text
    assert "MS. JOHNSON: My name is Mary Johnson." in result.working_text
    assert "THE COURT: Please proceed." in result.working_text
    assert "MR. SMITH: Thank you, Your Honor." in result.working_text
