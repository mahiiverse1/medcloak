"""Exact-span metrics for transparent PHI detector evaluation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class Span:
    category: str
    start: int
    end: int
    document_id: str = ""


@dataclass(frozen=True)
class MetricCounts:
    true_positives: int
    false_positives: int
    false_negatives: int

    def as_dict(self) -> dict[str, float | int]:
        precision = self.true_positives / (self.true_positives + self.false_positives) if self.true_positives + self.false_positives else 0.0
        recall = self.true_positives / (self.true_positives + self.false_negatives) if self.true_positives + self.false_negatives else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {**asdict(self), "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def evaluate_exact_spans(expected: Iterable[Span], predicted: Iterable[Span]) -> dict[str, object]:
    """Calculate micro and per-category exact-match precision, recall and F1."""

    expected_by_category: dict[str, set[Span]] = defaultdict(set)
    predicted_by_category: dict[str, set[Span]] = defaultdict(set)
    for span in expected:
        expected_by_category[span.category].add(span)
    for span in predicted:
        predicted_by_category[span.category].add(span)

    per_category: dict[str, dict[str, float | int]] = {}
    total = MetricCounts(0, 0, 0)
    for category in sorted(set(expected_by_category) | set(predicted_by_category)):
        expected_spans = expected_by_category[category]
        predicted_spans = predicted_by_category[category]
        counts = MetricCounts(len(expected_spans & predicted_spans), len(predicted_spans - expected_spans), len(expected_spans - predicted_spans))
        per_category[category] = counts.as_dict()
        total = MetricCounts(total.true_positives + counts.true_positives, total.false_positives + counts.false_positives, total.false_negatives + counts.false_negatives)
    return {"micro": total.as_dict(), "per_category": per_category}
