"""The picker: a frontier model proposes picks from a person's own verdicts in
their own words; the soup keeps it honest.

1. The model is given everything the person has said (verdicts and page
   answers, with their words and notes), what the household watched to the
   end, every title they already know (never to be proposed), and a
   shortlist of recent releases from the soup with their facts, since the
   model's own knowledge stops before them.
2. It proposes titles in the three kinds of pick, each with a one-line reason.
3. The soup resolves each to a real IMDb title, and drops anything
   unresolved, already known, answered or shown before.

Runs through the local `claude` command under the subscription.

Usage: python picker.py PERSON   (prints the resolved proposals)"""
import json
import re
import subprocess
import sys

import duckdb

import content
import household
from core import W

PRIVATE = household.PRIVATE
SHOWN = PRIVATE / "shown.jsonl"
PROPOSE = 40
RECENT = 120
KINDS = {"new": "new and good: out since 2024, or a series still running with a recent season",
         "decent": "decent: widely watched and well made, but not a streaming-homepage staple",
         "niche": "weird niche: little known, strange, cult"}


def claude(prompt, system="You are a film and television expert with deep knowledge of the long tail."):
    out = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config", "--safe-mode",
                          "--setting-sources", "", "--system-prompt", system, "--no-session-persistence"],
                         input=prompt, capture_output=True, text=True, timeout=1200, cwd="/tmp").stdout
    m = re.search(r"[\[{].*[\]}]", out, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def shown(person):
    if not SHOWN.exists():
        return set()
    return {int(json.loads(l)["imdb_id"][2:]) for l in open(SHOWN) if json.loads(l).get("person") == person}


def titles():
    ti = duckdb.sql(f"""select t, title, start_year, end_year, is_series, imdb_rating, imdb_votes, genres
        from '{W}/titles.parquet' where kind in ('movie','tvSeries','tvMiniSeries','tvMovie','tvSpecial')""").df()
    num = ["start_year", "end_year", "is_series", "imdb_rating", "imdb_votes"]
    ti[num] = ti[num].astype(float)
    return ti.set_index("t")


def said_lines(p, ti, hide=()):
    """The person's own verdicts and answers, with their words."""
    lines = []
    for t, (w, why) in sorted(p.evidence.items(), key=lambda x: -x[1][0]):
        if not why.startswith("said") or t in hide or t not in ti.index:
            continue
        r = ti.loc[t]
        year = int(r.start_year) if r.start_year == r.start_year else ""
        words = p.words.get(t)
        lines.append(f"- {r.title} ({year}, {'series' if r.is_series else 'film'}): {why[6:]}"
                     + (f' - "{words}"' if words else ""))
    return lines


def watched_lines(p, ti, hide=()):
    return [f"- {ti.title[t]}" for t, (w, why) in p.evidence.items()
            if "episodes played" in why and w > 0 and t not in hide and t in ti.index]


_RECENT = None


def recent_all(ti):
    """Recent releases with facts, built once (DuckDB connections are not shared across threads)."""
    global _RECENT
    if _RECENT is None:
        pm = duckdb.sql(f"select t, country, network, last_aired from '{W}/plex_meta.parquet'").df().drop_duplicates("t").set_index("t")
        r = ti[(ti.imdb_votes >= 1000) & (ti.imdb_rating >= 7.0)].join(pm)
        new = (r.start_year >= 2024) | ((r.is_series == 1) & (r.last_aired.fillna("") >= "2025-06"))
        r = r[new].sort_values("imdb_votes", ascending=False)
        plots = content.display_plots(220)
        _RECENT = [(t, f"- {x.title} ({int(x.start_year)}, {'series' if x.is_series else 'film'}, {x.country or '?'}"
                       f"{', ' + x.network if isinstance(x.network, str) and x.network else ''}; IMDb {x.imdb_rating}): "
                       f"{plots.get(t, '')}") for t, x in r.iterrows()]
    return _RECENT


def recent_shortlist(p, ti, exclude):
    """Recent releases the model may not know, with their facts, from the soup."""
    return [line for t, line in recent_all(ti) if t not in exclude][:RECENT]


def propose(p, ti, hide=(), n=PROPOSE):
    """Ask the model for n proposals. hide: titles to leave out of everything it is told."""
    hide = set(hide)
    known = sorted({t for t in p.known if t in ti.index and t not in hide})
    known_lines = [f"{ti.title[t]} ({int(ti.start_year[t]) if ti.start_year[t] == ti.start_year[t] else ''})" for t in known]
    prompt = (
        "You pick films and TV for one viewer: discovery of high-quality, stimulating, varied things they have "
        "probably not seen, without falling into the same streaming slop everyone else is shown. Their own words "
        "matter most; read them closely (what they dismiss and why, what they prize, what they say has "
        "dated).\n\n"
        "WHAT THEY HAVE SAID (verdicts and answers, with their words):\n" + "\n".join(said_lines(p, ti, hide)) +
        "\n\nWATCHED TO THE END ON THE HOUSEHOLD'S PLEX (shared viewing, not necessarily their choice):\n"
        + "\n".join(watched_lines(p, ti, hide)) +
        "\n\nALREADY SEEN OR KNOWN: never propose any of these:\n" + "; ".join(known_lines) +
        "\n\nRECENT RELEASES YOU MAY NOT KNOW (facts from a database; use them for the 'new and good' kind):\n"
        + "\n".join(recent_shortlist(p, ti, set(known) | hide)) +
        f"\n\nPropose {n} titles they have probably not seen, about a third of each kind:\n"
        + "\n".join(f"- {k}: {v}" for k, v in KINDS.items()) +
        "\nVary them: no more than a few of any one sort of show. Prefer series to films, about two to one. Give "
        "the exact title and first-release year so it can be looked up. For each, one line on why it is for this "
        "viewer, tied to their own titles and words.\n\n"
        'Reply with only JSON: [{"title": "...", "year": 2020, "kind_of_title": "series"|"film", '
        '"pick": "new"|"decent"|"niche", "why": "..."}]')
    return claude(prompt) or []


_RESOLVE = None


def resolver(ti):
    global _RESOLVE
    if _RESOLVE is None:
        _RESOLVE = household.resolve_fn(ti.reset_index())
    return _RESOLVE


def resolve_all(proposals, p, ti, exclude):
    resolve = resolver(ti)
    out, seen = [], set()
    for x in proposals:
        try:
            t = resolve(x["title"], x.get("year"), x.get("kind_of_title"))
        except Exception:
            t = None
        status = ("unresolved" if t is None else "known" if t in p.known or t in exclude else
                  "duplicate" if t in seen else "ok")
        if t:
            seen.add(t)
        out.append({**x, "t": t, "status": status})
    return out


def main(person):
    p = household.load(person)
    ti = titles()
    props = resolve_all(propose(p, ti), p, ti, shown(person) | p.answered)
    for x in props:
        print(x["status"], x["pick"], x["title"], x.get("year"), "|", x["why"][:100])


if __name__ == "__main__":
    main(sys.argv[1])
