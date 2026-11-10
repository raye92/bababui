import re

import pytest

from transcript_formatting import TranscriptFormatter
from evaluation.setups import formatted_transcript, grading_text


FORMATTER = TranscriptFormatter()


def content_lines(numbered):
    return re.findall(r"^ {9,10}\d{1,2} {4}(.+)$", numbered, re.MULTILINE)


@pytest.mark.parametrize("prefix", ["     Q    ", "     A    ", "     SPEAKER 3:  ", "          "])
def test_wrap_counts_labels_and_indentation_but_not_number_gutter(prefix):
    paragraph = prefix + "Please describe the records you reviewed before the examination."
    numbered, pages = FORMATTER.apply_formatting(paragraph)
    lines = content_lines(numbered)

    assert pages == 1
    assert len(lines) == 2
    assert all(len(line) <= 56 for line in lines)
    assert lines[0].startswith(prefix)
    assert not lines[1].startswith(" ")
    assert FORMATTER.strip_formatting(numbered) == paragraph


@pytest.mark.parametrize(("suffix", "expected"), [
    ("", ["     Q    " + "x" * 46]),
    (" y", ["     Q    " + "x" * 46, "y"]),
])
def test_wrap_only_when_content_exceeds_56(suffix, expected):
    numbered, _ = FORMATTER.apply_formatting("     Q    " + "x" * 46 + suffix)
    assert content_lines(numbered) == expected


def test_wrap_never_splits_words_or_hyphenated_terms():
    token = "medical-" + "x" * 60
    paragraph = "     A    It was " + token + " in the report."
    numbered, _ = FORMATTER.apply_formatting(paragraph)
    assert content_lines(numbered) == ["     A    It was", token, "in the report."]
    assert FORMATTER.strip_formatting(numbered) == paragraph


def test_strip_joins_multiple_physical_lines_using_each_lines_width():
    wrapped = (
        "     Q    Please describe the records you reviewed\n"
        "before the examination and identify which reports you\n"
        "considered when you reached your conclusion."
    )
    expected = (
        "     Q    Please describe the records you reviewed before "
        "the examination and identify which reports you considered "
        "when you reached your conclusion."
    )
    assert FORMATTER.strip_formatting(wrapped) == expected


@pytest.mark.parametrize("boundary", [
    "     Q    Another question?",
    "     A    Yes.",
    "     SPEAKER 3:  Objection.",
    "     MR. SMITH:  Objection.",
    "          Now a completely different topic.",
    "                      EXAMINATION",
    "                  FURTHER EXAMINATION",
    "BY SPEAKER 2:",
    "               (Off the record.)",
    "///",
    "42",
])
def test_strip_preserves_structural_boundaries_after_a_full_line(boundary):
    text = "     Q    " + "x" * 46 + "\n" + boundary
    assert FORMATTER.strip_formatting(text) == text


@pytest.mark.parametrize("text", [
    "Free-form text " + "x" * 45 + "\nAnother line",
    "     Q    How many?\n42\n1821    Main Street",
    "     Q    Brief question?\nAmbiguous separate text.",
    "     A    " + "x" * 46 + "\n  Indented separate text.",
    "A\t /#tag Keep  spacing.\nB",
])
def test_strip_keeps_ambiguous_line_breaks_and_interior_whitespace(text):
    assert FORMATTER.strip_formatting(text) == text


def test_wrapping_crosses_page_boundary_and_reapplying_is_stable():
    prefix = "     A    Short answer.\n" * 24
    paragraph = "     Q    Please describe the records you reviewed before the examination."
    numbered, pages = FORMATTER.apply_formatting(prefix + paragraph)

    assert pages == 2
    assert "         25         Q    Please describe the records you reviewed\n" in numbered
    assert "          1    before the examination.\n" in numbered.split("\f")[1]
    assert FORMATTER.strip_formatting(numbered) == prefix + paragraph
    assert FORMATTER.apply_formatting(numbered) == (numbered, pages)


@pytest.mark.parametrize("wrapped", [False, True])
def test_repeated_stripping_keeps_ambiguous_break_after_a_long_paragraph(wrapped):
    paragraph = "     Q    Please describe the records you reviewed before the examination."
    expected = paragraph + "\nSeparate note."
    text = expected.replace("reviewed before", "reviewed\nbefore") if wrapped else expected

    assert FORMATTER.strip_formatting(text) == expected
    assert FORMATTER.strip_formatting(FORMATTER.strip_formatting(text)) == expected
    direct, _ = FORMATTER.apply_formatting(text)
    assert content_lines(direct) == [
        "     Q    Please describe the records you reviewed",
        "before the examination.",
        "Separate note.",
    ]
    assert formatted_transcript(text) == direct


def test_eval_grading_unwraps_exports_without_changing_logical_paragraphs():
    text = (
        "                      EXAMINATION\nBY SPEAKER 2:\n"
        "     Q    Please describe the records you reviewed before the examination.\n"
        "          Now describe your employment history before you moved here.\n"
        "     A    I worked there.  It was part-time."
    )
    export = formatted_transcript(text)
    assert len(content_lines(export)) == 7
    assert grading_text(export, True) == text
    assert grading_text(export, False) == export
    assert formatted_transcript(export) == export
