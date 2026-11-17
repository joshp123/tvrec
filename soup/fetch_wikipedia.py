"""Download the plain-text lead section of the English Wikipedia article of
every title that Wikidata links to one, into
data/raw/wikipedia/intros.jsonl ({"enwiki": article, "text": ...}).
Resumable. Titles come from data/soup.sqlite, so build the soup first.

    uv run python -m soup.fetch_wikipedia
"""

import json
import sqlite3
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .db import RAW, SOUP

API = "https://en.wikipedia.org/w/api.php"
OUT = RAW / "wikipedia" / "intros.jsonl"
HEADERS = {"User-Agent": "tvrec/0.1 (personal film and TV research; https://github.com/joshp123/tvrec)"}
BATCH = 20  # the API's limit for lead-section extracts
WORKERS = 5


def fetch(articles):
    params = {"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
              "redirects": 1, "format": "json", "formatversion": 2, "maxlag": 5,
              "titles": "|".join(a.replace("_", " ") for a in articles)}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=HEADERS)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                q = json.load(r)
            if "error" in q:
                raise RuntimeError(q["error"])
            q = q.get("query", {})
            break
        except Exception as e:  # noqa: BLE001 - lag, throttling or network: back off
            print("retry", attempt, repr(e)[:200], flush=True)
            time.sleep(2 ** attempt)
    else:
        return []
    # Follow the API's renames back to the article names we asked for.
    back = {}
    for step in q.get("normalized", []) + q.get("redirects", []):
        back[step["to"]] = back.get(step["from"], step["from"])
    out = []
    for page in q.get("pages", []):
        asked = back.get(page["title"], page["title"])
        out.append({"enwiki": asked.replace(" ", "_"), "text": page.get("extract") or None})
    return out


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        with open(OUT) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["enwiki"])
                except json.JSONDecodeError:
                    pass
    con = sqlite3.connect(f"file:{SOUP}?mode=ro", uri=True)
    articles = [a for (a,) in con.execute("""
        select distinct l.enwiki from title_link l join title t using (tconst)
        where l.enwiki is not null order by 1""").fetchall()
                if urllib.parse.unquote(a) not in done and a not in done]
    con.close()
    articles = [urllib.parse.unquote(a) for a in articles]
    batches = [articles[i:i + BATCH] for i in range(0, len(articles), BATCH)]
    print(f"{len(done)} done, {len(articles)} to fetch in {len(batches)} requests", flush=True)
    with open(OUT, "a") as out, ThreadPoolExecutor(WORKERS) as pool:
        for i, recs in enumerate(pool.map(fetch, batches), 1):
            for rec in recs:
                out.write(json.dumps(rec) + "\n")
            if i % 500 == 0:
                out.flush()
                print(i, flush=True)


if __name__ == "__main__":
    main()
