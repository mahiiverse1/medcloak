"""Reproducible, synthetic clinical notes with known PHI spans.

This module intentionally contains invented data only. It lets us measure a
detector without storing or handling real patient records.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random


@dataclass(frozen=True)
class GroundTruthEntity:
    category: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SyntheticNote:
    id: str
    text: str
    entities: tuple[GroundTruthEntity, ...]


FIRST_NAMES = ("Aarav", "Diya", "Ishaan", "Kavya", "Neel", "Riya", "Vihaan", "Zoya")
LAST_NAMES = ("Bose", "Gupta", "Iyer", "Kapoor", "Mehta", "Nair", "Sharma", "Verma")
STREETS = ("Lake View Road", "Cedar Avenue", "Palm Grove Lane", "Sunrise Street")


class _NoteBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.entities: list[GroundTruthEntity] = []

    @property
    def position(self) -> int:
        return sum(len(part) for part in self.parts)

    def add(self, value: str, category: str | None = None) -> None:
        start = self.position
        self.parts.append(value)
        if category:
            self.entities.append(GroundTruthEntity(category, start, start + len(value), value))

    def build(self, note_id: str) -> SyntheticNote:
        text = "".join(self.parts)
        return SyntheticNote(note_id, text, tuple(self.entities))


def _phone(rng: Random) -> str:
    return f"+91 {rng.randint(60000, 99999)} {rng.randint(10000, 99999)}"


def generate_synthetic_notes(count: int = 120, seed: int = 42) -> list[SyntheticNote]:
    """Create a deterministic mixed-difficulty corpus for baseline evaluation.

    Four in five notes use demographic labels supported by the initial rules.
    Every fifth note deliberately uses an unlabelled patient name: this records
    a known baseline limitation instead of hiding it from the metric report.
    """

    if count < 1:
        raise ValueError("count must be at least 1")

    rng = Random(seed)
    notes: list[SyntheticNote] = []
    for index in range(count):
        first = rng.choice(FIRST_NAMES)
        full_name = f"{first} {rng.choice(LAST_NAMES)}"
        date = f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1970, 2004)}"
        mrn = f"MRN: MC-{rng.randint(10000, 99999)}"
        email = f"{first.lower()}.{rng.choice(LAST_NAMES).lower()}@example.test"
        phone = _phone(rng)
        address = f"{rng.randint(10, 99)} {rng.choice(STREETS)}, Pune {rng.randint(400001, 411099)}"
        builder = _NoteBuilder()

        if index % 5 == 0:
            # No patient label or honorific: a controlled hard case for the
            # rules-only baseline. A later NLP layer should improve this.
            builder.add("The care coordinator discussed results with ")
            builder.add(full_name, "NAME")
            builder.add(". Reports improved sleep after medication adjustment. ")
        else:
            builder.add("Patient: ")
            builder.add(full_name, "NAME")
            builder.add(". ")
            builder.add(date, "DATE")
            builder.add(". ")
            builder.add(mrn, "MRN")
            builder.add(". During review, ")
            builder.add(first, "NAME")
            builder.add(" reports no adverse effects. ")

        builder.add("Contact: ")
        builder.add(phone, "PHONE")
        builder.add("; email: ")
        builder.add(email, "EMAIL")
        builder.add(". ")
        builder.add("Address: ")
        builder.add(address, "ADDRESS")
        builder.add(".")
        notes.append(builder.build(f"synthetic-{index + 1:03d}"))
    return notes
