"""Exam lifecycle, issuing, tracing and custody resolution."""
from __future__ import annotations

import hashlib
import io
import json
import random
import secrets
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .canary import stage_of, trace_text
from .db import Store
from .model import AMP_X, AMP_Y, DEFAULT_CENTRES, DEFAULT_HOLDERS, ExamModel
from .simulate import copy_pdf, fake_photo, render_page, retyped_leak
from .tracer import decode_image, trace_photo
from .typeset import build_layout, copy_code, pdf_bytes

DEFAULT_TITLE = "National Science Entrance 2026"
DEFAULT_SUBTITLE = "Mock Paper 1: Physics, Chemistry and Biology"
STAGE_LABEL = {"setting": "Paper setting", "moderation": "Moderation", "translation": "Translation",
               "print": "Printing and centres"}


class Nishaan:
    def __init__(self, root: Path):
        self.var = root / "var"
        for d in ("runs", "media", "softcopies"):
            (self.var / d).mkdir(parents=True, exist_ok=True)
        self.store = Store(self.var / "nishaan.db")
        self.lock = threading.RLock()
        self.listeners: list = []
        self.model: ExamModel | None = None
        self.exam: dict | None = None
        self.centres: list[dict] = []
        self.holders: list[dict] = []
        self.copies: list[dict] = []
        self.has_ocr = shutil.which("tesseract") is not None

    # ------------------------------------------------------------ events
    def emit(self, kind: str, data: dict) -> None:
        for fn in list(self.listeners):
            try:
                fn({"type": kind, **data})
            except Exception:
                pass

    # ------------------------------------------------------------ lifecycle
    def boot(self) -> None:
        exam = self.store.active_exam()
        if exam is None:
            self.create_exam(DEFAULT_TITLE, DEFAULT_SUBTITLE, 8)
        else:
            self._load(exam)

    def _load(self, exam: dict) -> None:
        self.exam = exam
        self.centres = self.store.centres(exam["id"])
        self.holders = self.store.holders(exam["id"])
        self.model = ExamModel(exam["secret"], exam["title"], exam["subtitle"], self.centres, self.holders)
        self.model.build_refs()
        self.copies = self.store.copies(exam["id"])
        _copy_pdf_cached.cache_clear()

    def create_exam(self, title: str, subtitle: str, per_centre: int) -> None:
        with self.lock:
            s = self.store
            s.x("UPDATE exam SET active=0")
            secret = secrets.token_hex(16)
            eid = s.x("INSERT INTO exam (secret, title, subtitle, created_at, active) VALUES (?,?,?,?,1)",
                      (secret, title, subtitle, time.time()))
            rng = random.Random(secret)
            for code, city, area, press in DEFAULT_CENTRES:
                rooms = sorted(rng.sample(range(10, 40), 2))
                rooms = [{"room": str(r), "invigilator": f"INV-{code[:3]}-{r}"} for r in rooms]
                s.x("INSERT INTO centre VALUES (?,?,?,?,?,?)", (eid, code, city, area, press, json.dumps(rooms)))
            for hid, stage, role, label in DEFAULT_HOLDERS:
                s.x("INSERT INTO holder VALUES (?,?,?,?,?)", (eid, hid, stage, role, label))
            exam = s.active_exam()
            self._load(exam)
            m = self.model
            master = pdf_bytes(build_layout(title, subtitle, m.questions, m.master), [(None, None)], 0, 0)
            s.append("exam_created", "Exam authority", title, {"exam": eid, "questions": len(m.questions)})
            s.append("paper_sealed", "S1", "Master paper", {"sha256": hashlib.sha256(master).hexdigest()})
            for h in self.holders:
                if h["stage"] in (1, 2):
                    pdf = self.softcopy_pdf(h["id"])
                    s.append("softcopy_issued", "Exam authority", h["id"],
                             {"holder": h["label"], "sha256": hashlib.sha256(pdf).hexdigest()})
            self.issue(per_centre)

    def issue(self, per_centre: int) -> dict:
        per_centre = max(1, min(int(per_centre), 400))
        with self.lock:
            s, exam, m = self.store, self.exam, self.model
            eid = exam["id"]
            s.x("DELETE FROM copy WHERE exam_id=?", (eid,))
            run_id = s.x("INSERT INTO run (exam_id, created_at, per_centre, total, file) VALUES (?,?,?,?,?)",
                         (eid, time.time(), per_centre, per_centre * len(self.centres), ""))
            prefix = f"{(470 + eid) % 1000:03d}"
            n, rows, now = 1, [], time.time()
            for ci, c in enumerate(self.centres):
                for k in range(per_centre):
                    room = c["rooms"][k % len(c["rooms"])]["room"]
                    seat = k // len(c["rooms"]) + 1
                    booklet = f"{prefix}{n:04d}"
                    roll = f"26{ci + 1:02d}{int(room):02d}{seat:03d}"
                    rows.append((eid, booklet, c["code"], room, seat, roll, run_id, now))
                    n += 1
            s.many("INSERT INTO copy VALUES (?,?,?,?,?,?,?,?)", rows)
            self.copies = s.copies(eid)
            pdf = self.print_pdf(self.copies)
            path = self.var / "runs" / f"run_{run_id}.pdf"
            path.write_bytes(pdf)
            s.x("UPDATE run SET file=? WHERE id=?", (path.name, run_id))
            _copy_pdf_cached.cache_clear()
            for press in ("P1", "P2"):
                cs = [c["code"] for c in self.centres if c["press"] == press]
                s.append("print_run", press, f"Run {run_id}",
                         {"centres": cs, "copies": per_centre * len(cs), "sha256": hashlib.sha256(pdf).hexdigest()[:16]})
            for c in self.centres:
                bs = [r for r in self.copies if r["centre"] == c["code"]]
                s.append("booklets_dispatched", c["press"], c["code"],
                         {"first": bs[0]["booklet"], "last": bs[-1]["booklet"], "count": len(bs),
                          "rooms": [r["room"] for r in c["rooms"]]})
            self.emit("issued", {"run": run_id, "total": len(self.copies)})
            return {"run": run_id, "total": len(self.copies), "per_centre": per_centre}

    # ------------------------------------------------------------ documents
    def print_pdf(self, copies: list[dict]) -> bytes:
        m = self.model
        items = []
        by_centre: dict[str, list] = {}
        for c in copies:
            by_centre.setdefault(c["centre"], []).append(c)
        parts = []
        for code, cs in by_centre.items():
            lay = m.layouts[code]
            parts.append((lay, [(c["booklet"], [copy_code(m.secret, c["booklet"], p) for p in range(len(lay))])
                                for c in cs]))
        # one document, centre by centre
        from reportlab.pdfgen import canvas as rl_canvas
        from .typeset import PAGE_H, PAGE_W, draw_page, register_fonts
        register_fonts()
        buf = io.BytesIO()
        cv = rl_canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), invariant=1)
        cv.setTitle(f"{self.exam['title']} print run")
        for lay, items in parts:
            for booklet, codes in items:
                for i, page in enumerate(lay):
                    draw_page(cv, page, codes[i], booklet, AMP_X, AMP_Y)
                    cv.showPage()
        cv.save()
        return buf.getvalue()

    def booklet_pdf(self, booklet: str) -> bytes | None:
        c = self.copy(booklet)
        if not c:
            return None
        return _copy_pdf_cached(self, booklet, c["centre"])

    def softcopy_pdf(self, holder_id: str) -> bytes:
        m = self.model
        v = m.master if holder_id == "S1" else m.soft_variants.get(holder_id, m.master)
        lay = build_layout(m.title, m.subtitle, m.questions, v)
        return pdf_bytes(lay, [(None, None)], 0, 0, title=f"{m.title} soft copy")

    def answer_keys_csv(self) -> str:
        m = self.model
        lines = ["question," + ",".join(c["code"] for c in self.centres)]
        keys = {c["code"]: m.answer_key(c["code"]) for c in self.centres}
        for i in range(len(m.questions)):
            lines.append(f"{i + 1}," + ",".join(str(keys[c["code"]][i]) for c in self.centres))
        return "\n".join(lines) + "\n"

    def render(self, booklet: str, page: int, clip=None, dpi: int = 72) -> np.ndarray | None:
        pdf = self.booklet_pdf(booklet)
        if pdf is None or page < 0 or page >= self.model.n_pages:
            return None
        return render_page(pdf, page, dpi, clip)

    # ------------------------------------------------------------ lookups
    def copy(self, booklet: str) -> dict | None:
        return next((c for c in self.copies if c["booklet"] == booklet), None)

    def centre(self, code: str) -> dict | None:
        return next((c for c in self.centres if c["code"] == code), None)

    def holder(self, hid: str) -> dict | None:
        return next((h for h in self.holders if h["id"] == hid), None)

    def custody_for_copy(self, booklet: str) -> dict | None:
        c = self.copy(booklet)
        if not c:
            return None
        ce = self.centre(c["centre"])
        room = next((r for r in ce["rooms"] if r["room"] == c["room"]), {"invigilator": "?"})
        press = self.holder(ce["press"])
        return {
            "booklet": booklet, "centre": c["centre"], "city": ce["city"], "area": ce["area"],
            "room": c["room"], "seat": c["seat"], "roll": c["roll"], "invigilator": room["invigilator"],
            "superintendent": f"CS-{c['centre']}", "press": ce["press"], "press_label": press["label"] if press else "",
            "printed_at": c["printed_at"],
        }

    # ------------------------------------------------------------ tracing
    def _save_media(self, token: str, name: str, img: np.ndarray, max_side: int, quality: int = 84) -> str:
        h, w = img.shape[:2]
        s = min(1.0, max_side / max(h, w))
        if s < 1:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(self.var / "media" / f"{token}_{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return f"/media/{token}_{name}.jpg"

    def trace_photo(self, data: bytes, channel: str = "web", truth: dict | None = None) -> dict:
        img = decode_image(data)
        if img is None:
            return {"kind": "photo", "status": "unreadable"}
        with self.lock:
            r = trace_photo(self.model, img, self.copies)
        token = secrets.token_hex(6)
        if r["status"] in ("unregistered", "inconclusive") and self.has_ocr:
            text = _ocr(data)
            if len(text.strip()) > 120:
                with self.lock:
                    tr = trace_text(self.model, text)
                if tr["status"] in ("traced", "probable", "stage") or r["status"] == "unregistered":
                    return self.trace_text(text, channel, source_image=self._save_media(token, "in", img, 1400),
                                           via_ocr=True)
        result = {"kind": "photo", "channel": channel, **{k: v for k, v in r.items() if not k.startswith("_")}}
        result["photo"] = self._save_media(token, "in", img, 1400)
        if "_warped" in r:
            x0, y0, x1, y1 = r["viz"]["crop"]
            reg = r["_warped"][y0:y1, x0:x1]
            reg = cv2.normalize(reg, None, 0, 255, cv2.NORM_MINMAX)
            mask = r["_valid"][y0:y1, x0:x1] > 0
            reg = np.where(mask, reg, 238).astype(np.uint8)
            result["registered"] = self._save_media(token, "reg", reg, 1400, 88)
            result["viz"]["image_scale"] = min(1.0, 1400 / max(reg.shape))
        n = max(len(self.copies), 1)
        if "log10_odds" in r:
            result["log10_odds"] = round(r["log10_odds"] - np.log10(n), 1)
        if r.get("booklet"):
            result["custody"] = self.custody_for_copy(r["booklet"])
        if truth:
            result["truth"] = truth
        return self._record("photo", channel, result)

    def trace_text(self, text: str, channel: str = "web", source_image: str | None = None,
                   via_ocr: bool = False) -> dict:
        with self.lock:
            r = trace_text(self.model, text)
        result = {"kind": "text", "channel": channel, "text": text, "via_ocr": via_ocr, **r}
        if source_image:
            result["photo"] = source_image
        best = r.get("best")
        if best:
            result["custody"] = self.custody_for_source(best["id"])
        for row in result["ranking"]:
            row["label"] = self.source_label(row["id"])
            row["stage"] = stage_of(self.model, row["id"])
        if r.get("stage"):
            result["stage_label"] = STAGE_LABEL.get(r["stage"], r["stage"])
        return self._record("text", channel, result)

    def source_label(self, sid: str) -> str:
        h = self.holder(sid)
        if h:
            return h["label"]
        c = self.centre(sid)
        return f"{c['city']}, {c['area']}" if c else sid

    def custody_for_source(self, sid: str) -> dict:
        h = self.holder(sid)
        if h:
            return {"type": "holder", "id": sid, "label": h["label"], "role": h["role"],
                    "stage": stage_of(self.model, sid)}
        c = self.centre(sid)
        press = self.holder(c["press"]) if c else None
        return {"type": "centre", "id": sid, "city": c["city"] if c else "", "area": c["area"] if c else "",
                "press": c["press"] if c else "", "press_label": press["label"] if press else "",
                "superintendent": f"CS-{sid}", "copies": sum(1 for x in self.copies if x["centre"] == sid),
                "stage": "print"}

    def _record(self, kind: str, channel: str, result: dict) -> dict:
        status = result.get("status", "inconclusive")
        summary = {"status": status, "kind": kind, "channel": channel}
        if kind == "photo" and result.get("booklet"):
            cu = result.get("custody") or {}
            summary.update(booklet=result["booklet"], centre=cu.get("centre"), room=cu.get("room"),
                           z=result.get("z"), page=result.get("page"))
        elif kind == "text" and result.get("best"):
            b = result["best"]
            summary.update(source=b["id"], label=self.source_label(b["id"]), matched=b["matched"],
                           total=b["total"], stage=result.get("stage"))
        tid = self.store.add_trace(self.exam["id"], kind, channel, status, summary, result)
        result["id"] = tid
        summary["id"] = tid
        led_payload = {"trace": tid, "status": status, "channel": channel}
        if kind == "photo" and result.get("booklet"):
            led_payload.update(booklet=result["booklet"], z=result.get("z"))
        if kind == "text" and result.get("best"):
            led_payload.update(source=result["best"]["id"], matched=result["best"]["matched"],
                               total=result["best"]["total"])
        subject = result.get("booklet") or (result.get("best") or {}).get("id") or "unidentified"
        self.store.append("leak_traced" if status in ("traced", "probable") else "trace_attempt",
                          "Nishaan", subject, led_payload)
        self.store.x("UPDATE trace SET result=? WHERE id=?", (json.dumps(result), tid))
        self.emit("trace", {"summary": {**summary, "ts": time.time()}})
        return result

    # ------------------------------------------------------------ rehearsal
    def simulate_photo(self, fragment: bool = False) -> dict:
        c = random.choice(self.copies)
        page = random.randrange(self.model.n_pages)
        jpg = fake_photo(self.model, c["booklet"], c["centre"], page, seed=random.randrange(1 << 30),
                         fragment=fragment, crumple=random.choice([0.6, 1.0, 1.4]))
        return self.trace_photo(jpg, "rehearsal", truth={"booklet": c["booklet"], "page": page + 1})

    def simulate_text(self, source: str | None = None) -> dict:
        ids = ["M1", "M2", "T1", "T2", "T3"] + [c["code"] for c in self.centres]
        source = source if source in ids + ["S1"] else random.choice(ids)
        return {"source": source, "text": retyped_leak(self.model, source, seed=random.randrange(1 << 30))}


@lru_cache(maxsize=24)
def _copy_pdf_cached(svc: Nishaan, booklet: str, centre: str) -> bytes:
    return copy_pdf(svc.model, booklet, centre)


def _ocr(data: bytes) -> str:
    try:
        p = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "4"], input=data,
                           capture_output=True, timeout=40)
        return p.stdout.decode("utf-8", "ignore")
    except Exception:
        return ""
