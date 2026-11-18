"""Experiment: does choosing on the taste map find things a person likes
outside their usual clusters, better than other people's likes alone?

For each held-out person (split.py), reveal 20 of their likes. Their usual
clusters are the clusters of those 20. Their stretch likes are their other
likes in any other cluster. Rank every title outside their usual clusters
and count how many stretch likes reach the top 50, and how well known those
hits are. The map was built from everyone's likes, test people included
(7,700 of 5.7 million), so it knows a little about them.

Methods:
- popularity: most likers first;
- likes: the level-1 ranker (sum of links from the revealed likes);
- likes, popularity-corrected: the same, links divided by the candidate's own likers;
- map: clusters ordered by closeness to the usual clusters, best-rated title first in each;
- map + likes, map + corrected likes: reciprocal-rank fusion of the two."""
import duckdb
import numpy as np
import pandas as pd

import eval_warm as R
from core import W

TOP, REVEAL, PEOPLE = 50, 20, 2000
rng = np.random.default_rng(17)

m = duckdb.sql(f"select t, cluster from '{W}/map.parquet'").df()
cl = dict(zip(m.t, m.cluster))
lab = np.array([cl.get(t, -1) for t in R.items])
S = np.load(W / "closeness.npy")
rating = dict(duckdb.sql(f"select t, imdb_rating from '{W}/titles.parquet'").fetchall())
votes = dict(duckdb.sql(f"select t, imdb_votes from '{W}/titles.parquet'").fetchall())
qual = np.array([rating.get(t) or 0 for t in R.items])
v = np.array([votes.get(t) or 0 for t in R.items], float)
quality = (qual * v + 7 * 2000) / (v + 2000)
cnt = np.load(W / "nb_eval.npz")["cnt"]
LIFT = (cnt / (np.sqrt(R.n)[:, None] * R.n[R.idx]) * (cnt / (cnt + 5))).astype(np.float32)
LIFT[cnt < 2] = 0


def rank(s):
    r = np.empty(len(s))
    r[np.argsort(-s, kind="stable")] = np.arange(len(s))
    return r


def rrf(*xs):
    return sum(1 / (60 + rank(x)) for x in xs)


tl = duckdb.sql(f"select u, t from '{W}/test_likes.parquet'").df()
users = rng.choice(tl.u.unique(), PEOPLE, replace=False)
rows = []
for u, g in tl[tl.u.isin(users)].groupby("u"):
    warm = np.array([R.pos[t] for t in g.t if t in R.pos])
    warm = warm[lab[warm] >= 0]
    if len(warm) < REVEAL + 10:
        continue
    tail = R.little[warm].mean() >= 0.25
    rev = rng.choice(warm, REVEAL, replace=False)
    usual = np.unique(lab[rev])
    outside = (lab >= 0) & ~np.isin(lab, usual)
    hidden = np.zeros(R.N, bool)
    hidden[np.setdiff1d(warm, rev)] = True
    hidden &= outside
    if not hidden.any():
        continue
    reach = np.bincount(lab[rev], minlength=S.shape[0]) @ S
    map_score = np.where(lab >= 0, reach[np.maximum(lab, 0)], 0) * 10 + quality / 100
    cf = R.agg(rev, "sum")
    lift = np.bincount(R.idx[rev].ravel(), LIFT[rev].ravel(), minlength=R.N)
    methods = {"popularity": R.n.astype(float), "likes": cf, "likes, popularity-corrected": lift,
               "map": map_score, "map + likes": rrf(map_score, cf), "map + corrected likes": rrf(map_score, lift)}
    for name, s in methods.items():
        x = np.where(outside, s + R.tie, -np.inf)
        top = np.argpartition(-x, TOP)[:TOP]
        hits = top[hidden[top]]
        rows.append((u, tail, name, len(hits) / min(TOP, hidden.sum()), len(hits),
                     np.median(R.n[hits]) if len(hits) else np.nan, R.little[hits].mean() if len(hits) else np.nan))

df = pd.DataFrame(rows, columns=["u", "long_tail", "method", "recall", "hits", "median_likers_of_hits", "little_rated_share"])
df.to_parquet(W / "eval_stretch.parquet")
pd.set_option("display.width", 200)
for grp, sub in (("all people", df), ("long-tail people", df[df.long_tail])):
    print(f"\n== stretch likes in the top {TOP} of titles outside the person's usual clusters, {grp}: {sub.u.nunique()} people")
    print(sub.groupby("method")[["recall", "median_likers_of_hits", "little_rated_share"]].mean().round(3)
          .sort_values("recall").to_string())
