"""The facts and evidence behind one card, as data, so whoever writes the
words (a model or a template) works from the same things:

- format and status: seasons, episodes, total hours, ended or running;
- makers and cast, each with what the person knows them from (their own
  titles first, then Plex, then the maker's best-known work);
- every episode's IMDb rating by season;
- closest titles by shared audience, marked when the person likes one, has it
  on Plex, or when the other person asked for it;
- awards and nominations (Wikidata);
- links to the person's titles: shared audience (how many fans of theirs also
  loved it), shared makers, the cluster it sits in;
- stretch: how it differs from what they already like (country, decade, kind);
- against: what counts against it (later seasons rate lower, critics and
  audience disagree, few votes, sits near something they disliked, placed on
  the map by makers and plot alone);
- the other person: whether their titles point to it."""
import duckdb
import numpy as np

from core import W


class Facts:
    def __init__(self):
        self.ti = duckdb.sql(f"""select t, tconst, title, start_year, end_year, is_series, null::int as runtime_min, imdb_rating,
               imdb_votes, n_episodes, genres from '{W}/titles.parquet'""").df().set_index("t")
        num = ["start_year", "end_year", "is_series", "runtime_min", "imdb_rating", "imdb_votes", "n_episodes"]
        self.ti[num] = self.ti[num].astype(float)
        self.pm = duckdb.sql(f"select * from '{W}/plex_meta.parquet'").df().drop_duplicates("t").set_index("t")
        self.pm[["seasons", "runtime_min"]] = self.pm[["seasons", "runtime_min"]].astype(float)
        self.ep = duckdb.sql(f"select * from '{W}/episodes.parquet'").df()
        self.facts = duckdb.sql(f"select * from '{W}/facts.parquet'").df()
        self.people = dict(duckdb.sql(f"select nconst, name from '{W}/people.parquet'").fetchall())
        cr = duckdb.sql(f"""select t, nconst, role, billing, episodes from '{W}/credits.parquet'
            where role in ('actor','creator','director','writer')""").df()
        self.cast = cr[(cr.role == "actor") & cr.billing.notna() & (cr.billing <= 5)]
        self.mk = duckdb.sql(f"select t, nconst, share from '{W}/makers.parquet'").df()
        self.by_person = cr[cr.nconst.isin(set(self.cast.nconst) | set(self.mk.nconst))].groupby("nconst").t.apply(list)
        d = np.load(W / "nb_full.npz")
        self.items, self.idx, self.val, self.cnt, self.n = d["items"], d["idx"], d["val"], d["cnt"], d["n"]
        self.pos = {t: i for i, t in enumerate(self.items)}

    def title(self, t):
        return self.ti.title.get(t, str(t))

    def ref(self, t):
        r = self.ti.loc[t]
        return {"imdb_id": r.tconst, "title": r.title, "year": int(r.start_year) if r.start_year == r.start_year else None,
                "kind": "series" if r.is_series else "film"}


def known_from(F, nconst, person, exclude):
    """Up to three titles this person knows the maker or actor from."""
    ts = [t for t in F.by_person.get(nconst, []) if t != exclude and t in F.ti.index]
    mine = [t for t in ts if person.evidence.get(t, (0, ""))[0] > 0 and person.evidence[t][1].startswith("said")]
    plex = [t for t in ts if t in person.in_library and t not in mine]
    rest = sorted((t for t in ts if t not in mine and t not in plex), key=lambda t: -(F.ti.imdb_votes.get(t) or 0))
    out = [{"title": F.title(t), "yours": "liked" if t in mine else "on your Plex" if t in plex else None}
           for t in (mine + plex + rest)[:3]]
    return [{k: v for k, v in o.items() if v} for o in out]


def build(F, t, person, other, cluster_name, relation, link, against_sim, placed_by):
    r = F.ti.loc[t]
    pm = F.pm.loc[t] if t in F.pm.index else None
    e = {}
    # Format and status.
    if r.is_series:
        eps = F.ep[F.ep.t == t]
        n_eps = int(r.n_episodes) if r.n_episodes == r.n_episodes else len(eps)
        mins = int(pm.runtime_min) if pm is not None and pm.runtime_min == pm.runtime_min else (
            int(r.runtime_min) if r.runtime_min == r.runtime_min else None)
        seasons = int(pm.seasons) if pm is not None and pm.seasons == pm.seasons else (
            int(eps.season.max()) if len(eps) else None)
        e["format"] = {"seasons": seasons, "episodes": n_eps, "episode_minutes": mins,
                       "hours": round(n_eps * mins / 60) if mins and n_eps else None}
        last = pm.last_aired if pm is not None else None
        e["status"] = ("ended " + str(int(r.end_year))) if r.end_year == r.end_year else "running"
        if isinstance(last, str):
            e["status"] += f", last episode {last}"
        e["episodes"] = [{"season": int(s), "ratings": [round(float(x), 1) for x in g.sort_values("episode").rating],
                          "average": round(float(g.rating.mean()), 2)}
                         for s, g in eps[eps.season.notna() & (eps.season > 0)].groupby("season")]
    else:
        mins = int(pm.runtime_min) if pm is not None and pm.runtime_min == pm.runtime_min else (
            int(r.runtime_min) if r.runtime_min == r.runtime_min else None)
        e["format"] = {"minutes": mins}
    f = F.facts[F.facts.t == t]
    e["based_on"] = list(f[f.fact == "based_on"].value)[:2]
    e["made_for"] = list(f[f.fact == "broadcaster"].value)[:2] or ([pm.network] if pm is not None and isinstance(pm.network, str) and pm.network else [])
    e["awards"] = list(f[f.fact == "award"].value)[:6]
    e["nominations"] = int((f.fact == "nomination").sum())

    # People.
    mk = F.mk[(F.mk.t == t) & (F.mk.share >= 0.5)].sort_values("share", ascending=False).head(3)
    e["makers"] = [{"name": F.people.get(m.nconst, m.nconst), "role": "creator" if m.share >= 1 and r.is_series else
                    ("director" if not r.is_series else "writer or director"),
                    "known_from": known_from(F, m.nconst, person, t)} for m in mk.itertuples()]
    cast = F.cast[F.cast.t == t].sort_values("billing").head(4)
    e["cast"] = [{"name": F.people.get(c.nconst, c.nconst), "known_from": known_from(F, c.nconst, person, t)}
                 for c in cast.itertuples()]

    # Closest by shared audience.
    close = []
    if t in F.pos:
        j = F.pos[t]
        order = np.argsort(-F.val[j])
        for k in order[:40]:
            u = F.items[F.idx[j][k]]
            if u not in F.ti.index or F.cnt[j][k] < 3:
                continue
            flag = ("you like it" if person.evidence.get(u, (0, ""))[0] > 0 and person.evidence[u][1].startswith("said")
                    else "on your Plex" if u in person.in_library
                    else f"{other.name.capitalize()} asked for it" if other and other.evidence.get(u, (0, ""))[0] > 0
                    and other.evidence[u][1].startswith("said") else None)
            close.append({**F.ref(u), "flag": flag, "closeness": round(float(F.val[j][k]), 3)} if flag else
                         {**F.ref(u), "closeness": round(float(F.val[j][k]), 3)})
            if len(close) == 8:
                break
    e["closest"] = close

    # Links to the person's titles.
    e["cluster"] = cluster_name
    e["relation"] = relation
    links = []
    if "likes_from" in link:
        s = link["likes_from"]
        c = n = None
        if t in F.pos and s in F.pos:
            js = F.pos[s]
            hit = np.flatnonzero(F.idx[js] == F.pos[t])
            if len(hit):
                c, n = int(F.cnt[js][hit[0]]), int(F.n[js])
        links.append({**F.ref(s), "how": "shared audience", "fans_who_also_loved_it": c, "fans": n})
    if "maker_from" in link:
        links.append({**F.ref(link["maker_from"]), "how": "shared maker",
                      "maker": F.people.get(link.get("maker_who"), link.get("maker_who"))})
    e["links"] = links

    # How it differs from what they already like.
    mine = [u for u, (w, why) in person.evidence.items() if w > 0 and why.startswith("said") and u in F.ti.index]
    countries = {c for u in mine for c in (F.pm.country.get(u) or "").split(", ") if c}
    tc = [c for c in ((pm.country if pm is not None and isinstance(pm.country, str) else "") or "").split(", ") if c]
    decades = {int(F.ti.start_year[u]) // 10 * 10 for u in mine if F.ti.start_year[u] == F.ti.start_year[u]}
    diff = []
    if tc and not set(tc) & countries:
        diff.append(f"from {tc[0]}, a country none of their own titles come from")
    if r.start_year == r.start_year and int(r.start_year) // 10 * 10 not in decades:
        diff.append(f"from the {int(r.start_year) // 10 * 10}s, a decade none of their own titles come from")
    if not r.is_series and sum(not F.ti.is_series[u] for u in mine) < 0.3 * len(mine):
        diff.append("a film, where most of what they like is series")
    e["differs"] = diff

    # What counts against it.
    against = []
    seasons = e.get("episodes", [])
    if len(seasons) >= 2 and seasons[-1]["average"] < seasons[0]["average"] - 0.3:
        against.append(f"later seasons rate lower: season {seasons[-1]['season']} averages {seasons[-1]['average']} "
                       f"against {seasons[0]['average']} for season {seasons[0]['season']}")
    rc, ra = (F_rt(t, "rt_critics"), F_rt(t, "rt_audience"))
    if rc is not None and ra is not None and abs(rc - ra) >= 15:
        against.append(f"critics and audiences disagree: {rc}% against {ra}% on Rotten Tomatoes")
    if (r.imdb_votes or 0) < 2000:
        against.append(f"few people have rated it ({int(r.imdb_votes):,} IMDb votes), so the evidence is thin")
    if against_sim:
        against.append(f"its audience overlaps with {against_sim}, which they disliked")
    if placed_by != "likes":
        against.append("too few ratings to place it by audience; it sits on the map by its makers and plot")
    if r.is_series and e.get("format", {}).get("seasons") == 1 and r.end_year == r.end_year and r.end_year <= 2025 \
            and r.start_year >= 2015:
        against.append("one season only")
    e["against"] = against

    # The other person.
    if other:
        theirs = [(u, w) for u, (w, why) in other.evidence.items() if w > 0 and why.startswith("said") and u in F.pos]
        hits = []
        if t in F.pos:
            for u, w in theirs:
                ju = F.pos[u]
                h = np.flatnonzero(F.idx[ju] == F.pos[t])
                if len(h) and F.cnt[ju][h[0]] >= 2:
                    hits.append((F.val[ju][h[0]] * w, u))
        hits.sort(reverse=True)
        e["other_person"] = {"name": other.name, "linked_titles": [F.title(u) for _, u in hits[:3]],
                             "evidence_titles": len([1 for _, (w, why) in other.evidence.items() if why.startswith("said")])}
    return e


_RT = None


def F_rt(t, scorer):
    global _RT
    if _RT is None:
        rt = duckdb.sql(f"select t, scorer, score from '{W}/plex_scores.parquet' where scorer like 'rt%'").fetchall()
        _RT = {(a, b): round(c * 10) for a, b, c in rt}
    return _RT.get((t, scorer))
