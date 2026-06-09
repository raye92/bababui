from transcript_pipeline.models import Suggestion, SuggestionType, TranscriptDocument


class FormattingGenerator:
    suggestion_type = SuggestionType.FORMATTING

    def generate(self, document: TranscriptDocument, context: dict) -> list[Suggestion]:
        return []
