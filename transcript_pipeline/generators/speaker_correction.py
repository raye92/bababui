from __future__ import annotations

import re
import uuid

from transcript_pipeline.models import (
    Location,
    Suggestion,
    SuggestionType,
    TranscriptDocument,
)


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _surname(name: str) -> str:
    parts = _normalize_name(name).split()
    return parts[-1] if parts else ""


def _title_variants(official_name: str) -> set[str]:
    normalized = _normalize_name(official_name)
    variants = {normalized}
    for prefix in ("mr", "ms", "mrs", "dr", "the"):
        if normalized.startswith(prefix + " "):
            variants.add(normalized[len(prefix) + 1 :])
    return variants


def _find_official_match(
    zoom_speaker: str,
    official_speakers: list[str],
) -> tuple[str | None, float, str]:
    if re.fullmatch(r"Speaker\s+\d+", zoom_speaker, re.IGNORECASE):
        for official in official_speakers:
            if official.upper() == "THE COURT":
                return (
                    official,
                    0.6,
                    "Generic Zoom speaker label; THE COURT is a likely match.",
                )

    zoom_norm = _normalize_name(zoom_speaker)

    for official in official_speakers:
        if _normalize_name(official) == zoom_norm:
            return official, 1.0, "Exact match with official speaker list."

    for official in official_speakers:
        if zoom_norm in _title_variants(official) or _normalize_name(official) in _title_variants(
            zoom_speaker
        ):
            return official, 0.94, "Normalized name matches official speaker list."

    zoom_last = _surname(zoom_speaker)
    if not zoom_last:
        return None, 0.0, ""

    surname_matches = [
        official
        for official in official_speakers
        if _surname(official) == zoom_last
    ]
    if len(surname_matches) == 1:
        return (
            surname_matches[0],
            0.82,
            "Surname matches a single official speaker entry.",
        )

    if len(surname_matches) > 1:
        return (
            surname_matches[0],
            0.55,
            "Surname matches multiple official speakers; review carefully.",
        )

    return None, 0.0, ""


class SpeakerCorrectionGenerator:
    suggestion_type = SuggestionType.SPEAKER_CORRECTION

    def generate(self, document: TranscriptDocument, context: dict) -> list[Suggestion]:
        official_speakers = context.get("official_speakers") or document.metadata.get(
            "official_speakers", []
        )
        if not official_speakers:
            return []

        suggestions: list[Suggestion] = []

        for segment in document.segments:
            if not segment.speaker:
                continue

            if segment.speaker in official_speakers:
                continue

            suggested, confidence, reason = _find_official_match(
                segment.speaker,
                official_speakers,
            )
            if suggested is None or suggested == segment.speaker:
                continue

            suggestions.append(
                Suggestion(
                    id=f"spk-{uuid.uuid4().hex[:8]}",
                    type=SuggestionType.SPEAKER_CORRECTION,
                    original_text=segment.speaker,
                    replacement_text=suggested,
                    confidence=confidence,
                    reason=reason,
                    location=Location(
                        segment_id=segment.id,
                        field="speaker",
                        line_number=segment.raw_line_start,
                        context_after=segment.text[:40],
                    ),
                )
            )

        return suggestions
