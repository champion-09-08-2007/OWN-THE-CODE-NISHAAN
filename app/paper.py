"""Question bank, canary slots and per-holder text variants.

Stems may contain canary slots written as {first|second|...}. The first
alternative is the canonical wording that goes to print; other holders of a
soft copy receive their own combination of alternatives and option orders.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

import numpy as np

SLOT_RE = re.compile(r"\{([^{}]+)\}")

QUESTIONS = [
    ("{Which of the following|Which one of the following} is a scalar quantity?",
     ["Displacement", "Momentum", "Electric potential", "Acceleration"], 2),
    ("A body starts from rest and moves with a uniform acceleration of 2 m/s² for 5 s. "
     "The distance {covered|travelled} by the body is",
     ["10 m", "20 m", "25 m", "50 m"], 2),
    ("The {SI unit|S.I. unit} of magnetic flux is",
     ["tesla", "weber", "henry", "gauss"], 1),
    ("Two resistors of 6 Ω and 3 Ω are connected in parallel. Their {equivalent|effective} resistance is",
     ["2 Ω", "4.5 Ω", "9 Ω", "18 Ω"], 0),
    ("The {refractive index|index of refraction} of a glass slab is 1.5. The speed of light inside the slab is "
     "{approximately|nearly}",
     ["1 × 10⁸ m/s", "1.5 × 10⁸ m/s", "2 × 10⁸ m/s", "4.5 × 10⁸ m/s"], 2),
    ("{Which of the following|Which one of the following} statements about an ideal transformer is {correct|true}?",
     ["It works on steady direct current", "It changes the frequency of the supply",
      "Input power equals output power", "It raises both voltage and current"], 2),
    ("A convex lens has a focal length of 20 cm. Its {power|optical power} is",
     ["+2 D", "+5 D", "−5 D", "+0.5 D"], 1),
    ("The work done in moving a charge of 2 C across a potential difference of 12 V {is|equals}",
     ["6 J", "10 J", "14 J", "24 J"], 3),
    ("The half-life of a radioactive sample is 10 days. The fraction of the sample {remaining|left} "
     "after 30 days is",
     ["1/2", "1/4", "1/8", "1/16"], 2),
    ("The {phenomenon|effect} responsible for the blue {colour|color} of the clear sky is",
     ["Reflection", "Refraction", "Dispersion", "Scattering"], 3),
    ("The number of moles {in|present in} 22 g of carbon dioxide is",
     ["0.25", "0.5", "1.0", "2.0"], 1),
    ("{Which of the following|Which one of the following} elements has the highest electronegativity?",
     ["Oxygen", "Nitrogen", "Fluorine", "Chlorine"], 2),
    ("The {hybridisation|hybridization} of each carbon atom in ethyne is",
     ["sp", "sp²", "sp³", "dsp²"], 0),
    ("The pH of a 0.001 M solution of hydrochloric acid {is|will be}",
     ["1", "2", "3", "11"], 2),
    ("{Rusting|The rusting} of iron in moist air is an example of",
     ["Reduction", "Oxidation", "Sublimation", "Decomposition"], 1),
    ("The gas {evolved|released} when zinc reacts with dilute {sulphuric|sulfuric} acid is",
     ["Oxygen", "Hydrogen", "Sulphur dioxide", "Hydrogen sulphide"], 1),
    ("An element X has atomic number 12. The {formula|chemical formula} of its oxide is",
     ["XO", "X₂O", "XO₂", "X₂O₃"], 0),
    ("The {organelle|cell organelle} known as the powerhouse of the cell is the",
     ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome"], 1),
    ("{Which of the following|Which one of the following} blood groups is {known as|called} the universal donor?",
     ["A", "B", "AB", "O"], 3),
    ("Photosynthesis {takes place|occurs} in which part of the plant cell?",
     ["Nucleus", "Chloroplast", "Vacuole", "Cell wall"], 1),
    ("The enzyme that {breaks down|digests} starch in the human mouth is",
     ["Pepsin", "Trypsin", "Salivary amylase", "Lipase"], 2),
    ("The number of chromosomes in a {normal|typical} human somatic cell is",
     ["23", "44", "46", "48"], 2),
    ("Insulin is {secreted|produced} by",
     ["Alpha cells of the pancreas", "Beta cells of the pancreas",
      "The adrenal cortex", "The thyroid gland"], 1),
    ("{Which of the following|Which one of the following} is not a greenhouse gas?",
     ["Carbon dioxide", "Methane", "Nitrogen", "Water vapour"], 2),
]

INSTRUCTIONS = [
    "This booklet contains 24 questions. Each question carries 4 marks and one mark is deducted for every wrong answer.",
    "Mark your answers on the separate answer sheet with a blue or black ballpoint pen only.",
    "Do not fold, photograph or copy any part of this booklet. Every copy is uniquely traceable to its holder.",
    "Return the booklet with the answer sheet to the invigilator before leaving the examination room.",
]


@dataclass
class Slot:
    q: int
    j: int
    alts: list[str]


@dataclass
class Question:
    idx: int
    raw: str
    options: list[str]
    answer: int
    segments: list = field(default_factory=list)  # str | Slot

    @property
    def slots(self) -> list[Slot]:
        return [s for s in self.segments if isinstance(s, Slot)]

    def stem(self, choices: list[int] | None = None) -> str:
        out, k = [], 0
        for seg in self.segments:
            if isinstance(seg, Slot):
                c = choices[k] if choices else 0
                out.append(seg.alts[c])
                k += 1
            else:
                out.append(seg)
        return "".join(out)


def parse_questions() -> list[Question]:
    qs = []
    for i, (raw, opts, ans) in enumerate(QUESTIONS):
        segs, pos, j = [], 0, 0
        for m in SLOT_RE.finditer(raw):
            if m.start() > pos:
                segs.append(raw[pos:m.start()])
            segs.append(Slot(i, j, m.group(1).split("|")))
            j += 1
            pos = m.end()
        if pos < len(raw):
            segs.append(raw[pos:])
        qs.append(Question(i, raw, opts, ans, segs))
    return qs


@dataclass
class Variant:
    """Wording and option order a holder receives."""
    key: str
    choices: dict[int, list[int]]      # question -> chosen alternative per slot
    order: dict[int, list[int]]        # question -> original option index at each printed position

    def stem(self, q: Question) -> str:
        return q.stem(self.choices.get(q.idx))

    def options(self, q: Question) -> list[str]:
        return [q.options[i] for i in self.order[q.idx]]

    def answer_position(self, q: Question) -> int:
        return self.order[q.idx].index(q.answer)


def _rng(secret: str, label: str) -> np.random.Generator:
    digest = hmac.new(secret.encode(), label.encode(), hashlib.sha256).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def master_variant(questions: list[Question]) -> Variant:
    return Variant("master",
                   {q.idx: [0] * len(q.slots) for q in questions},
                   {q.idx: [0, 1, 2, 3] for q in questions})


def print_variant(secret: str, centre_code: str, questions: list[Question]) -> Variant:
    """Canonical wording, centre-specific option order."""
    rng = _rng(secret, f"centre:{centre_code}")
    order = {}
    for q in questions:
        perm = list(rng.permutation(4))
        if perm == [0, 1, 2, 3]:
            perm = [1, 0, 3, 2]
        order[q.idx] = [int(x) for x in perm]
    return Variant(f"centre:{centre_code}", {q.idx: [0] * len(q.slots) for q in questions}, order)


def softcopy_variant(secret: str, holder_id: str, questions: list[Question]) -> Variant:
    """Unique wording and option order for a pre-print holder."""
    rng = _rng(secret, f"holder:{holder_id}")
    choices, order = {}, {}
    for q in questions:
        cs = []
        for s in q.slots:
            cs.append(int(rng.integers(1, len(s.alts))) if rng.random() < 0.62 else 0)
        choices[q.idx] = cs
        order[q.idx] = [int(x) for x in rng.permutation(4)]
    return Variant(f"holder:{holder_id}", choices, order)
