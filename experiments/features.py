"""Per-title features for a personal ranker (ranker_test.py), from the soup.

Two kinds:
- what the title is, the same for everyone: IMDb rating and votes, critics'
  score and the gap to the audience score, how episode ratings move (first
  episode against the rest, last season against the first, the finale against
  the average), network, country, series or film, length, decade;
- how it links to each labelled title, kept as matrices so a label can be
  hidden without recomputing: shared makers, shared repeat cast, shared TV
  Tropes and MovieLens tags, and crowd links from EASE (Steck 2019) fitted
  within one rating source at a time on its most-liked titles.

Candidates are every series with 1,000 or more IMDb votes, every film with
5,000 or more, and every labelled title.

Usage: python features.py PERSON   writes data/work/exp/features-<person>.npz"""
import sys

import duckdb
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer

import household
import labels as LB
from core import W

EASE_ITEMS, EASE_LAMBDA = 6000, 200.0
SOURCES = ("amazon", "netflix", "trakt", "movielens", "letterboxd")


def candidates(lab):
    ti = duckdb.sql(f"""select t, title, start_year, end_year, is_series, imdb_rating, imdb_votes, n_episodes
        from '{W}/titles.parquet' where kind in ('movie','tvSeries','tvMiniSeries')""").df().set_index("t")
    num = ["start_year", "end_year", "is_series", "imdb_rating", "imdb_votes", "n_episodes"]
    ti[num] = ti[num].astype(float)
    keep = ((ti.is_series == 1) & (ti.imdb_votes >= 1000)) | ((ti.is_series == 0) & (ti.imdb_votes >= 5000))
    keep |= ti.index.isin(lab)
    return ti[keep].copy()


def intrinsic(c):
    pm = duckdb.sql(f"select t, network, country, runtime_min from '{W}/plex_meta.parquet'").df().drop_duplicates("t").set_index("t")
    rt = duckdb.sql(f"select t, scorer, score from '{W}/plex_scores.parquet' where scorer like 'rt%'").df()
    rt = rt.pivot_table(index="t", columns="scorer", values="score")
    ep = duckdb.sql(f"select * from '{W}/episodes.parquet' where season > 0 and rating is not null").df()
    ep = ep[ep.t.isin(c.index)].sort_values(["t", "season", "episode"])
    g = ep.groupby("t")
    first = g.rating.first()
    rest = g.rating.apply(lambda x: x.iloc[1:].mean() if len(x) > 1 else np.nan)
    by_season = ep.groupby(["t", "season"]).rating.mean().reset_index()
    sg = by_season.groupby("t").rating
    f = pd.DataFrame(index=c.index)
    f["imdb_rating"] = c.imdb_rating.fillna(c.imdb_rating.median())
    f["log_votes"] = np.log1p(c.imdb_votes.fillna(0))
    crit = rt.rt_critics.reindex(c.index) * 10
    aud = rt.rt_audience.reindex(c.index) * 10
    f["critics"] = crit.fillna(crit.median())
    f["critics_minus_audience"] = (crit - aud).fillna(0)
    f["has_critics"] = crit.notna().astype(float)
    f["pilot_vs_rest"] = (rest - first).reindex(c.index).fillna(0)
    f["last_vs_first_season"] = (sg.last() - sg.first()).reindex(c.index).fillna(0)
    f["finale_vs_mean"] = (g.rating.last() - g.rating.mean()).reindex(c.index).fillna(0)
    f["is_series"] = c.is_series.fillna(0)
    f["log_episodes"] = np.log1p(c.n_episodes.fillna(1))
    f["log_runtime"] = np.log1p(pm.runtime_min.reindex(c.index).astype(float).fillna(45))
    f["decade"] = ((c.start_year.fillna(2000) - 2000) / 10)
    country = pm.country.reindex(c.index).fillna("")
    f["uk_or_ireland"] = country.str.contains("United Kingdom|Ireland").astype(float)
    f["us"] = country.str.contains("United States").astype(float)
    nets = pm.network.reindex(c.index).fillna("").str.split(",").str[0].str.strip()
    return f, nets


def link_matrix(rows, cols, df, key, weight=None):
    """rows x cols: summed weights of shared values of `key` (makers or cast)."""
    df = df[df.t.isin(set(rows) | set(cols))]
    codes = {v: i for i, v in enumerate(df[key].unique())}
    w = df[weight].values if weight else np.ones(len(df))

    def inc(ts):
        p = {t: i for i, t in enumerate(ts)}
        s = df[df.t.isin(p)]
        ws = s[weight].values if weight else np.ones(len(s))
        return sp.csr_matrix((ws, ([p[t] for t in s.t], [codes[v] for v in s[key]])), shape=(len(ts), len(codes)))
    M = (inc(rows) @ inc(cols).T).toarray().astype(np.float32)
    for i, t in enumerate(rows):
        if t in set(cols):
            M[i, list(cols).index(t)] = 0
    return M


def cast_table():
    cr = duckdb.sql(f"""select t, nconst, billing, episodes from '{W}/credits.parquet'
        where role = 'actor' and (billing <= 6 or episodes >= 3)""").df()
    n = cr.groupby("nconst").t.nunique()
    cr["w"] = (1 / np.log2(1 + n.reindex(cr.nconst).values)).astype(np.float32)
    return cr


def trope_matrix(rows, cols):
    tr = duckdb.sql(f"select t, replace(trope, ' ', '_') tok from '{W}/tropes.parquet'").df()
    tg = duckdb.sql(f"select t, replace(tag, ' ', '_') tok from '{W}/tags.parquet' where n >= 2").df()
    docs = pd.concat([tr, tg]).groupby("t").tok.apply(" ".join)
    ts = list(dict.fromkeys(list(rows) + list(cols)))
    have = [t for t in ts if t in docs.index]
    X = TfidfVectorizer(min_df=2, sublinear_tf=True, token_pattern=r"\S+", dtype=np.float32).fit_transform(docs.loc[have])
    pos = {t: i for i, t in enumerate(have)}
    R = np.zeros((len(rows), len(cols)), np.float32)
    ri = [i for i, t in enumerate(rows) if t in pos]
    ci = [j for j, t in enumerate(cols) if t in pos]
    if ri and ci:
        block = (X[[pos[rows[i]] for i in ri]] @ X[[pos[cols[j]] for j in ci]].T).toarray()
        R[np.ix_(ri, ci)] = block
    for i, t in enumerate(rows):
        if t in pos and t in set(cols):
            R[i, list(cols).index(t)] = 0
    return R, np.array([t in pos for t in cols])


def ease_matrix(rows, cols):
    """rows x cols: the EASE weight from each labelled title to each candidate,
    summed over rating sources, each source fitted on its own most-liked titles."""
    con = duckdb.connect(config={"memory_limit": "4GB", "threads": 4})
    out = np.zeros((len(rows), len(cols)), np.float32)
    cpos = {t: j for j, t in enumerate(cols)}
    want = set(rows) | set(cols)
    for src in SOURCES:
        likes = con.execute(f"""
            with m as (select u, t, r, avg(r) over (partition by u) um from '{W}/ratings.parquet' where source = '{src}')
            select u, t from m where r >= 0.75 and r >= um""").fetchnumpy()
        u, t = likes["u"], likes["t"]
        items, counts = np.unique(t, return_counts=True)
        order = np.argsort(-counts)
        top = set(items[order[:EASE_ITEMS]])
        extra = [x for x, n in zip(items, counts) if x in want and n >= 3 and x not in top]
        keep = np.array(sorted(top | set(extra)))[: EASE_ITEMS + 1000]
        ipos = {x: i for i, x in enumerate(keep)}
        m = np.isin(t, keep)
        uu, ui = np.unique(u[m], return_inverse=True)
        X = sp.csr_matrix((np.ones(m.sum(), np.float32), (ui, [ipos[x] for x in t[m]])), shape=(len(uu), len(keep)))
        G = (X.T @ X).toarray().astype(np.float32)
        G[np.diag_indices_from(G)] += EASE_LAMBDA
        P = np.linalg.inv(G)
        B = -P / np.diag(P)[None, :]
        np.fill_diagonal(B, 0)
        r_in = [(i, ipos[x]) for i, x in enumerate(rows) if x in ipos]
        c_in = [(j, ipos[x]) for j, x in enumerate(cols) if x in ipos]
        if r_in and c_in:
            Bl = B[np.ix_([a for _, a in r_in], [b for _, b in c_in])]
            Bl = Bl / (np.abs(Bl).std() or 1)
            out[np.ix_([i for i, _ in r_in], [j for j, _ in c_in])] += Bl
        print(src, "titles", len(keep), "labelled in it", len(r_in), flush=True)
        del G, P, B, X
    return out


def main(person):
    p = household.load(person)
    lab = LB.labels(p)
    c = candidates(lab.index)
    rows, cols = list(lab.index), list(c.index)
    f, nets = intrinsic(c)
    mk = duckdb.sql(f"select t, nconst, w from '{W}/makers.parquet'").df()
    links = {"makers": link_matrix(rows, cols, mk, "nconst", "w"),
             "cast": link_matrix(rows, cols, cast_table(), "nconst", "w")}
    links["tropes"], has_tropes = trope_matrix(rows, cols)
    links["crowd"] = ease_matrix(rows, cols)
    f["has_tropes"] = has_tropes.astype(float)
    np.savez(W / f"features-{person}.npz", rows=np.array(rows), cols=np.array(cols), names=np.array(f.columns),
             F=f.values.astype(np.float32), nets=nets.values.astype(str),
             **{f"L_{k}": v for k, v in links.items()})
    print("labelled", len(rows), "candidates", len(cols), "features", f.shape[1], "link kinds", list(links))


if __name__ == "__main__":
    main(sys.argv[1])
