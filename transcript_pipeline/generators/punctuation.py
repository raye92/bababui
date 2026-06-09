from transcript_pipeline.models import Suggestion, SuggestionType, TranscriptDocument


class PunctuationGenerator:
    suggestion_type = SuggestionType.PUNCTUATION

    def generate(self, document: TranscriptDocument, context: dict) -> list[Suggestion]:
        return []
