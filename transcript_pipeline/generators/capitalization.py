from transcript_pipeline.models import Suggestion, SuggestionType, TranscriptDocument


class CapitalizationGenerator:
    suggestion_type = SuggestionType.CAPITALIZATION

    def generate(self, document: TranscriptDocument, context: dict) -> list[Suggestion]:
        return []
