from transcript_pipeline.apply_suggestions import apply_accepted_suggestion
from transcript_pipeline.models import Location, Suggestion, SuggestionStatus, SuggestionType
from transcript_pipeline.parser import parse_zoom_transcript, sync_document_source_text


def test_apply_accepted_suggestion_updates_canonical_zoom_line():
    source = "00:00:28 Speaker 2: Please proceed."
    document = parse_zoom_transcript(source)
    suggestion = Suggestion(
        id="sug-1",
        type=SuggestionType.SPEAKER_CORRECTION,
        original_text="Speaker 2",
        replacement_text="THE COURT",
        confidence=0.6,
        reason="test",
        location=Location(segment_id="seg-00001", field="speaker"),
        status=SuggestionStatus.ACCEPTED,
    )

    apply_accepted_suggestion(document, suggestion)
    sync_document_source_text(document)

    assert document.source_text == "00:00:28 THE COURT: Please proceed."
