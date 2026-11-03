"""SQLite storage and the hash-chained custody ledger."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS exam (id INTEGER PRIMARY KEY, secret TEXT, title TEXT, subtitle TEXT,
  created_at REAL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS centre (exam_id INTEGER, code TEXT, city TEXT, area TEXT, press TEXT,
  rooms TEXT, PRIMARY KEY (exam_id, code));
CREATE TABLE IF NOT EXISTS holder (exam_id INTEGER, id TEXT, stage INTEGER, role TEXT, label TEXT,
  PRIMARY KEY (exam_id, id));
CREATE TABLE IF NOT EXISTS run (id INTEGER PRIMARY KEY, exam_id INTEGER, created_at REAL,
  per_centre INTEGER, total INTEGER, file TEXT);
CREATE TABLE IF NOT EXISTS copy (exam_id INTEGER, booklet TEXT, centre TEXT, room TEXT, seat INTEGER,
  roll TEXT, run_id INTEGER, printed_at REAL, PRIMARY KEY (exam_id, booklet));
CREATE TABLE IF NOT EXISTS trace (id INTEGER PRIMARY KEY, exam_id INTEGER, ts REAL, kind TEXT,
  channel TEXT, status TEXT, summary TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS ledger (seq INTEGER PRIMARY KEY, ts REAL, type TEXT, actor TEXT,
  subject TEXT, payload TEXT, prev TEXT, hash TEXT);
"""

GENESIS = "0" * 64


def _hash(seq, ts, typ, actor, subject, payload, prev) -> str:
    raw = f"{seq}|{ts:.3f}|{typ}|{actor}|{subject}|{payload}|{prev}"
    return hashlib.sha256(raw.encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def many(self, sql: str, rows) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    # ------------------------------------------------------------ exam
    def active_exam(self):
        rows = self.q("SELECT * FROM exam WHERE active=1 ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def centres(self, exam_id: int) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM centre WHERE exam_id=? ORDER BY rowid", (exam_id,)):
            d = dict(r)
            d["rooms"] = json.loads(d["rooms"])
            out.append(d)
        return out

    def holders(self, exam_id: int) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM holder WHERE exam_id=? ORDER BY stage, id", (exam_id,))]

    def copies(self, exam_id: int) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM copy WHERE exam_id=? ORDER BY booklet", (exam_id,))]

    def copy(self, exam_id: int, booklet: str):
        rows = self.q("SELECT * FROM copy WHERE exam_id=? AND booklet=?", (exam_id, booklet))
        return dict(rows[0]) if rows else None

    def latest_run(self, exam_id: int):
        rows = self.q("SELECT * FROM run WHERE exam_id=? ORDER BY id DESC LIMIT 1", (exam_id,))
        return dict(rows[0]) if rows else None

    # ------------------------------------------------------------ traces
    def add_trace(self, exam_id, kind, channel, status, summary, result) -> int:
        return self.x("INSERT INTO trace (exam_id, ts, kind, channel, status, summary, result) VALUES (?,?,?,?,?,?,?)",
                      (exam_id, time.time(), kind, channel, status, json.dumps(summary), json.dumps(result)))

    def traces(self, exam_id: int, limit: int = 30) -> list[dict]:
        out = []
        for r in self.q("SELECT id, ts, kind, channel, status, summary FROM trace WHERE exam_id=? "
                        "ORDER BY id DESC LIMIT ?", (exam_id, limit)):
            d = dict(r)
            d["summary"] = json.loads(d["summary"])
            out.append(d)
        return out

    def trace(self, tid: int):
        rows = self.q("SELECT * FROM trace WHERE id=?", (tid,))
        if not rows:
            return None
        d = dict(rows[0])
        d["summary"] = json.loads(d["summary"])
        d["result"] = json.loads(d["result"])
        return d

    def trace_count(self, exam_id: int) -> int:
        return self.q("SELECT COUNT(*) AS n FROM trace WHERE exam_id=?", (exam_id,))[0]["n"]

    # ------------------------------------------------------------ ledger
    def append(self, typ: str, actor: str, subject: str, payload: dict | None = None) -> dict:
        with self.lock:
            last = self.q("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1")
            seq = (last[0]["seq"] + 1) if last else 1
            prev = last[0]["hash"] if last else GENESIS
            ts = round(time.time(), 3)
            pl = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
            h = _hash(seq, ts, typ, actor, subject, pl, prev)
            self.conn.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)", (seq, ts, typ, actor, subject, pl, prev, h))
            self.conn.commit()
            return {"seq": seq, "ts": ts, "type": typ, "actor": actor, "subject": subject,
                    "payload": json.loads(pl), "prev": prev, "hash": h}

    def ledger(self, limit: int = 200, before: int | None = None) -> list[dict]:
        if before:
            rows = self.q("SELECT * FROM ledger WHERE seq<? ORDER BY seq DESC LIMIT ?", (before, limit))
        else:
            rows = self.q("SELECT * FROM ledger ORDER BY seq DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    def ledger_head(self) -> dict:
        rows = self.q("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1")
        return {"count": rows[0]["seq"] if rows else 0, "head": rows[0]["hash"] if rows else GENESIS}

    def verify(self) -> dict:
        prev, n = GENESIS, 0
        for r in self.q("SELECT * FROM ledger ORDER BY seq"):
            n += 1
            if r["prev"] != prev or _hash(r["seq"], r["ts"], r["type"], r["actor"], r["subject"],
                                          r["payload"], r["prev"]) != r["hash"]:
                return {"ok": False, "count": n, "broken_at": r["seq"]}
            prev = r["hash"]
        return {"ok": True, "count": n, "head": prev}
