"""A backlog for one person from their stated verdicts, cut into three kinds of
pick: new and good, decent and widely watched, weird niche.

Usage: python backlog.py PERSON LEVEL OUT.md
Reads private/verdicts.csv and the soup's play table at run time."""
import csv
import sqlite3
import sys

import duckdb
import numpy as np
import pandas as pd

from core import W, score
import content

ROOT = W.parent.parent.parent
PER_LANE = 10
SERIES_PER_LANE = 7
PER_SEED = 3
W_LOVED, W_LIKED = 1.0, 0.6


def load():
    d = np.load(W / "nb_full.npz")
    ti = duckdb.sql(f"""
        select t, tconst, title, start_year, end_year, is_series, kind, genres, imdb_rating, imdb_votes
        from '{W}/titles.parquet'
        where kind in ('movie','tvSeries','tvMiniSeries')""").df().set_index("t")
    return d, ti


def household(person):
    rows = [r for r in csv.DictReader(open(ROOT / "private/verdicts.csv")) if r["person"] == person]
    con = sqlite3.connect(f"file:{ROOT}/data/soup.sqlite?mode=ro", uri=True)
    played = {int(t[2:]) for (t,) in con.execute("select distinct tconst from play where tconst like 'tt%'")}
    return rows, played


def main(person, level, out):
    d, ti = load()
    items, idx, val, cnt = d["items"], d["idx"], d["val"].copy(), d["cnt"]
    val[cnt < 2] = 0  # a link one person supports is noise
    pos = {t: i for i, t in enumerate(items)}
    rows, played = household(person)
    liked = [(int(r["target"][2:]), W_LOVED if r["verdict"] == "loved" else W_LIKED)
             for r in rows if r["target"].startswith("tt") and r["verdict"] != "disliked"]
    disliked = [int(r["target"][2:]) for r in rows if r["target"].startswith("tt") and r["verdict"] == "disliked"]
    loved_makers = {r["target"]: (W_LOVED if r["verdict"] == "loved" else W_LIKED)
                    for r in rows if r["target"].startswith("nm") and r["verdict"] != "disliked"}
    seen = played | {t for t, _ in liked} | set(disliked)

    # Other people's likes.
    seeds = [(t, w) for t, w in liked if t in pos]
    cf, cf_seed = score([pos[t] for t, _ in seeds], idx, val, len(items), "max+", [w for _, w in seeds])
    dis, _ = score([pos[t] for t in disliked if t in pos], idx, val, len(items), "max") if disliked else (0, None)
    cf_t = dict(zip(items, cf))
    dis_t = dict(zip(items, dis)) if disliked else {}
    cf_why = {items[i]: seeds[cf_seed[i]][0] for i in np.flatnonzero(cf > 0)}
    cf_n = {}
    for s_i, (t, _) in enumerate(seeds):
        j = pos[t]
        for c, n in zip(idx[j], cnt[j]):
            if cf_seed[c] == s_i:
                cf_n[items[c]] = int(n)

    # Shared makers, and makers loved by name.
    mk = duckdb.sql(f"select t, nconst, w from '{W}/makers.parquet'").df()
    by_title = mk.groupby("t")
    seed_makers = {t: dict(zip(g.nconst, g.w)) for t, g in by_title if t in dict(liked)}
    maker_score, maker_why = {}, {}
    for t, g in by_title:
        best, why = 0.0, None
        for s, w_s in liked:
            shared = set(g.nconst) & set(seed_makers.get(s, {}))
            v = min(1.0, sum(seed_makers[s][m] for m in shared)) * w_s
            if v > best:
                best, why = v, (sorted(shared, key=lambda m: -seed_makers[s][m])[0], s)
        for m in set(g.nconst) & loved_makers.keys():
            if loved_makers[m] > best:
                best, why = loved_makers[m], (m, None)
        if best > 0:
            maker_score[t], maker_why[t] = best, why

    # Plain text search: plot words shared with the favourites' plots.
    text_score, text_why = content.text_scores([t for t, _ in liked], dict(liked))

    emb_score, emb_why = ({}, {})
    if level >= 2:
        emb_score, emb_why = content.embedding_scores([t for t, _ in liked], dict(liked))

    cand = ti[~ti.index.isin(seen) & (ti.imdb_votes >= 300) & (ti.imdb_rating >= 7.0)].copy()
    cand["cf"] = [cf_t.get(t, 0.0) for t in cand.index]
    cand["maker"] = [0.2 * maker_score.get(t, 0.0) for t in cand.index]
    cand["text"] = [0.1 * text_score.get(t, 0.0) for t in cand.index]
    cand["emb"] = [0.1 * emb_score.get(t, 0.0) for t in cand.index]
    cand["score"] = cand[["cf", "maker", "text", "emb"]].max(axis=1) - [dis_t.get(t, 0.0) for t in cand.index]
    cand["why"] = cand[["cf", "maker", "text", "emb"]].idxmax(axis=1)

    names = dict(duckdb.sql(f"select nconst, name from '{W}/people.parquet' where nconst in "
                            f"(select distinct nconst from '{W}/makers.parquet')").fetchall())
    title = ti.title.to_dict()

    def reason(t, kind):
        if kind == "cf":
            s = cf_why[t]
            return f"{cf_n.get(t, '?')} people who loved {title[s]} also loved this"
        if kind == "maker":
            m, s = maker_why[t]
            return f"by {names.get(m, m)}" + (f", who made {title[s]}" if s else ", whose work you loved")
        if kind == "text":
            return f"plot reads like {title[text_why[t]]}"
        return f"plot embedding close to {title[emb_why[t]]}"

    def seed_of(t, kind):
        return {"cf": cf_why.get(t), "maker": (maker_why.get(t) or (None, None))[1],
                "text": text_why.get(t), "emb": emb_why.get(t)}[kind]

    new = (cand.start_year >= 2024) | ((cand.is_series == 1) & (cand.start_year >= 2021) & (cand.end_year.isna() | (cand.end_year >= 2025)))
    lanes = {
        "New and good": cand[new & (cand.imdb_votes >= 1000) & (cand.imdb_rating >= 7.3)],
        "Decent and widely watched": cand[~new & (cand.imdb_votes >= 40000) & (cand.imdb_rating >= 7.5)],
        "Weird niche": cand[~new & (cand.imdb_votes < 25000) & (cand.imdb_rating >= 7.2)],
    }
    plots = content.display_plots()
    rt = duckdb.sql(f"select t, scorer, score from '{W}/plex_scores.parquet' where scorer like 'rt%'").df()
    rt = {(t, s): v for t, s, v in rt.itertuples(index=False)}

    lines = [f"# Backlog for {person}, level {level}", ""]
    for lane, df in lanes.items():
        df = df[df.score > 0].sort_values("score", ascending=False)
        picks, per_seed = [], {}
        for want_series, limit in ((1, SERIES_PER_LANE), (0, PER_LANE - SERIES_PER_LANE)):
            n = 0
            for t, r in df[df.is_series == want_series].iterrows():
                s = seed_of(t, r.why)
                if per_seed.get(s, 0) >= PER_SEED:
                    continue
                per_seed[s] = per_seed.get(s, 0) + 1
                picks.append((t, r))
                n += 1
                if n == limit:
                    break
        lines += [f"## {lane}", ""]
        for t, r in picks:
            sc = f"IMDb {r.imdb_rating:.1f} ({int(r.imdb_votes):,} votes)"
            if (t, "rt_critics") in rt:
                sc += f", RT critics {rt[(t, 'rt_critics')]*10:.0f}%"
            if (t, "rt_audience") in rt:
                sc += f", RT audience {rt[(t, 'rt_audience')]*10:.0f}%"
            years = f"{int(r.start_year)}" + (f"–{int(r.end_year)}" if r.is_series and not pd.isna(r.end_year) and r.end_year != r.start_year else "–" if r.is_series else "")
            kind = "series" if r.is_series else "film"
            lines.append(f"- **{r.title}** ({years}, {kind}). {plots.get(t, '(no plot text)')} {sc}. Why: {reason(t, r.why)}.")
        lines.append("")
    open(out, "w").write("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
