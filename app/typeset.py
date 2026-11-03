"""Deterministic typesetting of a question booklet and PDF output.

Every word is placed explicitly so that the tracer knows its exact position
on the unmarked master, and each printed copy can shift individual words and
lines by a sub-point amount drawn from the copy's secret code.
"""
from __future__ import annotations

import hashlib
import hmac
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import segno
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas

from .paper import INSTRUCTIONS, Question, Variant

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("Serif", str(FONT_DIR / "LiberationSerif-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Bold", str(FONT_DIR / "LiberationSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Italic", str(FONT_DIR / "LiberationSerif-Italic.ttf")))
    _registered = True


PAGE_W, PAGE_H = 595.28, 841.89
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 56.0, 56.0, 46.0, 58.0
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R
BODY, LEAD = 10.5, 14.6
ASCENT, DESCENT = 0.891, 0.216
OPTION_KEY_BASE = 4000


@dataclass
class Word:
    text: str
    x: float
    base: float
    w: float
    font: str
    size: float
    line: int
    key: int
    movable: bool
    kind: str = "common"   # common | option
    q: int = -1
    pos: int = -1

    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x, self.base - ASCENT * self.size, self.x + self.w, self.base + DESCENT * self.size)


@dataclass
class Shape:
    kind: str                 # rect | hline
    coords: tuple
    width: float = 0.8


@dataclass
class PageLayout:
    words: list[Word] = field(default_factory=list)
    shapes: list[Shape] = field(default_factory=list)
    serial_slots: list[tuple] = field(default_factory=list)   # (x, base, size, font)
    qr_slots: list[tuple] = field(default_factory=list)       # (x, top, size)
    variable_boxes: list[tuple] = field(default_factory=list) # pt boxes the tracer ignores
    n_lines: int = 0


def sw(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


class _Builder:
    def __init__(self) -> None:
        self.pages: list[PageLayout] = []
        self.new_page()

    def new_page(self) -> None:
        self.page = PageLayout()
        self.pages.append(self.page)
        self.common_key = 0

    def line_id(self) -> int:
        lid = self.page.n_lines
        self.page.n_lines += 1
        return lid

    def add(self, text, x, base, font, size, line, movable, kind="common", q=-1, pos=-1, key=None):
        w = sw(text, font, size)
        if key is None:
            key = self.common_key
            self.common_key += 1
        self.page.words.append(Word(text, x, base, w, font, size, line, key, movable, kind, q, pos))
        return w

    def paragraph(self, text, x, top, width, font=("Serif", BODY), lead=LEAD, justify=True):
        """Greedy line breaking with full justification. Returns the next top."""
        fname, size = font
        words = text.split()
        space = sw(" ", fname, size)
        lines, cur, cur_w = [], [], 0.0
        for wd in words:
            ww = sw(wd, fname, size)
            if cur and cur_w + space + ww > width:
                lines.append(cur)
                cur, cur_w = [wd], ww
            else:
                cur_w = cur_w + space + ww if cur else ww
                cur.append(wd)
        if cur:
            lines.append(cur)
        for li, ln in enumerate(lines):
            base = top + ASCENT * size + 1.0
            lid = self.line_id()
            widths = [sw(wd, fname, size) for wd in ln]
            last = li == len(lines) - 1
            gap = space
            if justify and not last and len(ln) > 1:
                extra = width - sum(widths) - space * (len(ln) - 1)
                if extra / (len(ln) - 1) < space * 2.2:
                    gap = space + extra / (len(ln) - 1)
            cx = x
            for k, wd in enumerate(ln):
                movable = k > 0 and (last or k < len(ln) - 1)
                self.add(wd, cx, base, fname, size, lid, movable)
                cx += widths[k] + gap
            top += lead
        return top


def _paragraph_lines(text, width, fname, size) -> int:
    words, space = text.split(), sw(" ", fname, size)
    n, cur_w, started = 1, 0.0, False
    for wd in words:
        ww = sw(wd, fname, size)
        if started and cur_w + space + ww > width:
            n += 1
            cur_w = ww
        else:
            cur_w = cur_w + space + ww if started else ww
            started = True
    return n


def build_layout(title: str, subtitle: str, questions: list[Question], variant: Variant) -> list[PageLayout]:
    register_fonts()
    b = _Builder()
    pg = b.page

    # Booklet box (variable content inside)
    bx0, by0, bx1, by1 = PAGE_W - MARGIN_R - 176, MARGIN_T - 4, PAGE_W - MARGIN_R, MARGIN_T + 66
    pg.shapes.append(Shape("rect", (bx0, by0, bx1, by1), 1.0))
    lid = b.line_id()
    b.add("Booklet", bx0 + 9, by0 + 15, "Serif", 9, lid, False)
    b.add("No.", bx0 + 9 + sw("Booklet ", "Serif", 9), by0 + 15, "Serif", 9, lid, True)
    pg.serial_slots.append((bx0 + 9, by0 + 45, 19, "Serif-Bold"))
    pg.qr_slots.append((bx1 - 60, by0 + 6, 54))
    pg.variable_boxes.append((bx0 + 4, by0 + 20, bx1 - 2, by1 - 2))

    head_w = TEXT_W - 196
    top = MARGIN_T
    top = b.paragraph(title, MARGIN_L, top, head_w, ("Serif-Bold", 16), lead=20, justify=False)
    top = b.paragraph(subtitle, MARGIN_L, top, head_w, ("Serif", 11.5), lead=16, justify=False)
    top = b.paragraph("Duration: 3 hours", MARGIN_L, top, head_w, ("Serif", 10.5), lead=15, justify=False)
    top = max(top, by1) + 8
    pg.shapes.append(Shape("hline", (MARGIN_L, top, PAGE_W - MARGIN_R), 1.3))
    top += 10

    # Instructions box
    box_top = top
    top += 6
    top = b.paragraph("Instructions to candidates", MARGIN_L + 10, top, TEXT_W - 20, ("Serif-Bold", BODY), justify=False)
    for i, ins in enumerate(INSTRUCTIONS):
        lid = b.line_id()
        b.page.n_lines -= 1  # number token shares the first line of the paragraph
        b.add(f"{i + 1}.", MARGIN_L + 10, top + ASCENT * BODY + 1.0, "Serif", BODY, lid, False)
        top = b.paragraph(ins, MARGIN_L + 28, top, TEXT_W - 38, ("Serif", BODY))
    top += 5
    pg.shapes.append(Shape("rect", (MARGIN_L, box_top, PAGE_W - MARGIN_R, top), 0.8))
    top += 14

    def page_header():
        nonlocal top
        b.new_page()
        p = b.page
        lid = b.line_id()
        x = MARGIN_L
        for k, wd in enumerate(f"{title}: {subtitle}".split()):
            x += b.add(wd, x, MARGIN_T + 9, "Serif-Italic", 9.5, lid, k > 0) + sw(" ", "Serif-Italic", 9.5)
        lab_x = PAGE_W - MARGIN_R - 128
        b.add("Booklet", lab_x, MARGIN_T + 9, "Serif", 9.5, lid, False)
        p.serial_slots.append((lab_x + sw("Booklet ", "Serif", 9.5) + 2, MARGIN_T + 9, 11, "Serif-Bold"))
        p.variable_boxes.append((lab_x + 34, MARGIN_T - 4, PAGE_W - MARGIN_R, MARGIN_T + 14))
        top = MARGIN_T + 16
        p.shapes.append(Shape("hline", (MARGIN_L, top, PAGE_W - MARGIN_R), 0.9))
        top += 14

    indent = 22
    for q in questions:
        stem = variant.stem(q)
        opts = variant.options(q)
        widest = max(sw(o, "Serif", BODY) for o in q.options) + 22
        span = TEXT_W - indent
        ncol = 4 if widest <= span / 4 - 8 else (2 if widest <= span / 2 - 10 else 1)
        col_w = span / ncol
        n_stem = _paragraph_lines(stem, TEXT_W - indent, "Serif", BODY)
        rows = 4 // ncol
        height = n_stem * LEAD + 3 + rows * LEAD + 9
        if top + height > PAGE_H - MARGIN_B:
            page_header()
        first_base = top + ASCENT * BODY + 1.0
        lid_first = b.page.n_lines
        b.add(f"{q.idx + 1}.", MARGIN_L, first_base, "Serif-Bold", BODY, lid_first, False)
        top = b.paragraph(stem, MARGIN_L + indent, top, TEXT_W - indent)
        top += 3
        for r in range(rows):
            lid = b.line_id()
            base = top + ASCENT * BODY + 1.0
            cells = [(r * ncol + c, c) for c in range(ncol)]
            for pos, col in cells:
                cx = MARGIN_L + indent + col * col_w
                b.add(f"({pos + 1})", cx, base, "Serif", BODY, lid, False)
                ox = cx + 22
                space = sw(" ", "Serif", BODY)
                for j, wd in enumerate(opts[pos].split()):
                    key = OPTION_KEY_BASE + (q.idx * 4 + pos) * 16 + j
                    ox += b.add(wd, ox, base, "Serif", BODY, lid, True, "option", q.idx, pos, key) + space
            top += LEAD
        top += 9

    n = len(b.pages)
    for i, p in enumerate(b.pages):
        b.page = p
        b.common_key = max([w.key for w in p.words if w.kind == "common"], default=-1) + 1
        lid = b.line_id()
        text = f"Page {i + 1} of {n}"
        x = (PAGE_W - sw(text, "Serif", 9.5)) / 2
        for k, wd in enumerate(text.split()):
            x += b.add(wd, x, PAGE_H - 30, "Serif", 9.5, lid, k > 0) + sw(" ", "Serif", 9.5)
        p.serial_slots.append((PAGE_W - MARGIN_R - 52, PAGE_H - 30, 9.5, "Serif"))
        p.variable_boxes.append((PAGE_W - MARGIN_R - 56, PAGE_H - 42, PAGE_W - MARGIN_R + 4, PAGE_H - 24))
    return b.pages


# ---------------------------------------------------------------- fingerprint
def _rng(secret: str, label: str) -> np.random.Generator:
    d = hmac.new(secret.encode(), label.encode(), hashlib.sha256).digest()
    return np.random.default_rng(int.from_bytes(d[:8], "big"))


@dataclass
class CopyCode:
    sx: np.ndarray   # sign per word key
    sy: np.ndarray   # sign per line id


def copy_code(secret: str, booklet: str, page: int) -> CopyCode:
    rng = _rng(secret, f"copy:{booklet}:p{page}")
    return CopyCode(rng.choice([-1.0, 1.0], size=6000), rng.choice([-1.0, 1.0], size=512))


def word_offsets(code: CopyCode | None, word: Word, amp_x: float, amp_y: float) -> tuple[float, float]:
    if code is None:
        return 0.0, 0.0
    dx = code.sx[word.key] * amp_x if word.movable else 0.0
    return dx, code.sy[word.line] * amp_y


# ---------------------------------------------------------------- PDF output
def draw_page(c, page: PageLayout, code: CopyCode | None, booklet: str | None,
              amp_x: float, amp_y: float, include_options: bool = True) -> None:
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    for s in page.shapes:
        c.setLineWidth(s.width)
        if s.kind == "rect":
            x0, y0, x1, y1 = s.coords
            c.rect(x0, PAGE_H - y1, x1 - x0, y1 - y0, stroke=1, fill=0)
        elif s.kind == "hline":
            x0, y, x1 = s.coords
            c.line(x0, PAGE_H - y, x1, PAGE_H - y)
    for w in page.words:
        if w.kind == "option" and not include_options:
            continue
        dx, dy = word_offsets(code, w, amp_x, amp_y)
        c.setFont(w.font, w.size)
        c.drawString(w.x + dx, PAGE_H - (w.base + dy), w.text)
    if booklet:
        for (x, base, size, font) in page.serial_slots:
            c.setFont(font, size)
            c.drawString(x, PAGE_H - base, booklet)
        for (x, top, size) in page.qr_slots:
            qr = segno.make(f"NSH:{booklet}", error="m", micro=False)
            rows = list(qr.matrix_iter(border=0))
            m = size / len(rows)
            for r, row in enumerate(rows):
                for col, v in enumerate(row):
                    if v:
                        c.rect(x + col * m, PAGE_H - (top + (r + 1) * m), m + 0.02, m + 0.02, stroke=0, fill=1)


def pdf_bytes(pages: list[PageLayout], copies: list[tuple[str | None, list[CopyCode | None]]],
              amp_x: float, amp_y: float, include_options: bool = True, title: str = "Nishaan") -> bytes:
    """copies: list of (booklet or None, per-page code list)."""
    register_fonts()
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
    c.setTitle(title)
    for booklet, codes in copies:
        for i, page in enumerate(pages):
            draw_page(c, page, codes[i] if codes else None, booklet, amp_x, amp_y, include_options)
            c.showPage()
    c.save()
    return buf.getvalue()
