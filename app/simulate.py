"""Synthetic leaks for rehearsal: phone photos of printed copies and
retyped 'guess papers' built from a holder's wording."""
from __future__ import annotations

import random
import re

import cv2
import numpy as np

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf  # type: ignore

from .model import AMP_X, AMP_Y, ExamModel
from .typeset import PAGE_H, PAGE_W, copy_code, pdf_bytes


def copy_pdf(model: ExamModel, booklet: str, centre: str) -> bytes:
    lay = model.layouts[centre]
    codes = [copy_code(model.secret, booklet, p) for p in range(len(lay))]
    return pdf_bytes(lay, [(booklet, codes)], AMP_X, AMP_Y, title=f"Booklet {booklet}")


def render_page(pdf: bytes, page: int, dpi: int, clip=None) -> np.ndarray:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pg = doc[page]
    kw = {"dpi": dpi, "colorspace": pymupdf.csGRAY, "alpha": False}
    if clip:
        kw["clip"] = pymupdf.Rect(*clip)
    pix = pg.get_pixmap(**kw)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _smooth_field(h, w, cells, amp, rng):
    g = rng.normal(0, 1, (cells[0], cells[1])).astype(np.float32)
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC) * amp


def fake_photo(model: ExamModel, booklet: str, centre: str, page: int, seed: int | None = None,
               fragment: bool = False, crumple: float = 1.0, cover_serial: bool = True,
               out_max: int = 1600, quality: int = 72) -> bytes:
    rng = np.random.default_rng(seed)
    dpi = 300
    paper = render_page(copy_pdf(model, booklet, centre), page, dpi).astype(np.float32)
    h, w = paper.shape
    s = dpi / 72

    if cover_serial:  # a thumb over the booklet number
        for (x, base, size, _f) in model.layouts[centre][page].serial_slots[:1]:
            cx, cy = int((x + 30) * s), int((base - 6) * s)
            cv2.ellipse(paper, (cx, cy), (int(70 * s), int(36 * s)), -15, 0, 360, 168, -1)

    # paper crumple: smooth displacement + fold shading
    if crumple > 0:
        fx = _smooth_field(h, w, (7, 5), 4.5 * crumple, rng)
        fy = _smooth_field(h, w, (7, 5), 4.5 * crumple, rng)
        mx, my = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        paper = cv2.remap(paper, mx + fx, my + fy, cv2.INTER_LINEAR, borderValue=255)
        shade = 1.0 - 0.05 * crumple * np.tanh(cv2.Sobel(fx + fy, cv2.CV_32F, 1, 1, ksize=5) * 0.4)
        paper *= shade

    alpha = np.full((h, w), 255, np.uint8)
    if fragment:  # torn piece: keep a random region with a jagged edge
        keep = np.zeros((h, w), np.uint8)
        corner = rng.integers(0, 4)
        fw, fh = rng.uniform(0.5, 0.7) * w, rng.uniform(0.38, 0.55) * h
        x0 = 0 if corner in (0, 2) else w - fw
        y0 = 0 if corner in (0, 1) else h - fh
        pts = [(x0, y0), (x0 + fw, y0), (x0 + fw, y0 + fh), (x0, y0 + fh)]
        poly = []
        for i in range(4):
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % 4])
            for t in np.linspace(0, 1, 40, endpoint=False):
                pnt = a + (b - a) * t + rng.normal(0, 9, 2)
                poly.append(pnt)
        cv2.fillPoly(keep, [np.int32(poly)], 255)
        alpha = keep

    # place on a table with perspective
    pad = int(0.12 * max(h, w))
    canvas_h, canvas_w = h + 2 * pad, w + 2 * pad
    table = (rng.uniform(70, 120) + rng.normal(0, 6, (canvas_h // 8, canvas_w // 8))).astype(np.float32)
    table = cv2.resize(table, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    jit = 0.07 * min(h, w)
    dst = src + pad + rng.uniform(-jit, jit, (4, 2)).astype(np.float32)
    ang = rng.uniform(-12, 12)
    R = cv2.getRotationMatrix2D((canvas_w / 2, canvas_h / 2), ang, 1.0)
    dst = (np.hstack([dst, np.ones((4, 1), np.float32)]) @ R.T).astype(np.float32)
    Hm = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(paper, Hm, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR, borderValue=0)
    a = cv2.warpPerspective(alpha, Hm, (canvas_w, canvas_h), flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    img = warped * a + table * (1 - a)

    # lens distortion and lighting
    k1 = rng.uniform(-0.06, 0.03)
    yy, xx = np.meshgrid(np.linspace(-1, 1, canvas_h, dtype=np.float32),
                         np.linspace(-1, 1, canvas_w, dtype=np.float32), indexing="ij")
    rr = xx ** 2 + yy ** 2
    mapx = ((xx * (1 + k1 * rr)) + 1) * (canvas_w - 1) / 2
    mapy = ((yy * (1 + k1 * rr)) + 1) * (canvas_h - 1) / 2
    img = cv2.remap(img, mapx, mapy, cv2.INTER_LINEAR, borderValue=60)
    light = 0.78 + 0.25 * (np.cos(xx * rng.uniform(0.5, 1.5) + rng.uniform(0, 3)) *
                           np.cos(yy * rng.uniform(0.5, 1.5) + rng.uniform(0, 3)))
    img = img * light
    img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.9, 1.5))
    img += rng.normal(0, 3.5, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    sc = out_max / max(img.shape)
    img = cv2.resize(img, (int(img.shape[1] * sc), int(img.shape[0] * sc)), interpolation=cv2.INTER_AREA)
    color = cv2.merge([np.clip(img * f, 0, 255).astype(np.uint8) for f in (0.92, 0.97, 1.0)])
    ok, enc = cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return enc.tobytes()


# ------------------------------------------------------------------ text leak
def _typo(word: str, rng: random.Random) -> str:
    if len(word) < 5 or not word.isalpha():
        return word
    i = rng.randrange(1, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def retyped_leak(model: ExamModel, source: str, seed: int | None = None) -> str:
    """source: holder id (M1, T2, ...), 'S1' for the master, or a centre code."""
    rng = random.Random(seed)
    if source in model.print_variants:
        v = model.print_variants[source]
    elif source in model.soft_variants:
        v = model.soft_variants[source]
    else:
        v = model.master
    qs = list(model.questions)
    keep = rng.sample(qs, k=rng.randint(int(len(qs) * 0.7), len(qs)))
    keep.sort(key=lambda q: q.idx)
    if rng.random() < 0.5:
        rng.shuffle(keep)
    style = rng.choice(["abcd", "1234", "paren"])
    lines = [rng.choice(["Guess paper - 100% match", "Important questions for tomorrow",
                         "Expected paper. Share only in group"])]
    for n, q in enumerate(keep, 1):
        stem = " ".join(_typo(w, rng) if rng.random() < 0.04 else w for w in v.stem(q).split())
        if rng.random() < 0.3:
            stem = stem.lower()
        lines.append(f"Q{n}. {stem}" if rng.random() < 0.5 else f"{n}) {stem}")
        for i, opt in enumerate(v.options(q)):
            lab = {"abcd": f"({'abcd'[i]})", "1234": f"{i + 1}.", "paren": f"{i + 1})"}[style]
            lines.append(f"   {lab} {opt}")
        if rng.random() < 0.25:
            lines.append(f"   Ans: {'abcd'[v.answer_position(q)]}" if style == "abcd" else
                         f"   Ans: {v.answer_position(q) + 1}")
    return "\n".join(lines)


def strip_layout_noise(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text)
