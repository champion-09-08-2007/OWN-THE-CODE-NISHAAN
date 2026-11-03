"""HTTP API, live event stream and static front end."""
from __future__ import annotations

import asyncio
import io
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
import segno
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .bot import TelegramBot
from .service import Nishaan

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PORT = int(os.environ.get("NISHAAN_PORT", "8000"))
svc = Nishaan(ROOT)


class Broker:
    def __init__(self):
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def publish(self, ev: dict) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self._put, ev)

    def _put(self, ev: dict) -> None:
        for q in list(self.queues):
            q.put_nowait(ev)


broker = Broker()


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    broker.loop = asyncio.get_running_loop()
    await run_in_threadpool(svc.boot)
    svc.listeners.append(broker.publish)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        TelegramBot(token, svc).start()
    yield


app = FastAPI(title="Nishaan", lifespan=lifespan)


def phone_url(request: Request) -> str:
    host = os.environ.get("NISHAAN_PUBLIC_URL")
    if host:
        return host.rstrip("/") + "/m"
    return f"http://{lan_ip()}:{request.url.port or PORT}/m"


# ---------------------------------------------------------------- state
@app.get("/api/state")
def state(request: Request):
    e = svc.exam
    run = svc.store.latest_run(e["id"])
    per_centre = {}
    for c in svc.copies:
        per_centre[c["centre"]] = per_centre.get(c["centre"], 0) + 1
    return {
        "exam": {"id": e["id"], "title": e["title"], "subtitle": e["subtitle"], "created_at": e["created_at"],
                 "pages": svc.model.n_pages, "questions": len(svc.model.questions)},
        "centres": [{**c, "copies": per_centre.get(c["code"], 0)} for c in svc.centres],
        "holders": svc.holders,
        "copies_total": len(svc.copies),
        "run": run,
        "traces": svc.store.traces(e["id"], 40),
        "trace_count": svc.store.trace_count(e["id"]),
        "leak_count": svc.store.q("SELECT COUNT(*) AS n FROM trace WHERE exam_id=? AND status IN "
                                  "('traced','probable','stage')", (e["id"],))[0]["n"],
        "ledger": svc.store.ledger_head(),
        "phone_url": phone_url(request),
        "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "ocr": svc.has_ocr,
    }


@app.get("/api/copies")
def copies(centre: str | None = None):
    rows = svc.copies if not centre else [c for c in svc.copies if c["centre"] == centre]
    return rows


class IssueIn(BaseModel):
    per_centre: int = 8


@app.post("/api/issue")
async def issue(body: IssueIn):
    return await run_in_threadpool(svc.issue, body.per_centre)


class ExamIn(BaseModel):
    title: str
    subtitle: str = ""
    per_centre: int = 8


@app.post("/api/exam")
async def new_exam(body: ExamIn):
    title = body.title.strip()[:80] or "Untitled examination"
    await run_in_threadpool(svc.create_exam, title, body.subtitle.strip()[:120], body.per_centre)
    return {"ok": True}


# ---------------------------------------------------------------- tracing
@app.post("/api/trace/photo")
async def trace_photo(file: UploadFile = File(...), channel: str = Form("web")):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    return await run_in_threadpool(svc.trace_photo, data, channel[:16])


class TextIn(BaseModel):
    text: str
    channel: str = "web"


@app.post("/api/trace/text")
async def trace_text(body: TextIn):
    if len(body.text.strip()) < 20:
        raise HTTPException(400, "Paste more of the leaked text")
    return await run_in_threadpool(svc.trace_text, body.text[:200_000], body.channel[:16])


class SimIn(BaseModel):
    fragment: bool = False


@app.post("/api/simulate/photo")
async def simulate_photo(body: SimIn):
    return await run_in_threadpool(svc.simulate_photo, body.fragment)


@app.get("/api/simulate/text")
async def simulate_text(source: str | None = None):
    return await run_in_threadpool(svc.simulate_text, source)


@app.get("/api/trace/{tid}")
def get_trace(tid: int):
    t = svc.store.trace(tid)
    if not t:
        raise HTTPException(404)
    return t["result"]


# ---------------------------------------------------------------- documents
@app.get("/files/print.pdf")
def print_file():
    run = svc.store.latest_run(svc.exam["id"])
    path = svc.var / "runs" / run["file"]
    return FileResponse(path, media_type="application/pdf", filename=f"print-run-{run['id']}.pdf")


@app.get("/files/booklet/{booklet}.pdf")
async def booklet_file(booklet: str):
    pdf = await run_in_threadpool(svc.booklet_pdf, booklet)
    if pdf is None:
        raise HTTPException(404)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="booklet-{booklet}.pdf"'})


@app.get("/files/softcopy/{hid}.pdf")
async def softcopy_file(hid: str):
    if not svc.holder(hid) or svc.holder(hid)["stage"] > 2:
        raise HTTPException(404)
    pdf = await run_in_threadpool(svc.softcopy_pdf, hid)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="softcopy-{hid}.pdf"'})


@app.get("/files/answer-keys.csv")
def keys_file():
    return Response(svc.answer_keys_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="answer-keys.csv"'})


def _png(img: np.ndarray) -> Response:
    ok, enc = cv2.imencode(".png", img)
    return Response(enc.tobytes(), media_type="image/png", headers={"Cache-Control": "max-age=600"})


def _clip(x0, y0, x1, y1):
    if None in (x0, y0, x1, y1):
        return None
    return (float(x0), float(y0), float(x1), float(y1))


@app.get("/api/render")
async def render(booklet: str, page: int = 0, dpi: int = 60, x0: float | None = None, y0: float | None = None,
                 x1: float | None = None, y1: float | None = None):
    dpi = max(30, min(dpi, 600))
    img = await run_in_threadpool(svc.render, booklet, page, _clip(x0, y0, x1, y1), dpi)
    if img is None:
        raise HTTPException(404)
    return _png(img)


@app.get("/api/diff")
async def diff(a: str, b: str, page: int = 0, dpi: int = 300, x0: float = 0, y0: float = 0,
               x1: float = 200, y1: float = 100):
    clip = (x0, y0, x1, y1)
    ia = await run_in_threadpool(svc.render, a, page, clip, dpi)
    ib = await run_in_threadpool(svc.render, b, page, clip, dpi)
    if ia is None or ib is None:
        raise HTTPException(404)
    da, db_ = ia < 150, ib < 150
    out = np.full((*ia.shape, 3), 255, np.uint8)
    out[da & db_] = (190, 184, 176)
    out[da & ~db_] = (58, 30, 196)     # only in A: crimson (BGR)
    out[~da & db_] = (181, 66, 36)     # only in B: ink blue
    return _png(out)


# ---------------------------------------------------------------- ledger
@app.get("/api/ledger")
def ledger(limit: int = 200, before: int | None = None):
    return {"events": svc.store.ledger(min(limit, 500), before), **svc.store.ledger_head()}


@app.get("/api/ledger/verify")
def ledger_verify():
    return svc.store.verify()


@app.get("/files/ledger.json")
def ledger_export():
    data = list(reversed(svc.store.ledger(100000)))
    return Response(json.dumps(data, indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="custody-ledger.json"'})


# ---------------------------------------------------------------- live + phone
@app.get("/api/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    broker.queues.add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broker.queues.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/phone-qr.svg")
def phone_qr(request: Request):
    buf = io.BytesIO()
    segno.make(phone_url(request), error="m").save(buf, kind="svg", scale=6, border=0, dark="#141B3A",
                                                     xmldecl=False, svgns=True)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


app.mount("/media", StaticFiles(directory=str(svc.var / "media")), name="media")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/m")
def phone_page():
    return FileResponse(STATIC / "m.html", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
