"""Run MedCloak's reproducible rules-only evaluation on synthetic notes."""

from __future__ import annotations

import json
from pathlib import Path

from app.evaluation.metrics import Span, evaluate_exact_spans
from app.evaluation.synthetic_data import generate_synthetic_notes
from app.services.redactor import RedactionEngine


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "data" / "evaluation" / "baseline_report.json"


def main() -> None:
    notes = generate_synthetic_notes()
    engine = RedactionEngine(nlp_enabled=False)
    expected = [Span(entity.category, entity.start, entity.end, note.id) for note in notes for entity in note.entities]
    predicted = [
        Span(entity.category, entity.start, entity.end, note.id)
        for note in notes
        for entity in engine.detect(note.text)
    ]
    report = {
        "dataset": {"name": "medcloak_synthetic_v1", "notes": len(notes), "seed": 42, "contains_real_patient_data": False},
        "method": "rules_only_exact_span",
        "metrics": evaluate_exact_spans(expected, predicted),
        "interpretation": "Exact spans only. Controlled unlabelled names are included to expose a known rules-only limitation.",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
