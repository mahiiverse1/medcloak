from app.evaluation.metrics import Span, evaluate_exact_spans
from app.evaluation.synthetic_data import generate_synthetic_notes
from app.services.redactor import RedactionEngine
from app.evaluation.report import build_evaluation_report


def test_synthetic_dataset_is_reproducible_and_spans_are_valid() -> None:
    first = generate_synthetic_notes(count=6, seed=7)
    second = generate_synthetic_notes(count=6, seed=7)

    assert first == second
    assert all(note.text[entity.start:entity.end] == entity.text for note in first for entity in note.entities)


def test_exact_span_metrics_count_true_and_false_results() -> None:
    expected = [Span("NAME", 0, 4), Span("PHONE", 10, 20)]
    predicted = [Span("NAME", 0, 4), Span("NAME", 30, 35)]

    assert evaluate_exact_spans(expected, predicted)["micro"] == {
        "true_positives": 1,
        "false_positives": 1,
        "false_negatives": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }


def test_rules_only_baseline_exposes_unlabelled_name_limit() -> None:
    notes = generate_synthetic_notes()
    expected = [Span(entity.category, entity.start, entity.end, note.id) for note in notes for entity in note.entities]
    predicted = [
        Span(entity.category, entity.start, entity.end, note.id)
        for note in notes
        for entity in RedactionEngine(nlp_enabled=False).detect(note.text)
    ]

    assert evaluate_exact_spans(expected, predicted)["micro"] == {
        "true_positives": 744,
        "false_positives": 0,
        "false_negatives": 24,
        "precision": 1.0,
        "recall": 0.9688,
        "f1": 0.9841,
    }


def test_hybrid_local_nlp_improves_the_synthetic_name_recall() -> None:
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
    baseline_metrics = evaluate_exact_spans(expected_names, rules_only_names)["micro"]
    hybrid_metrics = evaluate_exact_spans(expected_names, hybrid_names)["micro"]
    assert hybrid_metrics["recall"] > baseline_metrics["recall"]
    assert hybrid_metrics["false_positives"] == 0


def test_evaluation_report_exposes_the_comparison_for_the_interface() -> None:
    report = build_evaluation_report()

    assert report["dataset"] == "120 entirely synthetic clinical notes"
    assert report["rules_only_overall"]["f1"] > 0.9
    assert report["name_recall"]["hybrid_local_nlp"] > report["name_recall"]["rules_only"]
