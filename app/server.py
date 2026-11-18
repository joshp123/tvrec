"""Serve the picks page and record answers.

    python3 app/server.py

Reads <private>/cards/<person>.json on every request and appends each answer
to <private>/swipes.jsonl. <private> is ./private unless TVREC_PRIVATE says
otherwise; the port is 8788 unless TVREC_PORT says otherwise. It listens on
this machine only unless TVREC_HOST names another address to listen on.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get("TVREC_PRIVATE", HERE.parent / "private"))
CARDS = PRIVATE / "cards"
SWIPES = PRIVATE / "swipes.jsonl"
ANSWERS = {"want", "not_for_me", "seen_loved", "seen_fine", "seen_disliked", "dont_know"}
lock = threading.Lock()


def people():
    return sorted(p.stem for p in CARDS.glob("*.json"))


def answers(person):
    """The latest answer per title; a later line replaces an earlier one."""
    out = {}
    if SWIPES.exists():
        for line in SWIPES.read_text().splitlines():
            row = json.loads(line)
            if row["person"] == person:
                out[row["imdb_id"]] = row
    return out


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/people":
            return self.send(200, people())
        if self.path.startswith("/api/deck/"):
            person = self.path.removeprefix("/api/deck/")
            if person not in people():
                return self.send(404, {"error": f"no cards for {person}"})
            deck = json.loads((CARDS / f"{person}.json").read_text())
            return self.send(200, {"deck": deck, "answers": answers(person)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/answer":
            return self.send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("person") not in people() or body.get("answer") not in ANSWERS or not body.get("imdb_id"):
            return self.send(400, {"error": "need a known person, an imdb_id and one of " + ", ".join(sorted(ANSWERS))})
        row = {"person": body["person"], "imdb_id": body["imdb_id"], "answer": body["answer"]}
        if (body.get("note") or "").strip():
            row["note"] = body["note"].strip()
        row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with lock, SWIPES.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.send(200, row)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("TVREC_PORT", 8788))
    ThreadingHTTPServer((os.environ.get("TVREC_HOST", "127.0.0.1"), port), Handler).serve_forever()
