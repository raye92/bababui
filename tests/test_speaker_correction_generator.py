import json
from collections import Counter
from pathlib import Path

from transcript_pipeline.models import SuggestionType
from transcript_pipeline.parser import parse_zoom_transcript
from transcript_pipeline.suggestion_engine import generate_suggestions

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_speaker_correction_matches_zoom_sample_expectations():
    fixture = json.loads((SAMPLES / "suggestions_expected.json").read_text(encoding="utf-8"))
    source = (SAMPLES / "zoom_sample.txt").read_text(encoding="utf-8")
    document = parse_zoom_transcript(
        source,
        metadata={"official_speakers": fixture["official_speakers"]},
    )

    suggestions = generate_suggestions(
        document,
        types=[SuggestionType.SPEAKER_CORRECTION],
        context={"official_speakers": fixture["official_speakers"]},
    )

    assert all(suggestion.type == SuggestionType.SPEAKER_CORRECTION for suggestion in suggestions)

    actual = Counter(
        (suggestion.original_text, suggestion.replacement_text) for suggestion in suggestions
    )
    expected = Counter(
        {
            (item["original_text"], item["replacement_text"]): item["segment_count"]
            for item in fixture["expected_corrections"]
        }
    )

    assert actual == expected


def test_speaker_correction_does_not_mutate_document():
    source = "00:00:01 John Smith: Hello."
    document = parse_zoom_transcript(source)
    original_speaker = document.segments[0].speaker

    generate_suggestions(
        document,
        types=[SuggestionType.SPEAKER_CORRECTION],
        context={"official_speakers": ["MR. SMITH"]},
    )

    assert document.segments[0].speaker == original_speaker
