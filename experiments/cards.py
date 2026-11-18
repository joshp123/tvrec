"""Write private/cards/<person>.json for the picks page (app/README.md has the
shape; docs/cards.md lists the fields added here): the person's taste map,
their picks as cards, and a deck of "have you seen this?" questions.

Each card carries its evidence as data (evidence.py). The "what it is", "why
you" and "why not" lines are written from that evidence by the frontier model
through the local `claude` command, once per title and person, cached in
private/card_text.json. Choosing picks uses no AI model.

Usage: python cards.py PERSON [OTHER_PERSON]"""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import content
import evidence as EV
import extras
import household
import name_clusters
import picks as P
from core import W

PRIVATE = household.PRIVATE
CACHE = PRIVATE / "card_text.json"
MAP_CLUSTERS, EXAMPLES, NEARBY, DECK = 15, 6, 4, 40
KIND_NAME = {"new": "New and good", "decent": "Decent", "niche": "Weird niche"}


def poster(url):
    return url.replace("/t/p/original/", "/t/p/w500/") if isinstance(url, str) else None


def tile(F, t):
    o = F.ref(t)
    p = poster(F.pm.poster.get(t)) if t in F.pm.index else None
    if p:
        o["poster"] = p
    return {k: v for k, v in o.items() if v is not None}


def soup_links(ts):
    con = sqlite3.connect(f"file:{W.parent.parent}/soup.sqlite?mode=ro", uri=True)
    q = ",".join(f"'tt{t:07d}'" for t in ts)
    rows = con.execute(f"select tconst, tmdb_movie, tmdb_tv, enwiki from title_link where tconst in ({q})").fetchall()
    return {int(a[2:]): {"tmdb_movie": b, "tmdb_tv": c, "enwiki": d} for a, b, c, d in rows}


def write_text(person, summary, items):
    """items: card facts and evidence. Returns {imdb_id: {what, why, why_not}}."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    out, todo = {}, []
    for it in items:
        key = hashlib.sha1(json.dumps([summary, it], sort_keys=True).encode()).hexdigest()[:12]
        c = cache.get(f"{person}|{it['imdb_id']}")
        if c and c["key"] == key:
            out[it["imdb_id"]] = c
        else:
            todo.append((key, it))

    def ask(batch):
        prompt = (
            f"{summary}\n\nEach title below is a pick for this viewer, with facts and evidence. For each, write "
            "three texts for a card on their phone, in British English, plainly, with no em dashes and no "
            "marketing language:\n"
            "\"what\": what it is, in three or four sentences, the way you would tell a friend: the premise "
            "(who, where, what happens), the tone, and what makes it distinctive. Use the fuller premise "
            "where given.\n"
            "\"why\": why it is for this viewer, in two or three sentences, from the evidence: name their own "
            "titles it links to and how (made by the same people, loved by the same audience, the cluster it "
            "sits in), and what is different about it if it is a stretch. Say a number only if it is a count "
            "of people from the evidence and it helps.\n"
            "\"why_not\": one sentence on the strongest thing against it, from the 'against' evidence; empty "
            "if there is nothing.\n"
            "Use only the facts given and what you reliably know about the title.\n\n"
            "Reply with only a JSON list of objects with keys imdb_id, what, why, why_not.\n\n"
            + "\n\n".join(json.dumps(it, ensure_ascii=False) for _, it in batch))
        res = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config", "--safe-mode",
                              "--setting-sources", "", "--system-prompt",
                              "You are a film and television expert writing for a friend.",
                              "--no-session-persistence"], input=prompt, capture_output=True, text=True,
                             timeout=900, cwd="/tmp").stdout
        m = re.search(r"\[.*\]", res, re.S)
        try:
            got = {r["imdb_id"]: r for r in json.loads(m.group(0))} if m else {}
        except json.JSONDecodeError:
            got = {}
        return [(key, it, got.get(it["imdb_id"])) for key, it in batch]

    batches = [todo[i:i + 6] for i in range(0, len(todo), 6)]
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(ask, batches):
            for key, it, r in res:
                if r and r.get("what") and r.get("why"):
                    c = {"key": key, "what": r["what"], "why": r["why"], "why_not": r.get("why_not") or ""}
                    cache[f"{person}|{it['imdb_id']}"] = c
                    out[it["imdb_id"]] = c
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return out


def main(person, other_name=None):
    p = household.load(person)
    other = household.load(other_name) if other_name else None
    chosen, cand, lk, own, reach, against, cl, S = P.choose(p)
    F = EV.Facts()
    placed = dict(zip(*[P.duckdb.sql(f"select t, placed_by from '{W}/map.parquet'").df()[c] for c in ("t", "placed_by")]))

    top = [int(c) for c in np.argsort(-own)[:MAP_CLUSTERS] if own[c] > 0]
    neighbours = {c: [int(x) for x in np.argsort(-S[c])[:3]] for c in top}
    pick_clusters = {int(cand.loc[t, "cluster"]) for t, _, _ in chosen}
    stretch_from = {}
    for t, kind, stretch in chosen:
        c = int(cand.loc[t, "cluster"])
        if stretch:
            stretch_from[t] = max(top, key=lambda x: S[c, x]) if top else c
    want = set(top) | {x for v in neighbours.values() for x in v} | pick_clusters | set(stretch_from.values())
    name_clusters.main(sorted(want))
    names = json.loads(name_clusters.OUT.read_text())
    cname = lambda c: names.get(str(c), {}).get("name", f"cluster {c}")
    cdesc = lambda c: names.get(str(c), {}).get("description", "")

    said = {t: v for t, v in p.evidence.items() if v[1].startswith("said")}
    fav = [f"- {F.title(t)}: {why[6:]}" + (f' ("{p.words[t]}")' if p.words.get(t) else "")
           for t, (w, why) in sorted(said.items(), key=lambda x: -x[1][0]) if t in F.ti.index]
    summary = ("This viewer's own verdicts:\n" + "\n".join(fav) +
               "\n\nTheir strongest taste clusters: " + "; ".join(f"{cname(c)} ({cdesc(c)})" for c in top[:8]))

    # Taste map, by shelf: the handful of shelves the person's titles sit on.
    shelf = np.load(W / "shelves.npy")
    snames = json.loads((W / "shelves.json").read_text())
    k = int(shelf.max()) + 1
    C1 = np.eye(k)[shelf]
    Sh = C1.T @ S @ C1
    np.fill_diagonal(Sh, 0)
    s_own = np.bincount(shelf, weights=own, minlength=k)
    s_own = s_own / s_own.max() if s_own.max() > 0 else s_own
    ev_by_cluster, ev_by_shelf = {}, {}
    for t, (w, why) in sorted(p.evidence.items(), key=lambda x: (not x[1][1].startswith("said"), -x[1][0])):
        if w >= P.TASTE_MIN and t in cl and t in F.ti.index:
            ev_by_cluster.setdefault(cl[t], []).append(t)
            ev_by_shelf.setdefault(int(shelf[cl[t]]), []).append(t)
    shelves_top = [int(x) for x in np.argsort(-s_own)[:8] if s_own[x] > 0.05]
    clusters = []
    for x in shelves_top:
        members = [c for c in np.flatnonzero(shelf == x) if own[c] > 0]
        near = cand[cand.cluster.isin(members)].sort_values("value", ascending=False).head(NEARBY).index
        clusters.append({"name": snames.get(str(x), {}).get("name", f"shelf {x}"),
                         "description": snames.get(str(x), {}).get("description", ""),
                         "strength": round(float(s_own[x]), 2),
                         "examples": [tile(F, t) for t in ev_by_shelf.get(x, [])[:EXAMPLES]],
                         "nearby": [tile(F, t) for t in near if t in F.ti.index],
                         "neighbours": [snames.get(str(y), {}).get("name", f"shelf {y}") for y in np.argsort(-Sh[x])[:3]],
                         "clusters": [cname(c) for c in sorted(members, key=lambda c: -own[c])[:5]]})
    away = [tile(F, t) for t, (w, why) in said.items() if w < 0 and t in F.ti.index]

    # Cards: evidence as data, then words.
    ts = [t for t, _, _ in chosen]
    ext = extras.fetch(ts, soup_links(ts))
    plots = content.display_plots(800)
    dislikes = [u for u, (w, _) in p.evidence.items() if w < 0 and u in F.pos]
    items, built = [], []
    for t, kind, stretch in chosen:
        c = int(cand.loc[t, "cluster"])
        rel = (f"stretch: next to their cluster '{cname(stretch_from[t])}'" if stretch else f"in their cluster '{cname(c)}'")
        worst = None
        if t in F.pos and dislikes:
            sims = [(F.val[F.pos[u]][F.idx[F.pos[u]] == F.pos[t]], u) for u in dislikes]
            sims = [(float(s[0]), u) for s, u in sims if len(s) and s[0] > 0.02]
            worst = F.title(max(sims)[1]) if sims else None
        e = EV.build(F, t, p, other, f"{cname(c)}: {cdesc(c)}", rel, lk.get(t, {}), worst, placed.get(t, "likes"))
        if not stretch:
            e["your_titles_in_this_cluster"] = [F.title(x) for x in ev_by_cluster.get(c, []) if x in said][:4]
        else:
            e["your_titles_in_the_neighbouring_cluster"] = [F.title(x) for x in ev_by_cluster.get(stretch_from[t], []) if x in said][:4]
        r = F.ti.loc[t]
        premise = ext.get(t, {}).get("premise")
        items.append({"imdb_id": r.tconst, "title": r.title, "year": int(r.start_year),
                      "kind": "series" if r.is_series else "film", "summary": plots.get(t, ""),
                      "fuller_premise": premise, "evidence": e})
        built.append((t, kind, stretch, c, e))
    text = write_text(person, summary, items)

    cards = []
    for t, kind, stretch, c, e in built:
        r = F.ti.loc[t]
        pm = F.pm.loc[t] if t in F.pm.index else None
        tx = text.get(r.tconst, {})
        trailer = next((v["url"] for v in ext.get(t, {}).get("trailers", []) if v["type"] == "Trailer"), None)
        card = {"imdb_id": r.tconst, "title": r.title, "year": int(r.start_year),
                "end_year": int(r.end_year) if r.end_year == r.end_year else None,
                "kind": "series" if r.is_series else "film",
                "seasons": e["format"].get("seasons"), "episodes": e["format"].get("episodes"),
                "hours": e["format"].get("hours"),
                "runtime_min": e["format"].get("episode_minutes") or e["format"].get("minutes"),
                "status": e.get("status"),
                "country": pm.country if pm is not None and isinstance(pm.country, str) and pm.country else None,
                "pick_kind": KIND_NAME[kind] + (" (stretch)" if stretch else ""), "cluster": cname(c),
                "what": tx.get("what") or plots.get(t, ""), "why": tx.get("why", ""), "why_not": tx.get("why_not", ""),
                "links": list(dict.fromkeys([l["title"] for l in e["links"]] or e.get("your_titles_in_this_cluster", [])[:2])),
                "imdb_rating": float(r.imdb_rating) if r.imdb_rating == r.imdb_rating else None,
                "imdb_votes": int(r.imdb_votes) if r.imdb_votes == r.imdb_votes else None,
                "rt_critics": EV.F_rt(t, "rt_critics"), "rt_audience": EV.F_rt(t, "rt_audience"),
                "poster": poster(pm.poster) if pm is not None else None,
                "art": poster(pm.art) if pm is not None else None,
                "trailer": trailer, "in_library": t in p.in_library,
                "makers": e["makers"], "cast": e["cast"], "season_ratings": e.get("episodes"),
                "closest": e["closest"], "awards": e["awards"], "nominations": e["nominations"],
                "made_for": e["made_for"], "based_on": e["based_on"],
                "for_other": e.get("other_person"), "evidence": {k: e[k] for k in
                    ("cluster", "relation", "links", "differs", "against") if k in e}}
        cards.append({k: v for k, v in card.items() if v not in (None, [], "") or k == "end_year"})

    # Have you seen this? Library titles from clusters where only the library
    # speaks for the person, one per cluster, most-voted first; then
    # well-known titles of their strongest clusters they have not mentioned.
    has_said = {cl[t] for t in said if t in cl}
    lib = [t for t in p.in_library if t not in said and t not in p.answered and t in F.ti.index and t in cl]
    lib.sort(key=lambda t: (cl[t] in has_said, -(F.ti.imdb_votes.get(t) or 0)))
    deck, used = [], set()
    for t in lib:
        if cl[t] not in used:
            used.add(cl[t])
            deck.append(t)
    for c in top:
        famous = [t for t, x in cl.items() if x == c and t not in p.known and t not in p.answered and t in F.ti.index
                  and (F.ti.imdb_votes.get(t) or 0) >= 50_000]
        deck += sorted(famous, key=lambda t: -(F.ti.imdb_votes.get(t) or 0))[:2]
    seen_deck = []
    for t in deck[:DECK]:
        o = tile(F, t)
        rm = F.pm.runtime_min.get(t) if t in F.pm.index else None
        if rm == rm and rm:
            o["runtime_min"] = int(rm)
        o["what"] = plots.get(t, "")
        o["in_library"] = t in p.in_library
        seen_deck.append(o)

    out = {"person": person, "taste_map": {"clusters": clusters, "away_from": away}, "cards": cards, "seen_deck": seen_deck}
    (PRIVATE / "cards").mkdir(exist_ok=True)
    tmp = PRIVATE / "cards" / f".{person}.json.tmp"
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    tmp.replace(PRIVATE / "cards" / f"{person}.json")
    print(f"wrote private/cards/{person}.json: {len(clusters)} clusters, {len(cards)} cards, {len(seen_deck)} questions")


if __name__ == "__main__":
    main(*sys.argv[1:3])
