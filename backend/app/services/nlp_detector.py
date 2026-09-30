"""Optional local NLP detector for names, organizations, and locations.

The statistical spaCy model complements transparent rules. It runs locally and
only proposes PERSON entities; redaction remains deterministic and auditable.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from app.schemas import DetectedEntity


MODEL_NAME = os.getenv("MEDCLOAK_NLP_MODEL", "en_core_web_sm")
NAME_SHAPE = re.compile(r"[A-Z][a-z]+(?: [A-Z][a-z]+){0,3}\Z")
MEDICATION_LIST_CONTEXT = re.compile(
    r"\b(?:administered|prescribed|given|received|started\s+on)\s+([^.!?\n]+)",
    flags=re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _load_model():
    """Load once, returning None when the optional model is not installed."""

    try:
        import spacy

        return spacy.load(MODEL_NAME)
    except (ImportError, OSError):
        return None


class NlpPersonDetector:
    """Find conservative probable identifiers with a local statistical NER model."""

    def detect(self, text: str) -> list[DetectedEntity]:
        model = _load_model()
        if model is None:
            return []

        # Capitalized brand names can resemble people to a general-purpose NER
        # model. Treat text following a medication-administration verb as a
        # medication list, not as an automatic patient-name candidate.
        medication_ranges = [
            (match.start(1), match.end(1))
            for match in MEDICATION_LIST_CONTEXT.finditer(text)
        ]
        entities: list[DetectedEntity] = []
        label_mapping = {
            "PERSON": "NAME",
            "ORG": "ORGANIZATION",
            "FAC": "ORGANIZATION",
            "GPE": "LOCATION",
            "LOC": "LOCATION",
        }
        for entity in model(text).ents:
            candidate_text = entity.text.strip()
            # spaCy may occasionally include a newline or nearby clinical
            # abbreviation in an entity. Only accept clean title-cased names;
            # this keeps the statistical signal from consuming adjacent PHI.
            category = label_mapping.get(entity.label_)
            if category is None:
                continue
            if category == "NAME" and not NAME_SHAPE.fullmatch(candidate_text):
                continue
            if category == "NAME" and any(entity.start_char >= start and entity.end_char <= end for start, end in medication_ranges):
                continue
            if category == "ORGANIZATION":
                before = text[:entity.start_char]
                quoted = (
                    entity.start_char > 0
                    and entity.end_char < len(text)
                    and text[entity.start_char - 1] in {"'", '"'}
                    and text[entity.end_char] in {"'", '"'}
                )
                employment_context = bool(re.search(r"\b(?:works|worked|employed)\s+at\s*$", before, flags=re.IGNORECASE))
                if not (quoted or employment_context):
                    continue
            entities.append(
                DetectedEntity(
                    category=category,
                    start=entity.start_char,
                    end=entity.end_char,
                    text=entity.text,
                    replacement=f"[{category}]",
                    confidence=0.78 if category == "NAME" else 0.72,
                    detector=f"nlp.spacy_{entity.label_.lower()}",
                )
            )
        return entities
