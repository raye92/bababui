from pathlib import Path

from transcript_pipeline.parser import (
    parse_zoom_transcript,
    serialize_zoom_transcript,
    sync_document_source_text,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_parse_zoom_sample_segments():
    source = (SAMPLES / "zoom_sample.txt").read_text(encoding="utf-8")
    document = parse_zoom_transcript(source)

    assert len(document.segments) == 5
    assert document.segments[0].speaker == "John Smith"
    assert document.segments[0].text == "Good morning, everyone."
    assert document.segments[0].timestamp == "00:00:05"
    assert document.segments[0].id == "seg-00001"


def test_parse_continuation_lines_append_to_previous_segment():
    source = "\n".join(
        [
            "00:00:01 John Smith: Opening line.",
            "This continues the same utterance.",
            "00:00:10 Mary Johnson: Next speaker.",
        ]
    )
    document = parse_zoom_transcript(source)

    assert len(document.segments) == 2
    assert "continues the same utterance" in document.segments[0].text


def test_serialize_zoom_transcript_after_speaker_accept():
    source = "00:00:20 Mary Johnson: My name is Mary Johnson."
    document = parse_zoom_transcript(source)
    document.segments[0].speaker = "MS. JOHNSON"
    sync_document_source_text(document)

    assert document.source_text == "00:00:20 MS. JOHNSON: My name is Mary Johnson."
    assert serialize_zoom_transcript(document) == document.source_text


def test_parse_assigns_stable_ids_on_repeat():
    source = "00:00:01 John Smith: Hello."
    first = parse_zoom_transcript(source)
    second = parse_zoom_transcript(source)

    assert [segment.id for segment in first.segments] == [
        segment.id for segment in second.segments
    ]
