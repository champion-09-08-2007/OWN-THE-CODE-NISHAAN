"""Text tracer: identify which holder's wording a retyped leak came from.

Every pre-print holder receives its own combination of meaning-preserving
wording choices and option orders; every centre prints its own option order.
A retyped 'guess paper' keeps those choices, so it points back to its source.
"""
from __future__ import annotations

import math
import re
import unicodedata

from rapidfuzz import fuzz

from .model import ExamModel
from .paper import Question, Slot, Variant

EPS = 0.06
LABEL_RE = re.compile(r"(?:^|\s)[\(\[]?([a-dA-D1-4])[\)\]\.:]\s+")


def _normalize(text: str) -> tuple[str, list[int]]:
    """Lowercase, NFKC, collapse whitespace. Returns text and index map to the original."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(text):
        n = unicodedata.normalize("NFKC", ch).lower().replace("−", "-").replace("–", "-")
        for c in n:
            if c.isspace():
                if prev_space:
                    continue
                c, prev_space = " ", True
            else:
                prev_space = False
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def _norm(s: str) -> str:
    return _normalize(s)[0].strip()


def _context(q: Question, slot_index: int, side: str, words: int = 3) -> str:
    segs, k, pos = q.segments, -1, None
    for i, s in enumerate(segs):
        if isinstance(s, Slot):
            k += 1
            if k == slot_index:
                pos = i
                break
    if side == "left":
        txt = "".join(s if isinstance(s, str) else s.alts[0] for s in segs[:pos])
        return " ".join(txt.split()[-words:])
    txt = "".join(s if isinstance(s, str) else s.alts[0] for s in segs[pos + 1:])
    return " ".join(txt.split()[:words])


def _locate_questions(model: ExamModel, text: str) -> list[tuple[Question, int, int]]:
    found = []
    for q in model.questions:
        needle = _norm(q.stem())
        if len(needle) < 10:
            continue
        al = fuzz.partial_ratio_alignment(needle, text, score_cutoff=72)
        if al is None:
            continue
        found.append((q, al.dest_start, al.dest_end, al.score))
    # resolve overlaps: keep the better score
    found.sort(key=lambda t: -t[3])
    kept = []
    for q, s, e, sc in found:
        if all(e <= ks or s >= ke for _, ks, ke in kept):
            kept.append((q, s, e))
    kept.sort(key=lambda t: t[1])
    return kept


def _extract_options(block: str, q: Question) -> list[tuple[int, int, int]]:
    """Returns [(original option index, start, end)] in the order they appear."""
    marks = list(LABEL_RE.finditer(block))
    items = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
        seg = block[start:end].split("\n")[0].strip()
        seg = re.split(r"\s{2,}|\bans\b", seg)[0].strip(" ;,")
        if not seg:
            continue
        best, best_sc, second = None, 0.0, 0.0
        for oi, opt in enumerate(q.options):
            o = _norm(opt)
            sc = 100.0 if seg == o else (fuzz.ratio(seg, o) if len(o) > 2 else 0.0)
            if sc > best_sc:
                best, best_sc, second = oi, sc, best_sc
            elif sc > second:
                second = sc
        if best is not None and best_sc >= 84 and best_sc - second >= 6:
            items.append((best, start, start + len(seg)))
    seen, out = set(), []
    for it in items:
        if it[0] not in seen:
            seen.add(it[0])
            out.append(it)
    if len(out) >= 2:
        return out
    # inline fallback: locate longer option texts directly
    pos = []
    for oi, opt in enumerate(q.options):
        o = _norm(opt)
        if len(o) < 4:
            continue
        al = fuzz.partial_ratio_alignment(o, block, score_cutoff=88)
        if al:
            pos.append((oi, al.dest_start, al.dest_end))
    pos.sort(key=lambda t: t[1])
    return pos if len(pos) >= 2 else []


def _sources(model: ExamModel) -> list[dict]:
    out = [{"id": "S1", "kind": "holder", "variant": model.master}]
    for hid, v in model.soft_variants.items():
        out.append({"id": hid, "kind": "holder", "variant": v})
    for c in model.centres:
        out.append({"id": c["code"], "kind": "centre", "variant": model.print_variants[c["code"]]})
    return out


def stage_of(model: ExamModel, source_id: str) -> str:
    if source_id == "S1":
        return "setting"
    h = model.holder(source_id)
    if h is not None:
        return {1: "moderation", 2: "translation", 3: "print"}.get(h["stage"], "setting")
    return "print"


def ranking_all(ranking: list[dict], model: ExamModel):
    for r in ranking:
        yield stage_of(model, r["id"]), r["posterior"]


def trace_text(model: ExamModel, original: str) -> dict:
    text, imap = _normalize(original)
    located = _locate_questions(model, text)
    evidence = []
    for n, (q, s, e) in enumerate(located):
        nxt = located[n + 1][1] if n + 1 < len(located) else len(text)
        block = text[s:nxt]
        stem_block = text[max(0, s - 12):min(len(text), e + 12)]
        for j, slot in enumerate(q.slots):
            left, right = _norm(_context(q, j, "left")), _norm(_context(q, j, "right"))
            scores = []
            for a_i, alt in enumerate(slot.alts):
                pat = " ".join(x for x in (left, _norm(alt), right) if x)
                al = fuzz.partial_ratio_alignment(pat, stem_block)
                scores.append((al.score if al else 0.0, a_i, al))
            scores.sort(key=lambda t: -t[0])
            top, nxt_sc = scores[0], scores[1][0] if len(scores) > 1 else 0.0
            if top[0] >= 80 and top[0] - nxt_sc >= 3:
                al = top[2]
                base = max(0, s - 12) + al.dest_start
                a_txt = _norm(slot.alts[top[1]])
                off = len(left) + 1 if left else 0
                span = [base + off, base + off + len(a_txt)]
                evidence.append({"q": q.idx, "kind": "slot", "slot": j, "value": top[1], "alts": len(slot.alts),
                                 "text": slot.alts[top[1]], "span": span})
        opts = _extract_options(text[e:nxt], q)
        if len(opts) >= 2:
            seq = [o[0] for o in opts]
            evidence.append({"q": q.idx, "kind": "order", "value": seq,
                             "spans": [[e + o[1], e + o[2]] for o in opts]})

    sources = _sources(model)
    ranking = []
    for src in sources:
        v: Variant = src["variant"]
        score, matched, total = 0.0, 0, 0
        for ev in evidence:
            if ev["kind"] == "slot":
                choice = v.choices[ev["q"]][ev["slot"]]
                p = 1.0 / ev["alts"]
                ok = choice == ev["value"]
            else:
                order = v.order[ev["q"]]
                induced = sorted(ev["value"], key=lambda oi: order.index(oi))
                k = len(ev["value"])
                p = 1.0 / math.factorial(k)
                ok = induced == ev["value"]
            total += 1
            matched += int(ok)
            score += math.log((1 - EPS) / p) if ok else math.log(EPS / (1 - p))
        ranking.append({"id": src["id"], "kind": src["kind"], "matched": matched, "total": total, "score": score})
    ranking.sort(key=lambda r: -r["score"])
    mx = ranking[0]["score"] if ranking else 0.0
    z = sum(math.exp(r["score"] - mx) for r in ranking) or 1.0
    for r in ranking:
        r["posterior"] = math.exp(r["score"] - mx) / z
        r["score"] = round(r["score"], 2)

    best = ranking[0] if ranking else None
    status = "inconclusive"
    stage_post: dict[str, float] = {}
    for r in ranking_all(ranking, model):
        stage_post[r[0]] = stage_post.get(r[0], 0.0) + r[1]
    stage = max(stage_post, key=stage_post.get) if stage_post else None
    if best and best["total"] >= 6:
        frac = best["matched"] / best["total"]
        if best["posterior"] >= 0.999 and frac >= 0.8:
            status = "traced"
        elif best["posterior"] >= 0.95 and frac >= 0.7:
            status = "probable"
        elif stage and stage_post[stage] >= 0.99:
            status = "stage"
    best_v = next((s["variant"] for s in sources if best and s["id"] == best["id"]), None)

    def to_orig(span):
        a, b = span
        if a >= len(imap):
            return None
        return [imap[a], imap[min(b, len(imap)) - 1] + 1]

    marks = []
    for ev in evidence:
        if ev["kind"] == "slot":
            ok = best_v is not None and best_v.choices[ev["q"]][ev["slot"]] == ev["value"]
            sp = to_orig(ev["span"])
            if sp:
                marks.append({"span": sp, "ok": ok, "kind": "slot", "q": ev["q"] + 1})
        else:
            order = best_v.order[ev["q"]] if best_v else []
            ok = best_v is not None and sorted(ev["value"], key=lambda oi: order.index(oi)) == ev["value"]
            for spn in ev["spans"]:
                sp = to_orig(spn)
                if sp:
                    marks.append({"span": sp, "ok": ok, "kind": "order", "q": ev["q"] + 1})
    return {
        "status": status,
        "stage": stage,
        "stage_posterior": round(stage_post.get(stage, 0.0), 6) if stage else 0.0,
        "best": best,
        "ranking": ranking[:12],
        "questions_found": len(located),
        "questions_total": len(model.questions),
        "evidence_count": len(evidence),
        "marks": sorted(marks, key=lambda m: m["span"][0]),
    }
