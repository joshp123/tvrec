"""Download Plex's public metadata (plot summary, Rotten Tomatoes, IMDb and
TMDB scores, country, genres, makers, Plex's similar titles) for titles in
the soup, into data/raw/plex_metadata/metadata.jsonl, one JSON object per
title. Resumable: titles already fetched are skipped.

Plex's metadata service needs a Plex account token, read from PLEX_TOKEN.
Per-account fields (userState) are dropped before saving.

    PLEX_TOKEN=... uv run python -m soup.fetch_plex

Titles come from data/soup.sqlite, so build the soup first. Order: series with at least 20 IMDb votes or 5 ratings in the soup, then
films with at least 100 votes or 5 ratings, most-voted first.
"""

import json
import os
import sys
import time
import sqlite3
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .db import RAW, SOUP

URL = "https://metadata.provider.plex.tv/library/metadata/matches?type={type}&guid=imdb://{tconst}"
OUT = RAW / "plex_metadata" / "metadata.jsonl"
WORKERS = 4


def wanted(con):
    return con.execute("""
    with rated as (select tconst, count(*) as n from rating where tconst is not null group by 1)
    select tconst, is_series from title t left join rated r using (tconst)
    where (is_series and (imdb_votes >= 20 or r.n >= 5))
       or (kind in ('movie', 'tvMovie', 'tvSpecial') and (imdb_votes >= 100 or r.n >= 5))
    order by is_series desc, imdb_votes desc
    """).fetchall()


def fetch(token, tconst, is_series):
    req = urllib.request.Request(URL.format(type=2 if is_series else 1, tconst=tconst),
                                 headers={"X-Plex-Token": token, "Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                found = json.load(r)["MediaContainer"].get("Metadata") or []
            break
        except Exception as e:  # noqa: BLE001 - retried, then recorded as missing
            if getattr(e, "code", None) == 404:
                found = []
                break
            time.sleep(2 ** attempt)
    else:
        return None
    meta = found[0] if found else {}
    meta.pop("userState", None)
    return {"tconst": tconst, "metadata": meta or None}


def main():
    token = os.environ["PLEX_TOKEN"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        with open(OUT) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["tconst"])
                except json.JSONDecodeError:
                    pass  # a line cut short by an interrupted run
    con = sqlite3.connect(f"file:{SOUP}?mode=ro", uri=True)
    todo = [(t, s) for t, s in wanted(con) if t not in done]
    con.close()
    print(f"{len(done)} done, {len(todo)} to fetch", flush=True)
    with open(OUT, "a") as out, ThreadPoolExecutor(WORKERS) as pool:
        for i, rec in enumerate(pool.map(lambda a: fetch(token, *a), todo), 1):
            if rec:
                out.write(json.dumps(rec) + "\n")
            if i % 5000 == 0:
                out.flush()
                print(i, flush=True)


if __name__ == "__main__":
    sys.exit(main())
