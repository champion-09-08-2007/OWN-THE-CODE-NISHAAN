"""Exam model: centres, holders, typeset layouts and tracer references."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

try:
    import pymupdf
except ImportError:  # older PyMuPDF
    import fitz as pymupdf  # type: ignore

from .paper import Variant, master_variant, parse_questions, print_variant, softcopy_variant
from .typeset import OPTION_KEY_BASE, PageLayout, build_layout, pdf_bytes

REF_DPI = 200
SCALE = REF_DPI / 72.0
# Fingerprint strength in points. Keep the same values between printing and tracing.
AMP_X = float(os.environ.get("NISHAAN_SHIFT_X", "0.34"))   # horizontal word shift
AMP_Y = float(os.environ.get("NISHAAN_SHIFT_Y", "0.36"))   # vertical line shift

DEFAULT_CENTRES = [
    # code, city, area, press, (lat, lon) used only for ordering
    ("DEL-11", "Delhi", "Dwarka", "P1"),
    ("LKO-04", "Lucknow", "Gomti Nagar", "P1"),
    ("JAI-07", "Jaipur", "Malviya Nagar", "P1"),
    ("PAT-02", "Patna", "Kankarbagh", "P1"),
    ("PUN-03", "Pune", "Shivajinagar", "P2"),
    ("HYD-06", "Hyderabad", "Begumpet", "P2"),
    ("BLR-09", "Bengaluru", "Jayanagar", "P2"),
    ("CHE-05", "Chennai", "Adyar", "P2"),
]

DEFAULT_HOLDERS = [
    # id, stage, role, label
    ("S1", 0, "setter", "Paper setter"),
    ("M1", 1, "moderator", "Moderator 1"),
    ("M2", 1, "moderator", "Moderator 2"),
    ("T1", 2, "translator", "Translator, Hindi"),
    ("T2", 2, "translator", "Translator, Marathi"),
    ("T3", 2, "translator", "Translator, Tamil"),
    ("P1", 3, "press", "Press North"),
    ("P2", 3, "press", "Press South"),
]


@dataclass
class WordGeo:
    key: int
    line: int
    movable: bool
    box: tuple[int, int, int, int]   # x0, y0, x1, y1 in reference px (padded)
    cx: float
    cy: float
    text: str
    kind: str
    q: int = -1
    pos: int = -1


@dataclass
class PageRef:
    common: np.ndarray                         # blurred gray reference without options
    variants: dict[str, np.ndarray]            # centre -> blurred gray reference with options
    words: list[WordGeo]                       # common words
    option_words: dict[str, list[WordGeo]]     # centre -> option words
    kp: list = field(default_factory=list)
    matcher: object = None
    n_words: int = 0


def _render_gray(pdf: bytes, dpi: int) -> list[np.ndarray]:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
        out.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy())
    return out


def _geo(w, variable_boxes) -> WordGeo | None:
    x0, y0, x1, y1 = w.bbox()
    for (vx0, vy0, vx1, vy1) in variable_boxes:
        if x0 < vx1 and x1 > vx0 and y0 < vy1 and y1 > vy0:
            return None
    pad = 3
    box = (int(np.floor(x0 * SCALE)) - pad, int(np.floor(y0 * SCALE)) - pad,
           int(np.ceil(x1 * SCALE)) + pad, int(np.ceil(y1 * SCALE)) + pad)
    return WordGeo(w.key, w.line, w.movable, box, (x0 + x1) / 2 * SCALE, (y0 + y1) / 2 * SCALE,
                   w.text, w.kind, w.q, w.pos)


class ExamModel:
    def __init__(self, secret: str, title: str, subtitle: str, centres: list[dict], holders: list[dict]):
        self.secret, self.title, self.subtitle = secret, title, subtitle
        self.centres = centres
        self.holders = holders
        self.questions = parse_questions()
        self.master: Variant = master_variant(self.questions)
        self.print_variants = {c["code"]: print_variant(secret, c["code"], self.questions) for c in centres}
        self.soft_variants = {h["id"]: softcopy_variant(secret, h["id"], self.questions)
                              for h in holders if h["stage"] in (1, 2)}
        self.layouts: dict[str, list[PageLayout]] = {
            code: build_layout(title, subtitle, self.questions, v) for code, v in self.print_variants.items()}
        base = next(iter(self.layouts.values()))
        for code, lay in self.layouts.items():
            assert len(lay) == len(base), "variants must paginate identically"
            for a, b in zip(lay, base):
                assert a.n_lines == b.n_lines
        self.base_layout = base
        self.n_pages = len(base)
        self.pages: list[PageRef] = []
        self.lock = threading.Lock()
        self._sift = None

    # ------------------------------------------------------------ references
    def build_refs(self) -> None:
        sift = cv2.SIFT_create(nfeatures=14000)
        common_pdf = pdf_bytes(self.base_layout, [(None, None)], 0, 0, include_options=False)
        commons = _render_gray(common_pdf, REF_DPI)
        var_imgs = {code: _render_gray(pdf_bytes(lay, [(None, None)], 0, 0), REF_DPI)
                    for code, lay in self.layouts.items()}
        pages = []
        for p in range(self.n_pages):
            lay = self.base_layout[p]
            words = [g for w in lay.words if w.kind == "common" and (g := _geo(w, lay.variable_boxes))]
            opt = {code: [g for w in self.layouts[code][p].words if w.kind == "option"
                          and (g := _geo(w, lay.variable_boxes))] for code in self.layouts}
            common = commons[p]
            mask = np.full(common.shape, 255, np.uint8)
            for (vx0, vy0, vx1, vy1) in lay.variable_boxes:
                mask[int(vy0 * SCALE):int(vy1 * SCALE), int(vx0 * SCALE):int(vx1 * SCALE)] = 0
            kp, desc = sift.detectAndCompute(common, mask)
            matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
            matcher.add([desc])
            matcher.train()
            blur = lambda im: cv2.GaussianBlur(im, (0, 0), 1.0)
            pages.append(PageRef(blur(common), {c: blur(var_imgs[c][p]) for c in var_imgs}, words, opt,
                                 [k.pt for k in kp], matcher,
                                 len(words) + len(next(iter(opt.values())))))
        self.pages = pages
        self._sift = cv2.SIFT_create(nfeatures=9000)

    @property
    def sift(self):
        return self._sift

    # ------------------------------------------------------------ helpers
    def centre(self, code: str) -> dict | None:
        return next((c for c in self.centres if c["code"] == code), None)

    def holder(self, hid: str) -> dict | None:
        return next((h for h in self.holders if h["id"] == hid), None)

    def answer_key(self, code: str) -> list[int]:
        v = self.print_variants[code]
        return [v.answer_position(q) + 1 for q in self.questions]


def option_key(q: int, pos: int, j: int) -> int:
    return OPTION_KEY_BASE + (q * 4 + pos) * 16 + j
