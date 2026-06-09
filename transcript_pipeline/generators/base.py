from typing import Protocol

from transcript_pipeline.models import Suggestion, SuggestionType, TranscriptDocument


class SuggestionGenerator(Protocol):
    suggestion_type: SuggestionType

    def generate(
        self,
        document: TranscriptDocument,
        context: dict,
    ) -> list[Suggestion]:
        ...
