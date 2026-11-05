"""Saved evaluation choices and transcript transformations."""
import re

from transcript_formatting import TranscriptFormatter


MODELS = {"deepseek-v4-pro": "DeepSeek V4 Pro", "deepseek-flash": "DeepSeek Flash"}
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_FILTERS = {"strip_formatting": True, "remove_hash_marker": True, "remove_slash_marker": False}
LEGACY_FILTERS = dict.fromkeys(DEFAULT_FILTERS, False)
FORMATTER = TranscriptFormatter()


def grading_text(text, strip):
    if strip:
        return FORMATTER.strip_formatting(text)
    return text


def model_input(text, filters):
    text = grading_text(text, filters["strip_formatting"])
    if filters["remove_slash_marker"]:
        return re.sub(r"/\S+", "", text)
    if filters["remove_hash_marker"]:
        return re.sub(r"(?<!\S)/#\*\S+", "", text)
    return text


def formatted_transcript(response):
    return FORMATTER.apply_formatting(grading_text(response, True))[0]
