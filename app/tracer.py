"""Photo tracer: register a photo of any part of a booklet page against the
unmarked master, measure every word's sub-pixel position, remove camera and
paper distortion, and correlate what remains against every issued copy."""
from __future__ import annotations

import math
import time

import cv2
import numpy as np

from .model import AMP_X, AMP_Y, SCALE, ExamModel, PageRef, WordGeo
from .typeset import copy_code

SIFT_MAX_SIDE = 1900
MIN_INLIERS = 22


def decode_image(data: bytes) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _subpix(res: np.ndarray, x: int, y: int) -> tuple[float, float]:
    def para(a, b, c):
        d = a - 2 * b + c
        return 0.0 if abs(d) < 1e-9 else float(np.clip(0.5 * (a - c) / d, -0.5, 0.5))
    h, w = res.shape
    sx = para(res[y, x - 1], res[y, x], res[y, x + 1]) if 0 < x < w - 1 else 0.0
    sy = para(res[y - 1, x], res[y, x], res[y + 1, x]) if 0 < y < h - 1 else 0.0
    return sx, sy


def _match(ref: np.ndarray, img: np.ndarray, box, off: tuple[float, float], rx: int, ry: int, up: int = 1):
    """Locate the word template from `ref` inside `img` around box shifted by off."""
    x0, y0, x1, y1 = box
    tpl = ref[y0:y1, x0:x1]
    if tpl.size == 0 or tpl.std() < 14:
        return None
    ox, oy = int(round(off[0])), int(round(off[1]))
    sx0, sy0 = x0 + ox - rx, y0 + oy - ry
    sx1, sy1 = x1 + ox + rx, y1 + oy + ry
    H, W = img.shape
    if sx0 < 0 or sy0 < 0 or sx1 > W or sy1 > H:
        return None
    win = img[sy0:sy1, sx0:sx1]
    if win.std() < 8:
        return None
    if up > 1:
        tpl = cv2.resize(tpl, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
        win = cv2.resize(win, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
    res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    px, py = _subpix(res, ml[0], ml[1])
    return (ox + (ml[0] + px) / up - rx, oy + (ml[1] + py) / up - ry, float(mv))


def _inside(mask: np.ndarray, box) -> bool:
    x0, y0, x1, y1 = box
    H, W = mask.shape
    if x0 < 0 or y0 < 0 or x1 >= W or y1 >= H:
        return False
    return bool(mask[y0, x0] and mask[y0, x1] and mask[y1, x0] and mask[y1, x1]
                and mask[(y0 + y1) // 2, (x0 + x1) // 2])


def _register(model: ExamModel, gray: np.ndarray):
    h, w = gray.shape
    s = min(1.0, SIFT_MAX_SIDE / max(h, w))
    small = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray
    small = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(small)
    kp, desc = model.sift.detectAndCompute(small, None)
    if desc is None or len(kp) < 30:
        return None
    best = None
    for p, ref in enumerate(model.pages):
        matches = ref.matcher.knnMatch(desc, k=2)
        good = [m for m, n in (mm for mm in matches if len(mm) == 2) if m.distance < 0.78 * n.distance]
        if len(good) < MIN_INLIERS:
            continue
        src = np.float32([kp[m.queryIdx].pt for m in good])
        dst = np.float32([ref.kp[m.trainIdx] for m in good])
        Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0, maxIters=6000, confidence=0.997)
        if Hm is None:
            continue
        n = int(inl.sum())
        if best is None or n > best[1]:
            best = (p, n, Hm, len(good))
    if best is None or best[1] < MIN_INLIERS:
        return None
    p, n, Hm, ng = best
    S = np.diag([s, s, 1.0])
    return p, n, Hm @ S


def _neighbour_median(cx, cy, vals, good, k=8, exclude_self=True):
    pts = np.stack([cx, cy], 1)
    gp = pts[good]
    gv = vals[good]
    if len(gp) == 0:
        return np.zeros((len(cx), 2))
    d = ((pts[:, None, :] - gp[None, :, :]) ** 2).sum(-1)
    if exclude_self:
        gi = np.where(good)[0]
        d[gi, np.arange(len(gi))] = np.inf
    kk = min(k, len(gp))
    idx = np.argpartition(d, kk - 1, axis=1)[:, :kk]
    return np.median(gv[idx], axis=1)


def _detrend_matrices(cx, cy, line, sigma=58.0):
    n = len(cx)
    d2 = (cx[:, None] - cx[None, :]) ** 2 + (cy[:, None] - cy[None, :]) ** 2
    W = np.exp(-d2 / (2 * sigma ** 2))
    np.fill_diagonal(W, 0.0)
    Wy = W * (line[:, None] != line[None, :])
    I = np.eye(n)

    def norm(M):
        s = M.sum(1, keepdims=True)
        ok = (s[:, 0] > 1e-3)
        P = I - np.divide(M, s, out=np.zeros_like(M), where=s > 1e-3)
        P[~ok] = 0.0
        return P, ok
    Px, okx = norm(W)
    Py, oky = norm(Wy)
    return Px, Py, okx, oky


def trace_photo(model: ExamModel, img: np.ndarray, copies: list[dict]) -> dict:
    t0 = time.time()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    reg = _register(model, gray)
    if reg is None:
        return {"status": "unregistered", "elapsed": round(time.time() - t0, 2)}
    page, inliers, Hm = reg
    ref: PageRef = model.pages[page]
    Hh, Ww = ref.common.shape
    warped = cv2.warpPerspective(gray, Hm, (Ww, Hh), flags=cv2.INTER_CUBIC, borderValue=0)
    valid = cv2.warpPerspective(np.full(gray.shape, 255, np.uint8), Hm, (Ww, Hh), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((9, 9), np.uint8))
    raw_warp = warped.copy()
    warped = cv2.GaussianBlur(warped, (0, 0), 1.0)

    # pass 1: coarse displacement of common words
    words = [w for w in ref.words if _inside(valid, w.box)]
    if len(words) < 12:
        return {"status": "inconclusive", "page": page + 1, "reason": "too_little", "inliers": inliers,
                "elapsed": round(time.time() - t0, 2)}
    p1 = []
    for w in words:
        r = _match(ref.common, warped, w.box, (0, 0), 22, 16)
        p1.append(r if r else (0.0, 0.0, -1.0))
    p1 = np.array(p1)
    cx = np.array([w.cx for w in words])
    cy = np.array([w.cy for w in words])
    good = p1[:, 2] >= 0.55
    if good.sum() < 10:
        return {"status": "inconclusive", "page": page + 1, "reason": "unreadable", "inliers": inliers,
                "elapsed": round(time.time() - t0, 2)}
    med = _neighbour_median(cx, cy, p1[:, :2], good)
    dev = np.abs(p1[:, :2] - med).max(1)
    good &= dev < 3.0
    field_pts = np.stack([cx[good], cy[good]], 1)
    field_vals = p1[good, :2]

    def predict(px, py):
        d = ((field_pts - np.array([px, py])) ** 2).sum(1)
        kk = min(8, len(d))
        idx = np.argpartition(d, kk - 1)[:kk]
        return np.median(field_vals[idx], axis=0)

    # pass 2: fine measurement, common words then each centre's option words
    def measure(img_ref, geo: list[WordGeo]):
        out = []
        for w in geo:
            if not _inside(valid, w.box):
                continue
            off = predict(w.cx, w.cy)
            r = _match(img_ref, warped, w.box, (off[0], off[1]), 5, 5, up=2)
            if r and r[2] >= 0.6:
                out.append((w, r[0], r[1], r[2]))
        return out

    common_meas = measure(ref.common, words)
    by_centre = {c["code"]: [] for c in model.centres}
    for c in copies:
        by_centre.setdefault(c["centre"], []).append(c)

    rows = []
    viz = {}
    for code, ccopies in by_centre.items():
        if not ccopies:
            continue
        meas = common_meas + measure(ref.variants[code], ref.option_words.get(code, []))
        if len(meas) < 12:
            continue
        geo = [m[0] for m in meas]
        mx = np.array([m[1] for m in meas])
        my = np.array([m[2] for m in meas])
        wcx = np.array([g.cx for g in geo])
        wcy = np.array([g.cy for g in geo])
        line = np.array([g.line for g in geo])
        movable = np.array([g.movable for g in geo])
        keys = np.array([g.key for g in geo])
        Px, Py, okx, oky = _detrend_matrices(wcx, wcy, line)
        rx, ry = Px @ mx, Py @ my
        selx = movable & okx
        sely = oky
        # one value per line for the vertical channel, one per word for the horizontal
        lines_u = np.unique(line[sely])
        L = (line[sely][None, :] == lines_u[:, None]).astype(float)
        L /= L.sum(1, keepdims=True)
        rxs, rys = rx[selx], L @ ry[sely]
        nx, ny = len(rxs), len(rys)
        if nx + ny < 12:
            continue
        ax, ay = AMP_X * SCALE, AMP_Y * SCALE
        for c in ccopies:
            code_ = copy_code(model.secret, c["booklet"], page)
            ex = np.where(movable, code_.sx[keys] * ax, 0.0)
            ey = code_.sy[line] * ay
            qx, qy = Px @ ex, Py @ ey
            sx_ = _corr(rxs, qx[selx]) * math.sqrt(nx) if nx >= 6 else 0.0
            sy_ = _corr(rys, L @ qy[sely]) * math.sqrt(ny) if ny >= 4 else 0.0
            w = int(nx >= 6) + int(ny >= 4)
            score = (sx_ + sy_) / math.sqrt(max(w, 1))
            rows.append((score, c, nx + ny))
            viz[c["booklet"]] = (geo, rx, ry, qx, qy, selx, sely)

    if not rows:
        return {"status": "inconclusive", "page": page + 1, "reason": "too_little", "inliers": inliers,
                "elapsed": round(time.time() - t0, 2)}
    rows.sort(key=lambda t: -t[0])
    rhos = np.array([t[0] for t in rows])
    best_rho, best, ndim = rows[0]
    others = rhos[1:]
    sd = max(float(others.std()) if len(others) > 4 else 0.0, 0.85)
    mean = float(others.mean()) if len(others) > 4 else 0.0
    z = (best_rho - mean) / sd
    second = float(others[0]) if len(others) else 0.0
    log10_tail = _log10_normal_tail(z)
    if z >= 6 and (best_rho - second) / sd >= 3.5:
        status = "traced"
    elif z >= 4.5:
        status = "probable"
    else:
        status = "inconclusive"

    geo, rx, ry, qx, qy, selx, sely = viz[best["booklet"]]
    ys, xs = np.where(valid > 0)
    crop = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else [0, 0, Ww, Hh]
    word_viz = [{
        "b": [int(g.box[0]), int(g.box[1]), int(g.box[2]), int(g.box[3])],
        "m": [round(float(rx[i]), 3) if selx[i] else None, round(float(ry[i]), 3) if sely[i] else None],
        "e": [round(float(qx[i]), 3) if selx[i] else None, round(float(qy[i]), 3) if sely[i] else None],
    } for i, g in enumerate(geo)]
    total_words = ref.n_words
    return {
        "status": status,
        "page": page + 1,
        "inliers": inliers,
        "booklet": best["booklet"],
        "score": round(best_rho, 2),
        "second": round(second, 2),
        "z": round(z, 2),
        "log10_odds": round(-log10_tail, 1),
        "words_used": len(geo),
        "dims": ndim,
        "coverage": round(min(1.0, len(geo) / max(total_words, 1)), 3),
        "ranking": [{"booklet": c["booklet"], "centre": c["centre"], "score": round(rh, 2)} for rh, c, _ in rows],
        "viz": {"crop": crop, "size": [Ww, Hh], "words": word_viz, "scale": SCALE},
        "elapsed": round(time.time() - t0, 2),
        "_warped": raw_warp,
        "_valid": valid,
    }


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 0 and nb > 0 else 0.0


def _log10_normal_tail(z: float) -> float:
    """log10 of P(N(0,1) > z), stable for large z."""
    if z < 5:
        return math.log10(max(0.5 * math.erfc(z / math.sqrt(2)), 1e-300))
    return (-(z * z) / 2 - math.log(z * math.sqrt(2 * math.pi))) / math.log(10)
