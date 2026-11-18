"""Build a stand-in cards file until the engine writes its own.

    python3 app/sample.py <person>

Reads the person's old picks (private/backlog-level1.md), a hand-made taste
map (private/sample/taste-<person>.json), the library (private/
plex_library.jsonl), verdicts and the soup, and writes private/cards/<person>.json
with "sample": true. It never overwrites a file the engine wrote.
"""
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "private"
LINE = re.compile(r"^- \*\*(.+?)\*\* \((\d{4})[^,]*, (series|film)\)\. (.*) Why: (.*)\.$")
LINK = re.compile(r"rated (.+?) highly|who created (.+?)$|directed (.+?)$|made by (.+?), whose")


def poster(url):
    return url.replace("/t/p/original/", "/t/p/w500/") if url else None


def plex_metadata(ids):
    out = {}
    with open(ROOT / "data/raw/plex_metadata/metadata.jsonl") as f:
        for line in f:
            row = json.loads(line)
            if row["tconst"] in ids:
                out[row["tconst"]] = row["metadata"]
    return out


def resolve(db, title, year, series):
    rows = db.execute(
        "select tconst from title where (primary_title = ? or original_title = ?) "
        "and start_year between ? and ? and is_series = ? order by imdb_votes desc limit 1",
        (title, title, year - 1, year + 1, int(series))).fetchall()
    return rows[0][0] if rows else None


def facts(db, meta, t):
    row = db.execute("select primary_title, start_year, end_year, is_series, runtime_min, "
                     "n_seasons, imdb_rating, imdb_votes from title where tconst = ?", (t,)).fetchone()
    title, start, end, series, runtime, seasons, rating, votes = row
    scores = dict(db.execute("select scorer, score from public_score where tconst = ?", (t,)).fetchall())
    country = db.execute("select countries from plex_title where tconst = ?", (t,)).fetchone()
    m = meta.get(t, {})
    pct = lambda s: round(s * 10) if s is not None else None
    return {
        "imdb_id": t, "title": title, "year": start, "end_year": end,
        "kind": "series" if series else "film",
        "seasons": seasons, "runtime_min": runtime,
        "country": (country[0] or "").split(", ")[0] if country else None,
        "imdb_rating": rating, "imdb_votes": votes,
        "rt_critics": pct(scores.get("rotten_tomatoes_critics")),
        "rt_audience": pct(scores.get("rotten_tomatoes_audience")),
        "poster": poster(m.get("thumb")),
        "what": m.get("summary"),
    }


def main(person):
    out = PRIVATE / "cards" / f"{person}.json"
    if out.exists() and not json.loads(out.read_text()).get("sample"):
        sys.exit(f"{out} was written by the engine; not overwriting it")
    db = sqlite3.connect(f"file:{ROOT / 'data/soup.sqlite'}?mode=ro", uri=True)
    taste = json.loads((PRIVATE / "sample" / f"taste-{person}.json").read_text())

    picks, lane = [], None
    for line in (PRIVATE / "backlog-level1.md").read_text().splitlines():
        if line.startswith("## "):
            lane = line[3:]
        elif m := LINE.match(line):
            if lane.startswith("Check"):
                continue
            title, year, kind, _, why = m.groups()
            t = resolve(db, title, int(year), kind == "series")
            if t:
                links = [g for mm in LINK.finditer(why) for g in mm.groups() if g and g != "this"]
                picks.append((t, lane, why, links))

    library = [json.loads(l) for l in open(PRIVATE / "plex_library.jsonl")]
    lib_ids = {r["imdb"].removeprefix("imdb://") for r in library if r.get("imdb")}
    said = set()
    for name in ("verdicts.csv", "known.csv"):
        said |= {r["target"] for r in csv.DictReader(open(PRIVATE / name)) if r["person"] == person}

    examples = {t for c in taste["clusters"] for t in c["examples"]} | set(taste["away_from"])
    meta = plex_metadata({p[0] for p in picks} | lib_ids | examples)

    def brief(t):
        f = facts(db, meta, t)
        return {k: f[k] for k in ("imdb_id", "title", "year", "kind", "poster")}

    cluster_of = {}
    for c in taste["clusters"]:
        cluster_of |= {maker: c["name"] for maker in c.get("makers", [])}
        for t in c["examples"]:
            cluster_of[db.execute("select primary_title from title where tconst = ?", (t,)).fetchone()[0]] = c["name"]

    cards = []
    for t, lane, why, links in picks:
        if t in said:
            continue
        card = facts(db, meta, t)
        card.update(pick_kind=lane, why=why + ".", links=links, in_library=t in lib_ids,
                    cluster=None if "people who rated" in why else
                    next((cluster_of[l] for l in links if l in cluster_of), None))
        cards.append(card)

    clusters = []
    for c in taste["clusters"]:
        clusters.append({**c, "examples": [brief(t) for t in c["examples"]],
                         "nearby": [{k: x[k] for k in ("imdb_id", "title", "year", "kind", "poster")}
                                    for x in cards if x["cluster"] == c["name"]]})

    seen = []
    for r in library:
        t = r["imdb"].removeprefix("imdb://") if r.get("imdb") else None
        if not t or t in said or not db.execute("select 1 from title where tconst = ?", (t,)).fetchone():
            continue
        f = facts(db, meta, t)
        seen.append({k: f[k] for k in ("imdb_id", "title", "year", "end_year", "kind", "seasons",
                                        "runtime_min", "imdb_votes", "poster", "what")})
    seen.sort(key=lambda x: (x["kind"] != "series", -(x["imdb_votes"] or 0)))

    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "person": person, "sample": True,
        "taste_map": {"clusters": clusters, "away_from": [brief(t) for t in taste["away_from"]]},
        "cards": cards, "seen_deck": seen,
    }, ensure_ascii=False, indent=1))
    print(f"{out}: {len(cards)} cards, {len(clusters)} clusters, {len(seen)} in the seen deck")


if __name__ == "__main__":
    main(sys.argv[1])
