"""Transparent rule-based PHI detection used in MedCloak.

The detector is intentionally conservative and easy to inspect. It is not a
compliance guarantee; local NLP and an advisory GenAI review layer complement it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from app.schemas import DetectedEntity, EntityCategory, PrivacyProfile
from app.services.nlp_detector import NlpPersonDetector


@dataclass(frozen=True)
class DetectionRule:
    category: EntityCategory
    pattern: Pattern[str]
    heuristic_score: float
    detector: str


def _compiled(pattern: str) -> Pattern[str]:
    return re.compile(pattern, flags=re.IGNORECASE | re.MULTILINE)


RULES: tuple[DetectionRule, ...] = (
    DetectionRule(
        "EMAIL",
        _compiled(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        0.99,
        "regex.email",
    ),
    DetectionRule(
        "PHONE",
        _compiled(r"(?<!\w)(?:\+91[-\s]?)?(?:0[-\s]?)?[6-9]\d{4}[-\s]?\d{5}(?!\w)"),
        0.98,
        "regex.indian_phone",
    ),
    DetectionRule(
        "MRN",
        _compiled(r"\b(?:MRN|medical\s+record\s+(?:number|no\.?))\s*[:#-]?\s*[A-Z]{0,4}[-/]?\d{4,12}\b"),
        0.99,
        "regex.mrn",
    ),
    DetectionRule(
        "PATIENT_ID",
        _compiled(r"\b(?:patient\s*(?:id|identifier)|UHID)\s*[:#-]?\s*[A-Z]{0,4}[-/]?\d{4,12}\b"),
        0.99,
        "regex.patient_id",
    ),
    DetectionRule(
        "ADDRESS",
        _compiled(r"\b(?:address|resides\s+at|lives\s+(?:at|on))\s*(?::|-)?\s*([^\n.]{8,120})"),
        0.92,
        "regex.address_field",
    ),
    DetectionRule(
        "ADDRESS",
        _compiled(
            r"\b((?-i:[A-Z][a-z]+)(?:[ \t]+(?-i:[A-Z][a-z]+)){0,5}[ \t]+"
            r"(?:Street|Road|Rd\.?|Boulevard|Blvd\.?|Avenue|Ave\.?|Lane|Ln\.?)\b)"
        ),
        0.84,
        "regex.street_suffix",
    ),
    DetectionRule(
        "POSTAL_CODE",
        _compiled(r"\b[1-9]\d{5}\b"),
        0.93,
        "regex.indian_postal_code",
    ),
    DetectionRule(
        "DATE",
        _compiled(
            r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
            r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
            r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}|"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
            r"dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b"
        ),
        0.95,
        "regex.date",
    ),
    DetectionRule(
        "NAME",
        _compiled(
            r"\b(?:patient|name|patient\s+name)\s*:\s*"
            r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})\b"
        ),
        0.90,
        "regex.named_field",
    ),
    DetectionRule(
        "NAME",
        _compiled(
            r"\b(?:follow[- ]?up\s+note\s+for|follow[- ]?up\s+with|"
            r"patient\s+seen\s+today\s*:\s*)\s*"
            r"([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})\b"
        ),
        0.88,
        "regex.clinical_name_context",
    ),
    DetectionRule(
        "NAME",
        _compiled(
            r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})\s+"
            r"(?:visited|presented|reported|complained|attended)\b"
        ),
        0.87,
        "regex.clinical_narrative_name",
    ),
    DetectionRule(
        "NAME",
        _compiled(
            r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,3})(?=,\s*aged\b)"
        ),
        0.88,
        "regex.demographic_name_context",
    ),
    DetectionRule(
        "LOCATION",
        re.compile(
            r"\b(?i:near|outside|beside|at)\s+("
            r"[A-Z][A-Za-z]*(?:[ \t-]+[A-Z][A-Za-z-]*){0,6}[ \t]+"
            r"(?:Residences?|Apartments?|Housing[ \t]+Society))\b",
            flags=re.MULTILINE,
        ),
        0.82,
        "regex.named_residence_context",
    ),
    DetectionRule(
        "ORGANIZATION",
        _compiled(r"\b(?:works|worked|employed)\s+at\s+[\"']([^\"'\n]{2,100})[\"']"),
        0.86,
        "regex.organization_context",
    ),
    DetectionRule(
        "NAME",
        re.compile(
            r"\b(?i:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+"
            r"([A-Z]\.(?:[ \t]+[A-Z][a-z]+){1,3}|[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,3})\b",
            flags=re.MULTILINE,
        ),
        0.86,
        "regex.honorific_name",
    ),
)

STRICT_ONLY_CATEGORIES = {"LOCATION", "ORGANIZATION"}


def _span_for_match(rule: DetectionRule, match: re.Match[str]) -> tuple[int, int]:
    """Use a capture group when a rule separates identifying text from context."""

    if rule.category in {"NAME", "ADDRESS", "LOCATION", "ORGANIZATION"} and match.lastindex:
        return match.start(1), match.end(1)
    return match.start(), match.end()


def _select_non_overlapping(candidates: list[DetectedEntity]) -> list[DetectedEntity]:
    """Prefer the earliest, most-specific span; use score only as a tie-breaker."""

    selected: list[DetectedEntity] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start), -item.heuristic_score)):
        overlaps = any(candidate.start < existing.end and candidate.end > existing.start for existing in selected)
        if not overlaps:
            selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


class RedactionEngine:
    """Detect and redact identifiers without storing the submitted note."""

    def __init__(self, nlp_detector: NlpPersonDetector | None = None, *, nlp_enabled: bool = True) -> None:
        self.nlp_detector = nlp_detector or NlpPersonDetector()
        self.nlp_enabled = nlp_enabled

    def detect(self, text: str, privacy_profile: PrivacyProfile = "strict") -> list[DetectedEntity]:
        candidates: list[DetectedEntity] = []
        for rule in RULES:
            for match in rule.pattern.finditer(text):
                start, end = _span_for_match(rule, match)
                original = text[start:end]
                candidates.append(
                    DetectedEntity(
                        category=rule.category,
                        start=start,
                        end=end,
                        text=original,
                        replacement=f"[{rule.category}]",
                        heuristic_score=rule.heuristic_score,
                        detector=rule.detector,
                    )
                )

        # Statistical local NER catches context-based person names that do not
        # have a predictable label such as "Patient:". It is optional: without
        # the model installed, the deterministic baseline continues to work.
        if self.nlp_enabled:
            candidates.extend(self.nlp_detector.detect(text))

        # A labelled patient name is strong rule-based evidence. Once it is found,
        # redact the same full name everywhere else in the note as well. This is
        # safer than hoping every later mention repeats the "Patient:" label.
        labelled_patient_names = [
            entity.text
            for entity in candidates
            if entity.category == "NAME"
            and entity.detector
            in {
                "regex.named_field",
                "regex.clinical_name_context",
                "regex.clinical_narrative_name",
                "regex.demographic_name_context",
            }
        ]
        for name in sorted(set(labelled_patient_names)):
            name_pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", flags=re.IGNORECASE)
            for match in name_pattern.finditer(text):
                candidates.append(
                    DetectedEntity(
                        category="NAME",
                        start=match.start(),
                        end=match.end(),
                        text=text[match.start():match.end()],
                        replacement="[NAME]",
                        heuristic_score=0.94,
                        detector="rule.patient_name_propagation",
                    )
                )

            # Clinical notes commonly use the patient's given name after the
            # opening demographic block (for example, "Riya reports...").
            # Because the full patient identity was explicitly labelled above,
            # conservatively redact that given name throughout this one note.
            given_name = name.split()[0]
            given_name_pattern = re.compile(rf"(?<!\w){re.escape(given_name)}(?!\w)", flags=re.IGNORECASE)
            for match in given_name_pattern.finditer(text):
                candidates.append(
                    DetectedEntity(
                        category="NAME",
                        start=match.start(),
                        end=match.end(),
                        text=text[match.start():match.end()],
                        replacement="[NAME]",
                        heuristic_score=0.80,
                        detector="rule.patient_given_name_propagation",
                    )
                )
        selected = _select_non_overlapping(candidates)
        if privacy_profile == "core":
            return [entity for entity in selected if entity.category not in STRICT_ONLY_CATEGORIES]
        return selected

    def redact(
        self,
        text: str,
        entities: list[DetectedEntity] | None = None,
        privacy_profile: PrivacyProfile = "strict",
    ) -> tuple[str, list[DetectedEntity]]:
        entities = entities if entities is not None else self.detect(text, privacy_profile)
        redacted = text
        # Replace right-to-left so original offsets remain valid.
        for entity in reversed(entities):
            redacted = f"{redacted[:entity.start]}{entity.replacement}{redacted[entity.end:]}"
        return redacted, entities
