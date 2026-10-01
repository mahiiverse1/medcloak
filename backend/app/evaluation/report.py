"""Reproducible benchmark report for the MedCloak interface and API."""

from __future__ import annotations

from app.evaluation.metrics import Span, evaluate_exact_spans
from app.evaluation.synthetic_data import generate_synthetic_notes
from app.services.redactor import RedactionEngine


def build_evaluation_report() -> dict[str, object]:
    """Compare rules-only performance with local-NLP name recall on synthetic data."""
    notes = generate_synthetic_notes()
    expected = [Span(entity.category, entity.start, entity.end, note.id) for note in notes for entity in note.entities]
    rules_only = [
        Span(entity.category, entity.start, entity.end, note.id)
        for note in notes
        for entity in RedactionEngine(nlp_enabled=False).detect(note.text)
    ]
    hybrid = [
        Span(entity.category, entity.start, entity.end, note.id)
        for note in notes
        for entity in RedactionEngine().detect(note.text)
    ]
    expected_names = [span for span in expected if span.category == "NAME"]
    rules_only_names = [span for span in rules_only if span.category == "NAME"]
    hybrid_names = [span for span in hybrid if span.category == "NAME"]
    return {
        "dataset": "120 entirely synthetic clinical notes",
        "rules_only_overall": evaluate_exact_spans(expected, rules_only)["micro"],
        "name_recall": {
            "rules_only": evaluate_exact_spans(expected_names, rules_only_names)["micro"]["recall"],
            "hybrid_local_nlp": evaluate_exact_spans(expected_names, hybrid_names)["micro"]["recall"],
        },
        "method_note": "Controlled synthetic-template exact-span evaluation, not a clinical generalization study. Hybrid comparison is limited to names because the NLP layer also proposes locations and organizations.",
    }
