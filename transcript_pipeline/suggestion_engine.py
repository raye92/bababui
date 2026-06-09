from __future__ import annotations

from transcript_pipeline.generators import (
    CapitalizationGenerator,
    FormattingGenerator,
    PunctuationGenerator,
    SpeakerCorrectionGenerator,
    SuggestionGenerator,
    TerminologyGenerator,
)
from transcript_pipeline.models import (
    Location,
    Suggestion,
    SuggestionType,
    TranscriptDocument,
    suggestion_sort_key,
    validate_suggestions,
)

_DEFAULT_GENERATORS: list[SuggestionGenerator] = [
    SpeakerCorrectionGenerator(),
    PunctuationGenerator(),
    CapitalizationGenerator(),
    TerminologyGenerator(),
    FormattingGenerator(),
]

_TYPE_TO_GENERATOR = {generator.suggestion_type: generator for generator in _DEFAULT_GENERATORS}


def _locations_overlap(left: Location, right: Location) -> bool:
    if left.segment_id != right.segment_id or left.field != right.field:
        return False
    if left.field == "speaker":
        return True
    return left.start_offset < right.end_offset and right.start_offset < left.end_offset


def _dedupe_suggestions(suggestions: list[Suggestion]) -> list[Suggestion]:
    kept: list[Suggestion] = []
    for suggestion in sorted(suggestions, key=lambda item: item.confidence, reverse=True):
        if any(_locations_overlap(suggestion.location, existing.location) for existing in kept):
            continue
        kept.append(suggestion)
    return sorted(kept, key=suggestion_sort_key)


def generate_suggestions(
    document: TranscriptDocument,
    *,
    types: list[SuggestionType] | None = None,
    context: dict | None = None,
    generators: list[SuggestionGenerator] | None = None,
) -> list[Suggestion]:
    """Run enabled generators and return validated, deduplicated suggestions."""
    runtime_context = dict(context or {})
    runtime_context.setdefault(
        "official_speakers",
        document.metadata.get("official_speakers", []),
    )

    selected_generators = generators or _DEFAULT_GENERATORS
    if types is not None:
        selected_generators = [_TYPE_TO_GENERATOR[suggestion_type] for suggestion_type in types]

    suggestions: list[Suggestion] = []
    for generator in selected_generators:
        suggestions.extend(generator.generate(document, runtime_context))

    suggestions = _dedupe_suggestions(suggestions)
    validate_suggestions(document, suggestions)
    return suggestions
