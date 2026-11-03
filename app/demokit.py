"""Demo kit: files built from the running exam, so they trace on this machine.

Every photo and leak is checked against the tracer before it goes in the kit.
"""
from __future__ import annotations

import io
import random
import zipfile
from pathlib import Path

import cv2
import numpy as np

from .canary import trace_text
from .simulate import fake_photo, retyped_leak
from .tracer import decode_image, trace_photo

ROOT = Path(__file__).resolve().parent.parent


def _photo(svc, rng, booklet: str, centre: str, page: int, **kw) -> tuple[bytes, dict]:
    best = None
    for _ in range(6):
        jpg = fake_photo(svc.model, booklet, centre, page, seed=rng.randrange(1 << 30), **kw)
        with svc.lock:
            r = trace_photo(svc.model, decode_image(jpg), svc.copies)
        ok = r.get("booklet") == booklet and r["status"] in ("traced", "probable")
        if ok and (best is None or r["z"] > best[1]["z"]):
            best = (jpg, r)
        if ok and r["status"] == "traced":
            break
    if best is None:
        return jpg, r
    return best


def _leak(svc, rng, source: str) -> tuple[str, dict]:
    for _ in range(6):
        txt = retyped_leak(svc.model, source, seed=rng.randrange(1 << 30))
        with svc.lock:
            r = trace_text(svc.model, txt)
        if r.get("best", {}).get("id") == source and r["status"] == "traced":
            return txt, r
    return txt, r


def _unrelated_page(rng) -> bytes:
    h, w = 1754, 1240
    page = np.full((h, w), 246, np.uint8)
    lines = ["Weekly class notes", "Thermodynamics, lecture 6",
             "First law: change in internal energy equals heat added minus work done.",
             "Isothermal process: temperature stays constant, internal energy unchanged.",
             "Adiabatic process: no heat exchange with the surroundings.",
             "Carnot engine efficiency depends only on the two reservoir temperatures.",
             "Entropy of an isolated system never decreases.",
             "Homework: problems 4, 7 and 11 from chapter 12.",
             "Lab on Thursday, bring the calorimeter readings.",
             "Revision test next Monday covers chapters 10 to 12."]
    y = 170
    for i, t in enumerate(lines):
        scale = 1.6 if i == 0 else 0.95
        thick = 3 if i == 0 else 2
        cv2.putText(page, t, (110, y), cv2.FONT_HERSHEY_SIMPLEX, scale, 40, thick, cv2.LINE_AA)
        y += 110 if i == 0 else 78
        if i > 1:
            cv2.line(page, (110, y - 40), (w - 110, y - 40), 215, 1)
    pad = 160
    canvas = np.full((h + 2 * pad, w + 2 * pad), 92, np.uint8)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + pad + np.float32([[rng.uniform(-60, 60), rng.uniform(-60, 60)] for _ in range(4)])
    M = cv2.getPerspectiveTransform(src, dst)
    canvas = cv2.warpPerspective(page, M, (canvas.shape[1], canvas.shape[0]), dst=canvas,
                                 borderMode=cv2.BORDER_TRANSPARENT)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 1.1)
    img = cv2.resize(canvas, (int(canvas.shape[1] * 0.85), int(canvas.shape[0] * 0.85)), interpolation=cv2.INTER_AREA)
    color = cv2.merge([np.clip(img * f, 0, 255).astype(np.uint8) for f in (0.92, 0.97, 1.0)])
    return cv2.imencode(".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def _where(svc, booklet: str) -> str:
    c = svc.custody_for_copy(booklet)
    return f"booklet {booklet}, {c['city']} {c['area']} ({c['centre']}), room {c['room']}, seat {c['seat']}"


def build(svc) -> bytes:
    run = svc.store.latest_run(svc.exam["id"])
    rng = random.Random(f"{svc.exam['secret']}:{run['id']}")
    copies, centres = list(svc.copies), list(svc.centres)
    by_centre = {c["code"]: [x for x in copies if x["centre"] == c["code"]] for c in centres}

    print_set = [by_centre[c["code"]][0] for c in centres[:6]]
    pool = [x for x in copies if x not in print_set]
    full, torn, crumpled = rng.sample(pool, 3)

    files: list[tuple[str, bytes]] = []
    notes: list[str] = []

    files.append(("1-print-these-booklets.pdf", svc.print_pdf(print_set)))
    notes.append("1-print-these-booklets.pdf\n"
                 "   Print all 12 pages (6 booklets, 2 pages each). Hand one to a judge, let them cover the\n"
                 "   booklet number, crumple it and photograph it from the phone page.\n"
                 "   Booklets inside: " + ", ".join(f"{b['booklet']} ({b['centre']})" for b in print_set))

    jpg, r = _photo(svc, rng, full["booklet"], full["centre"], 0, crumple=0.8, out_max=1800, quality=82)
    files.append(("2-leak-photo-full-page.jpg", jpg))
    notes.append("2-leak-photo-full-page.jpg\n"
                 "   A phone photo of page 1, booklet number covered by a thumb.\n"
                 f"   Expect: {r['status'].upper()}, {_where(svc, full['booklet'])}, about {r.get('z', 0):.0f} sigma.")

    jpg, r = _photo(svc, rng, torn["booklet"], torn["centre"], 1, fragment=True, crumple=0.9, out_max=2000, quality=82)
    files.append(("3-leak-photo-torn-piece.jpg", jpg))
    notes.append("3-leak-photo-torn-piece.jpg\n"
                 "   Only a torn corner of page 2. Shows the fingerprint is on every word, not in one spot.\n"
                 f"   Expect: {r['status'].upper()}, {_where(svc, torn['booklet'])}, about {r.get('z', 0):.0f} sigma.")

    jpg, r = _photo(svc, rng, crumpled["booklet"], crumpled["centre"], 0, crumple=2.0, out_max=1800, quality=78)
    files.append(("4-leak-photo-crumpled.jpg", jpg))
    notes.append("4-leak-photo-crumpled.jpg\n"
                 "   A badly crumpled page photographed at an angle.\n"
                 f"   Expect: {r['status'].upper()}, {_where(svc, crumpled['booklet'])}, about {r.get('z', 0):.0f} sigma.")

    holder = rng.choice(["T1", "T2", "T3", "M1", "M2"])
    txt, r = _leak(svc, rng, holder)
    files.append(("5-guess-paper-from-a-holder.txt", txt.encode("utf-8")))
    notes.append("5-guess-paper-from-a-holder.txt\n"
                 "   A retyped guess paper, like the 2026 leak. Paste it on Trace > Text, or drag the file in.\n"
                 f"   Expect: TRACED to {svc.source_label(holder)} ({holder}), "
                 f"{r['best']['matched']} of {r['best']['total']} canary marks. Leaked before printing, so every centre is exposed.")

    centre = rng.choice(centres)["code"]
    txt, r = _leak(svc, rng, centre)
    files.append(("6-guess-paper-from-a-centre.txt", txt.encode("utf-8")))
    notes.append("6-guess-paper-from-a-centre.txt\n"
                 "   A retyped leak from inside one exam centre.\n"
                 f"   Expect: TRACED to {svc.source_label(centre)} ({centre}), "
                 f"{r['best']['matched']} of {r['best']['total']} marks. Only that centre needs a re-test.")

    jpg = _unrelated_page(rng)
    files.append(("7-not-this-paper.jpg", jpg))
    notes.append("7-not-this-paper.jpg\n"
                 "   Someone's class notes. Shows Nishaan never accuses a booklet when the page is not this paper.\n"
                 "   Expect: NOT THIS PAPER (or NO MATCH if Tesseract OCR is installed).")

    handout = ROOT / "docs" / "judge-handout.pdf"
    if handout.exists():
        files.append(("judge-handout.pdf", handout.read_bytes()))
        notes.append("judge-handout.pdf\n   One page to print and leave with judges.")

    header = (f"NISHAAN DEMO KIT\n{svc.exam['title']}: {svc.exam['subtitle']}\nPrint run {run['id']}\n\n"
              "Keep this file to yourself. It lists what each file should trace to.\n"
              "These files only match this exam. If you start a new exam, or issue a run with a\n"
              "different number of booklets per centre, download the kit again and reprint.\n\n")
    files.insert(0, ("PRESENTER-NOTES.txt", (header + "\n\n".join(notes) + "\n").encode("utf-8")))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(f"nishaan-demo-kit/{name}", data)
    return buf.getvalue()


def cached(svc) -> bytes:
    run = svc.store.latest_run(svc.exam["id"])
    path = svc.var / "runs" / f"demo_kit_{svc.exam['id']}_{run['id']}.zip"
    if path.exists():
        return path.read_bytes()
    data = build(svc)
    path.write_bytes(data)
    return data
