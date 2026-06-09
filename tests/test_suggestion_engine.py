from transcript_pipeline.models import SuggestionType, TranscriptDocument
from transcript_pipeline.parser import parse_zoom_transcript
from transcript_pipeline.suggestion_engine import generate_suggestions


def test_generate_suggestions_returns_empty_without_official_speakers():
    document = parse_zoom_transcript("00:00:01 John Smith: Hello.")
    suggestions = generate_suggestions(document, context={"official_speakers": []})

    assert suggestions == []


def test_generate_suggestions_can_limit_types():
    document = parse_zoom_transcript("00:00:01 John Smith: Hello.")
    suggestions = generate_suggestions(
        document,
        types=[SuggestionType.PUNCTUATION],
        context={"official_speakers": ["MR. SMITH"]},
    )

    assert suggestions == []


def test_generate_suggestions_assigns_unique_ids():
    source = "\n".join(
        [
            "00:00:01 John Smith: One.",
            "00:00:02 John Smith: Two.",
        ]
    )
    document = parse_zoom_transcript(source)
    suggestions = generate_suggestions(
        document,
        types=[SuggestionType.SPEAKER_CORRECTION],
        context={"official_speakers": ["MR. SMITH"]},
    )

    assert len(suggestions) == 2
    assert len({suggestion.id for suggestion in suggestions}) == 2
