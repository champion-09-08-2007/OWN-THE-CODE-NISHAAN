"""Optional Telegram bot: forward a leaked photo or text, get the source back.

Runs only when TELEGRAM_BOT_TOKEN is set in the environment.
"""
from __future__ import annotations

import threading
import time

import httpx


def _reply(r: dict) -> str:
    st = r.get("status")
    if r.get("kind") == "photo":
        if st in ("traced", "probable") and r.get("custody"):
            c = r["custody"]
            head = "Traced" if st == "traced" else "Probable match"
            return (f"{head}: booklet {c['booklet']}\n"
                    f"{c['city']}, {c['area']} ({c['centre']})\n"
                    f"Room {c['room']}, seat {c['seat']}, roll {c['roll']}\n"
                    f"Invigilator {c['invigilator']}\n"
                    f"Printed by {c['press_label']}\n"
                    f"Strength {r.get('z')}σ, page {r.get('page')}")
        if st == "unregistered":
            return "This photo does not show a page of the current paper."
        return "Not enough of the page is readable. Send a sharper or wider photo."
    b = r.get("best") or {}
    if st in ("traced", "probable"):
        c = r.get("custody") or {}
        where = c.get("label") or f"{c.get('city', '')}, {c.get('area', '')} ({c.get('id', '')})"
        return (f"{'Traced' if st == 'traced' else 'Probable source'}: {where}\n"
                f"{b.get('matched')} of {b.get('total')} canary marks match")
    if st == "stage":
        return f"Leak came from the {r.get('stage_label', r.get('stage'))} stage."
    return "No canary marks found in this text."


class TelegramBot(threading.Thread):
    def __init__(self, token: str, svc):
        super().__init__(daemon=True)
        self.token, self.svc = token, svc
        self.api = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    def run(self) -> None:
        with httpx.Client(timeout=40) as http:
            while True:
                try:
                    res = http.get(f"{self.api}/getUpdates", params={"timeout": 25, "offset": self.offset}).json()
                    for up in res.get("result", []):
                        self.offset = up["update_id"] + 1
                        self.handle(http, up.get("message") or {})
                except Exception:
                    time.sleep(3)

    def handle(self, http: httpx.Client, msg: dict) -> None:
        chat = (msg.get("chat") or {}).get("id")
        if not chat:
            return
        file_id = None
        if msg.get("photo"):
            file_id = msg["photo"][-1]["file_id"]
        elif (msg.get("document") or {}).get("mime_type", "").startswith("image/"):
            file_id = msg["document"]["file_id"]
        text = msg.get("text") or msg.get("caption") or ""
        if file_id:
            path = http.get(f"{self.api}/getFile", params={"file_id": file_id}).json()["result"]["file_path"]
            data = http.get(f"https://api.telegram.org/file/bot{self.token}/{path}").content
            result = self.svc.trace_photo(data, "telegram")
        elif len(text) > 80:
            result = self.svc.trace_text(text, "telegram")
        else:
            http.post(f"{self.api}/sendMessage", json={"chat_id": chat,
                      "text": "Send a photo of a leaked page, or paste the leaked text."})
            return
        http.post(f"{self.api}/sendMessage", json={"chat_id": chat, "text": _reply(result)})
