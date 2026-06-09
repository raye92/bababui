from transcript_pipeline.models import Suggestion, SuggestionType, TranscriptDocument


class TerminologyGenerator:
    suggestion_type = SuggestionType.TERMINOLOGY

    def generate(self, document: TranscriptDocument, context: dict) -> list[Suggestion]:
        return []
