"""A backlog for one person from their stated verdicts, cut into three kinds of
pick: new and good, decent and widely watched, weird niche.

Each kind is ranked by fusing the ranks of the evidence a level has:
level 1: other people's likes, scored by how much more often fans of a
favourite liked a title than its popularity predicts; for titles nobody has
rated, shared makers. Level 2 adds, for unrated titles, plot embeddings close
to a favourite; level 3 lets a frontier model reorder the top. Every reason names one of the person's favourites.

Usage: python backlog.py PERSON LEVEL OUT.md
Reads private/ (verdicts, titles seen elsewhere, watch list) and the soup's
play table at run time."""
import csv
import re
import sqlite3
import subprocess
import sys
import unicodedata

import duckdb
import numpy as np
import pandas as pd

import content
from core import SHRINK, W, score

ROOT = W.parent.parent.parent
PRIVATE = ROOT / "private"
PER_LANE, SERIES_PER_LANE, PER_SEED = 10, 7, 3
W_LOVED, W_LIKED = 1.0, 0.6
POP_EXP = 1.0      # candidate popularity exponent in the likes score; 0.5 is plain cosine
OBVIOUS = 0.15     # a title liked by more than this share of a favourite's fans (of 200 or more) is one they have likely seen
MIN_MAKER = 0.1    # weakest maker link that counts
RATED = 20         # likers a title needs before other people's likes alone rank it
DISLIKE_LABELS = ("slop",)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def resolve(ti, title, year=None, kind=None):
    """IMDb title for a name and year: the most-voted exact title match."""
    c = ti[ti.key == norm(title)]
    if kind:
        c = c[c.is_series == (kind == "series")]
    if year and len(c):
        c = c[(c.start_year - int(year)).abs() <= 1]
    return None if c.empty else c.imdb_votes.idxmax()


def household(person, ti):
    rows = [r for r in csv.DictReader(open(PRIVATE / "verdicts.csv")) if r["person"] == person]
    con = sqlite3.connect(f"file:{ROOT}/data/soup.sqlite?mode=ro", uri=True)
    played = {int(t[2:]) for (t,) in con.execute("select distinct tconst from play where tconst like 'tt%'")}
    seen, watch, unresolved = set(), {}, []
    for r in csv.DictReader(open(PRIVATE / "seen_elsewhere.csv")):
        t = resolve(ti, r["title"], r["year"], r["kind"]) or (resolve(ti, r["note"], r["year"], r["kind"]) if r["note"] else None)
        (seen.add(t) if t else unresolved.append(r["title"]))
    for r in csv.DictReader(open(PRIVATE / "watchlist.csv")):
        t = resolve(ti, r["title"], None, r["kind"])
        if t:
            watch[t] = r["note"]
        else:
            unresolved.append(r["title"])
    return rows, played, seen, watch, unresolved


def evidence(person, level, holdout=()):
    """holdout: titles treated as unseen and unrated, to check whether they are found."""
    d = np.load(W / "nb_full.npz")
    items, idx, cnt, n = d["items"], d["idx"], d["cnt"], d["n"]
    pos = {t: i for i, t in enumerate(items)}
    ti = duckdb.sql(f"""select t, title, start_year, end_year, is_series, imdb_rating, imdb_votes
        from '{W}/titles.parquet' where kind in ('movie','tvSeries','tvMiniSeries')""").df().set_index("t")
    ti["key"] = [norm(x) for x in ti.title]
    rows, played, seen_elsewhere, watch, unresolved = household(person, ti)
    liked = {int(r["target"][2:]): (W_LOVED if r["verdict"] == "loved" else W_LIKED)
             for r in rows if r["target"].startswith("tt") and r["verdict"] != "disliked"}
    disliked = {int(r["target"][2:]) for r in rows if r["target"].startswith("tt") and r["verdict"] == "disliked"}
    disliked |= {t for t, note in watch.items() if any(x in note for x in DISLIKE_LABELS)}
    loved_makers = {r["target"]: (W_LOVED if r["verdict"] == "loved" else W_LIKED)
                    for r in rows if r["target"].startswith("nm") and r["verdict"] != "disliked"}
    for t in holdout:
        liked.pop(t, None)
    seen = (played | seen_elsewhere | set(liked) | disliked) - set(holdout)
    cand = ti[~ti.index.isin(seen) & (ti.imdb_votes >= 300) & (ti.imdb_rating >= 7.0)].copy()
    ev, why = {}, {}

    # Other people's likes: for each favourite, how much more often its fans
    # liked a title than that title's popularity predicts; summed over favourites.
    val = cnt / (np.sqrt(n)[:, None] * n[idx] ** POP_EXP) * (cnt / (cnt + SHRINK))
    val[cnt < 2] = 0
    seeds = [t for t in liked if t in pos]
    cf, cf_seed = score([pos[t] for t in seeds], idx, val, len(items), "sum", [liked[t] for t in seeds])
    dis, _ = score([pos[t] for t in disliked if t in pos], idx, val, len(items), "max")
    cf_n = {}
    for s_i, t in enumerate(seeds):
        for c, k in zip(idx[pos[t]], cnt[pos[t]]):
            if cf_seed[c] == s_i:
                cf_n[items[c]] = int(k)
    obvious = set()
    for t in seeds:
        j = pos[t]
        if n[j] >= 200:
            obvious |= set(items[idx[j][cnt[j] > OBVIOUS * n[j]]])
    hit = np.flatnonzero(cf > 0)
    ev["likes"] = dict(zip(items[hit], cf[hit]))
    why["likes"] = {items[i]: (seeds[cf_seed[i]], f"{cf_n.get(items[i], 'several')} people who rated "
                               f"{ti.title.get(seeds[cf_seed[i]])} highly also rated this highly")
                    for i in hit}
    too_close_to_dislike = set(items[np.flatnonzero(dis > cf)])

    # Shared makers, weighted by how much of each title they made and how
    # few other titles they made; makers rated by name count directly.
    mk = duckdb.sql(f"select t, nconst, share, w from '{W}/makers.parquet'").df()
    names = dict(duckdb.sql(f"select nconst, name from '{W}/people.parquet' where nconst in (select nconst from mk)").fetchall())
    fav_mk = mk[mk.t.isin(liked.keys())]
    j = mk[mk.t.isin(cand.index)].merge(fav_mk, on="nconst", suffixes=("", "_fav"))
    j = j[j.t != j.t_fav]
    j["link"] = j.w * j.w_fav * j.t_fav.map(liked)
    ev["makers"], why["makers"] = {}, {}
    for t, g in j.groupby("t"):
        per_fav = g.groupby("t_fav").link.sum()
        best_fav = per_fav.idxmax()
        if per_fav.max() >= MIN_MAKER:
            m = g[g.t_fav == best_fav].sort_values("link").iloc[-1]
            film_fav, film = not ti.is_series.get(best_fav), not ti.is_series.get(t)
            verb = "made" if film_fav else "created" if m.share_fav >= 1 else "co-wrote or directed"
            by = "made" if film or m.share < 1 else "created"
            ev["makers"][t] = per_fav.max()
            why["makers"][t] = (best_fav, f"{by} by {names.get(m.nconst)}, who {verb} {ti.title.get(best_fav)}")
    for t, g in mk[mk.t.isin(cand.index) & mk.nconst.isin(loved_makers.keys())].groupby("t"):
        m = g.sort_values("share").iloc[-1]
        v = m.share * loved_makers[m.nconst]
        if v >= ev["makers"].get(t, 0) and m.share >= 0.5:
            ev["makers"][t] = v
            why["makers"][t] = (m.nconst, f"made by {names.get(m.nconst)}, whose work you rated")

    # Level 2: plot embedding closest to a favourite.
    if level >= 2:
        emb = content.Embeddings()
        fav = [t for t in liked if t in emb.pos]
        S = emb.sims(fav) * np.array([liked[t] for t in fav])[None, :]
        ev["plot"], why["plot"] = {}, {}
        for t in cand.index:
            if t in emb.pos:
                row = S[emb.pos[t]]
                b = row.argmax()
                ev["plot"][t] = row[b]
                why["plot"][t] = (fav[b], f"its plot is close to {ti.title.get(fav[b])}")

    likers = dict(zip(items, n))
    cand["likers"] = [likers.get(t, 0) for t in cand.index]
    for k, v in ev.items():
        cand[k] = [v.get(t, 0.0) for t in cand.index]
    cand = cand[~cand.index.isin(too_close_to_dislike | obvious)]
    return cand, list(ev), why, rows, watch, unresolved


def fuse(df, kinds):
    """Titles other people have rated (RATED or more likers) are ranked by their likes alone, which
    beat every mix with makers or plot text in the tests on strangers. Titles
    with no likes evidence are ranked by makers (and plot, at level 2), fused
    by reciprocal rank. The two lists are interleaved rank for rank."""
    def rank(v):
        r = pd.Series(-v).rank(method="min").to_numpy(copy=True)
        r[v <= 0] = np.inf
        return r

    likes = df["likes"].values
    rated = df["likers"].values >= RATED
    total = np.where(rated, 1 / (60 + rank(likes)), 0.0)
    best = np.where(rated, "likes", "").astype(object)
    rest = [k for k in kinds if k != "likes"]
    content = np.zeros(len(df))
    best_r = np.full(len(df), np.inf)
    for k in rest:
        v = np.where(rated, 0, df[k].values)
        r = rank(v)
        content += np.where(np.isfinite(r), 1 / (60 + r), 0)
        better = r < best_r
        best[better & ~rated], best_r[better & ~rated] = k, r[better & ~rated]
    total = np.where(rated, total, 1 / (60 + rank(content)) * (content > 0))
    return total, best


def judge(person_rows, df, n):
    """Level 3: the frontier model reorders the top n of one kind of pick."""
    plots = content.display_plots(300)
    words = "\n".join(f"- {r['title']}: {r['verdict']} (\"{r['words']}\")" for r in person_rows)
    cands = list(df.index[:n])
    lines = [f"[{i}] {df.title[t]} ({df.start_year[t]}, {'series' if df.is_series[t] else 'film'}): "
             f"{plots.get(t, '(no plot text)')}" for i, t in enumerate(cands)]
    prompt = ("This viewer's own verdicts on titles, with their words:\n" + words +
              "\n\nThey want discovery: high-quality, stimulating, varied things to watch that they have probably "
              "not seen, not mainstream slop. "
              f"Rank all {len(cands)} candidates below from best to worst pick for this viewer. "
              "Reply with only the candidate numbers in order, comma-separated.\n\n" + "\n".join(lines))
    out = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config", "--safe-mode",
                          "--setting-sources", "", "--system-prompt", "You are a film and television expert.",
                          "--no-session-persistence"], input=prompt, capture_output=True, text=True,
                         timeout=900, cwd="/tmp").stdout
    order = []
    for x in re.findall(r"\d+", out):
        if int(x) < len(cands) and int(x) not in order:
            order.append(int(x))
    order += [i for i in range(len(cands)) if i not in order]
    return df.loc[[cands[i] for i in order] + list(df.index[n:])]


def lanes_of(cand):
    new = (cand.start_year >= 2024) | ((cand.is_series == 1) & (cand.start_year >= 2021) &
                                       (cand.end_year.isna() | (cand.end_year >= 2025)))
    return {
        "New and good": cand[new & (cand.imdb_votes >= 1000) & (cand.imdb_rating >= 7.3)],
        "Decent and widely watched": cand[~new & (cand.imdb_votes >= 40000) & (cand.imdb_rating >= 7.5)],
        "Weird niche": cand[~new & (cand.imdb_votes < 25000) & (cand.imdb_rating >= 7.2)],
    }


def main(person, level, out):
    cand, kinds, why, rows, watch, unresolved = evidence(person, level)
    plots = content.display_plots()
    rt = {(t, s): v for t, s, v in duckdb.sql(
        f"select t, scorer, score from '{W}/plex_scores.parquet' where scorer like 'rt%'").fetchall()}
    lines = [f"# Backlog for {person}, level {level}", ""]
    found = []
    for lane, df in lanes_of(cand).items():
        df = df.copy()
        df["score"], df["why"] = fuse(df, kinds)
        df = df[df.score > 0].sort_values("score", ascending=False)
        for t in watch:
            if t in df.index:
                part = df[df.is_series == df.is_series[t]]
                found.append(f"{df.title[t]}: {lane}, rank {list(part.index).index(t) + 1} of {len(part)}")
        df = df[~df.index.isin(watch)]
        picks, per_seed = [], {}
        for want_series, limit in ((1, SERIES_PER_LANE), (0, PER_LANE - SERIES_PER_LANE)):
            part = df[df.is_series == want_series]
            if level >= 3:
                part = judge(rows, part, 3 * limit)
            k = 0
            for t, r in part.iterrows():
                seed, text = why[r.why][t]
                if per_seed.get(seed, 0) >= PER_SEED:
                    continue
                per_seed[seed] = per_seed.get(seed, 0) + 1
                picks.append((t, r, text))
                k += 1
                if k == limit:
                    break
        lines += [f"## {lane}", ""]
        for t, r, text in picks:
            sc = f"IMDb {r.imdb_rating:.1f} ({int(r.imdb_votes):,} votes)"
            if (t, "rt_critics") in rt:
                sc += f", RT critics {rt[(t, 'rt_critics')] * 10:.0f}%"
            if (t, "rt_audience") in rt:
                sc += f", RT audience {rt[(t, 'rt_audience')] * 10:.0f}%"
            ended = r.is_series and not pd.isna(r.end_year) and r.end_year != r.start_year
            years = f"{int(r.start_year)}" + (f"–{int(r.end_year)}" if ended else "–" if r.is_series and pd.isna(r.end_year) else "")
            kind = "series" if r.is_series else "film"
            lines.append(f"- **{r.title}** ({years}, {kind}). {plots.get(t, '(no plot text)')} {sc}. Why: {text}.")
        lines.append("")
    lines += ["## Check: watch-list titles the ranker reached unprompted (excluded above)", ""]
    lines += [f"- {x}" for x in found] or ["- none"]
    lines += ["", f"Watch-list titles in no lane: {len(watch) - len(found)} of {len(watch)}.",
              f"Titles in private lists that did not resolve to an IMDb ID: {', '.join(unresolved) or 'none'}.", ""]
    open(out, "w").write("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
