"""What each person in the household has told us, directly or through what
they watched, as weighted taste evidence, and every title they already know.

Reads only private/ at run time. Weights (1 = a loved title):
- stated verdicts and page answers: loved 1, liked 0.6, seen and fine 0.3,
  disliked -1, slop -1 (a judgement on the show, which also counts against
  shows like it), not for me -0.5 (a no without a reason); wanting a title
  counts 0.3 as interest. "Not right now" is no judgement: it carries no
  weight, and only holds the title back for NOT_NOW_DAYS;
- a show watched to the end on Plex 0.5, dropped after one episode -0.3, a
  film played 0.2; plays are the household's, so a title one person said they
  dislike counts only for the other person;
- a title kept in the Plex library: shows 0.05, films 0.03. About 70% of the
  shows and half the films have been seen, but there are hundreds of them, so
  together they must not outweigh a few stated verdicts. picks.py counts them
  as known titles and as "have you seen this?" questions, not as taste, until
  the person answers.
Viewing and library evidence fades with age, halving every HALF_LIFE years,
dated by Plex plays or, for library titles, by the era their release name
suggests. What a person says now does not fade."""
import csv
import json
import re
import time
from datetime import datetime
import unicodedata
from dataclasses import dataclass, field

import duckdb

from core import W

PRIVATE = W.parent.parent.parent / "private"
HALF_LIFE = 8.0
LIB_SHOW, LIB_FILM = 0.05, 0.03  # hundreds of library titles must not outweigh a few stated verdicts
NOW = 2026.9
VERDICT = {"loved": 1.0, "liked": 0.6, "disliked": -1.0}
ANSWER = {"seen_loved": 1.0, "seen_fine": 0.3, "seen_disliked": -1.0, "want": 0.3, "not_for_me": -0.5,
          "slop": -1.0}
NOT_NOW_DAYS = 42  # a "not right now" title may be offered again after this long


@dataclass
class Person:
    name: str
    evidence: dict = field(default_factory=dict)   # tconst int -> (weight, why)
    known: set = field(default_factory=set)         # never offer these
    words: dict = field(default_factory=dict)       # tconst -> their own words
    answered: set = field(default_factory=set)      # titles they answered on the page
    in_library: set = field(default_factory=set)    # the household's Plex library

    def add(self, t, w, why):
        old = self.evidence.get(t)
        # A direct statement replaces inferred evidence; otherwise the stronger signal wins.
        if old is None or why.startswith("said") or (not old[1].startswith("said") and abs(w) > abs(old[0])):
            self.evidence[t] = (w, why)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def decay(year):
    return 0.5 ** (max(0.0, NOW - year) / HALF_LIFE)


def release_era(name):
    """The year a release was probably downloaded, from its name: no earlier than
    the film's own year, and no earlier than its file format became common."""
    y = re.findall(r"(?<!\d)(19[2-9]\d|20[0-2]\d)(?!\d)", name)
    year = int(y[-1]) if y else None
    low, high = 2012, 2026
    n = name.lower()
    if re.search(r"2160p|uhd|x265|hevc|h\.?265|\bdv\b|hdr|atmos|ddp", n):
        low = 2019
    elif re.search(r"web-?dl|webrip|amzn|nf\.", n):
        low = 2014
    elif re.search(r"1080p|720p|bluray|x264", n):
        low = 2010
    elif re.search(r"xvid|divx|dvdrip|axxo|\.avi$|\bts\b|dvdscr", n):
        low, high = 2004, 2012
    if year is None:
        return None, low
    return year, min(max(year, low), high)


def titles():
    ti = duckdb.sql(f"select t, title, start_year, is_series, n_episodes from '{W}/titles.parquet' "
                    f"where kind in ('movie','tvSeries','tvMiniSeries','tvMovie','tvSpecial')").df()
    return ti


def resolve_fn(ti):
    by = {}
    for t, title, y, s, votes in duckdb.sql(f"""select t, title, start_year, is_series, imdb_votes from '{W}/titles.parquet'
            where kind in ('movie','tvSeries','tvMiniSeries','tvMovie','tvSpecial')""").fetchall():
        by.setdefault(norm(title), []).append((votes or 0, t, y, s))

    def resolve(title, year=None, kind=None):
        c = by.get(norm(title), [])
        if kind:
            c = [x for x in c if bool(x[3]) == (kind == "series")]
        if year:
            c = [x for x in c if x[2] and abs(x[2] - int(year)) <= 1]
        return max(c)[1] if c else None
    return resolve


def library_eras(library, resolve):
    """Library title -> estimated year it was added, from the NAS release names."""
    eras = {}
    for line in open(PRIVATE / "nas_release_names.txt"):
        name = line.strip().rsplit("/", 1)[-1]
        year, era = release_era(name)
        base = re.split(r"[\[(]?(?:19[2-9]\d|20[0-2]\d)", name.replace(".", " "))[0]
        base = re.sub(r"\bS\d\d.*", "", base, flags=re.I)
        t = resolve(base.strip(" -_#"), year)
        if t:
            eras[t] = era
    return eras


def load(person, ti=None):
    ti = titles() if ti is None else ti
    resolve = resolve_fn(ti)
    nep = dict(zip(ti.t, ti.n_episodes))
    p = Person(person)
    other_dislikes = set()

    for r in csv.DictReader(open(PRIVATE / "verdicts.csv")):
        if not r["target"].startswith("tt"):
            continue
        t = int(r["target"][2:])
        if r["person"] != person:
            if r["verdict"] == "disliked":
                other_dislikes.add(t)
            continue
        p.known.add(t)
        if r["verdict"] in VERDICT:
            p.add(t, VERDICT[r["verdict"]], f"said: {r['verdict']}")
            p.words[t] = r["words"]
    if (PRIVATE / "known.csv").exists():
        for r in csv.DictReader(open(PRIVATE / "known.csv")):
            if r["person"] == person and r["target"].startswith("tt"):
                t = int(r["target"][2:])
                p.known.add(t)
                if r["state"] == "wants":
                    p.add(t, 0.3, "said: wants to watch")
    if (PRIVATE / f"{person}_evidence.csv").exists():
        for r in csv.DictReader(open(PRIVATE / f"{person}_evidence.csv")):
            t = int(r["target"][2:]) if r["target"].startswith("tt") else resolve(r["title"])
            if t:
                p.known.add(t)
                w = {"watched alone": 0.8, "watched": 0.5, "requested": 0.4, "wants": 0.3}[r["signal"]]
                p.add(t, w, f"said: {r['signal']} ({r['source']})")
    if (PRIVATE / "swipes.jsonl").exists():
        latest = {}
        for line in open(PRIVATE / "swipes.jsonl"):
            a = json.loads(line)
            if a.get("person") == person:
                latest[a["imdb_id"]] = a
        for tc, a in latest.items():
            t = int(tc[2:])
            p.answered.add(t)
            if a["answer"] == "not_now":
                # No judgement on the title or its kind: it is only held back for a while.
                age = time.time() - datetime.fromisoformat(a["ts"]).timestamp() if a.get("ts") else 0
                if age < NOT_NOW_DAYS * 86400:
                    p.known.add(t)
                else:
                    p.answered.discard(t)
                continue
            if a["answer"] != "dont_know":
                p.known.add(t)
            if a["answer"] in ANSWER:
                p.add(t, ANSWER[a["answer"]], f"said: {a['answer']}")
                if a.get("note"):
                    p.words[t] = a["note"]

    # Household: seen elsewhere, watch list, library, plays.
    for r in csv.DictReader(open(PRIVATE / "seen_elsewhere.csv")):
        t = resolve(r["title"], r["year"], r["kind"]) or (resolve(r["note"], r["year"], r["kind"]) if r["note"] else None)
        if t:
            p.known.add(t)
    for r in csv.DictReader(open(PRIVATE / "watchlist.csv")):
        t = resolve(r["title"], None, r["kind"])
        if t:
            p.known.add(t)
            if r.get("verdict") == "disliked" and r.get("person", person) == person:
                p.add(t, -1.0, "said: disliked")
    library = [json.loads(l) for l in open(PRIVATE / "plex_library.jsonl")]
    eras = library_eras(library, resolve)
    in_library = set()
    for x in library:
        if not x.get("imdb"):
            continue
        t = int(x["imdb"].split("tt")[-1])
        in_library.add(t)
        p.known.add(t)
        if t in other_dislikes:
            continue
        year = eras.get(t, max(x.get("year") or 2014, 2014))
        p.add(t, (LIB_SHOW if x["section"] == 2 else LIB_FILM) * decay(year), "in the Plex library")

    plays = json.load(open(PRIVATE / "plex_plays.json"))
    eps, last = {}, {}
    for x in plays:
        t = int(x["tconst"][2:]) if x.get("tconst") else None
        if not t:
            continue
        p.known.add(t)
        key = (x.get("season"), x.get("episode")) if x["type"] == "episode" else "film"
        eps.setdefault(t, set()).add(key)
        last[t] = max(last.get(t, 0), x["viewed_at"])
    for t, e in eps.items():
        mine = t not in other_dislikes and p.evidence.get(t, (0, ""))[0] >= 0
        year = 1970 + last[t] / 31557600
        if "film" in e:
            w, why = 0.1, "played on Plex"
        elif len(e) >= max(6, 0.8 * (nep.get(t) or 99)) or len(e) >= 20:
            w, why = 0.5, f"{len(e)} episodes played on Plex"
        elif len(e) == 1 and time.time() - last[t] > 30 * 86400:
            w, why = -0.3, "dropped after one episode on Plex"
        else:
            continue
        if t in other_dislikes:
            w, why = 0.8, why + ", which the other person disliked"
        elif not mine:
            continue
        p.add(t, w * decay(year), why)
    p.in_library = in_library
    return p
