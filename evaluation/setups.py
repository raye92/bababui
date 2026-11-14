"""Saved evaluation choices and transcript transformations."""
import re

from shared.client import DEFAULT_MODEL
from shared.transcript_formatting import TranscriptFormatter


MODELS = {"deepseek-v4-pro": "DeepSeek V4 Pro", "deepseek-flash": "DeepSeek Flash"}
DEFAULT_FILTERS = {"strip_formatting": True, "remove_hash_marker": True, "remove_slash_marker": False,
                   "remove_heading": True}
LEGACY_FILTERS = dict.fromkeys(DEFAULT_FILTERS, False)
FORMATTER = TranscriptFormatter()
LINE_NUMBER = r"(?:[1-9]|1[0-9]|2[0-5])"
HEADING_END = re.compile(rf"({LINE_NUMBER}\s+)?transcript\s+of\s+the\s+proceeding\.", re.IGNORECASE)


def grading_text(text, strip):
    if strip:
        return FORMATTER.strip_formatting(text)
    return text


def expected_for_grading(text, filters):
    warning = None
    if filters.get("remove_heading", False):
        lines = text.splitlines(keepends=True)
        markers = [(index, match) for index, line in enumerate(lines)
                   if (match := HEADING_END.fullmatch(line.strip()))]
        if not markers:
            warning = "marker missing"
        elif len(markers) > 1:
            warning = "marker repeated"
        else:
            marker_index, marker = markers[0]
            for index in range(marker_index + 1, len(lines)):
                content = lines[index].strip()
                if content and not (marker.group(1) and re.fullmatch(LINE_NUMBER, content)):
                    text = "".join(lines[index:])
                    break
            else:
                warning = "no proceeding text after marker"
    return grading_text(text, filters["strip_formatting"]), warning


def model_input(text, filters):
    text = grading_text(text, filters["strip_formatting"])
    if filters["remove_slash_marker"]:
        return re.sub(r"/\S+", "", text)
    if filters["remove_hash_marker"]:
        return re.sub(r"(?<!\S)/#\*\S+", "", text)
    return text


def formatted_transcript(response):
    return FORMATTER.apply_formatting(grading_text(response, True))[0]
