"""Experiment: does adding makers and plot text (level 1) or a plot embedding
(level 2) to other people's likes help rank titles that do have ratings?
Same held-out people and measure as eval_warm.py, at k = 10 and 20."""
import sys

import duckdb
import numpy as np
import pandas as pd
import scipy.sparse as sp

import eval_warm as R
from content import Text, load_embeddings
from core import W

rng = np.random.default_rng(11)
MAX_PEOPLE = 2000
N = R.N


def rank(s):
    r = np.empty(len(s))
    r[np.argsort(-s, kind="stable")] = np.arange(len(s))
    return r


def rrf(*scores, w=None):
    """Reciprocal-rank fusion; titles with no evidence of a kind get nothing from it."""
    w = w or [1] * len(scores)
    return sum(wi * np.where(s > 0, 1 / (60 + rank(s)), 0) for wi, s in zip(w, scores))


tx = Text()
tpos = np.array([tx.pos.get(t, -1) for t in R.items])
TX = tx.X[np.maximum(tpos, 0)].multiply((tpos >= 0)[:, None]).tocsr()
USE_EMB = "--no-emb" not in sys.argv
ids, E = load_embeddings() if USE_EMB else (np.zeros(0, np.int64), np.zeros((0, 8), np.float32))
epos = {t: i for i, t in enumerate(ids)}
EM = np.zeros((N, E.shape[1]), np.float32)
have = np.array([t in epos for t in R.items])
EM[have] = E[[epos[t] for t in R.items[have]]]
print("rated titles with plot text", (tpos >= 0).mean().round(3), "with embedding", have.mean().round(3), flush=True)

mk = duckdb.sql(f"select t, nconst, w from '{W}/makers.parquet'").df()
mk = mk[mk.t.isin(set(R.items))]
mcode = {m: i for i, m in enumerate(mk.nconst.unique())}
rows_ = [R.pos[t] for t in mk.t]
MW = sp.csr_matrix((mk.w.values, (rows_, [mcode[m] for m in mk.nconst])), shape=(N, len(mcode)))
MB = MW

_cnt = np.load(W / "nb_eval.npz")["cnt"]
LIFT = (_cnt / (np.sqrt(R.n)[:, None] * R.n[R.idx]) * (_cnt / (_cnt + 5))).astype(np.float32)
LIFT[_cnt < 2] = 0
tl = duckdb.sql(f"select u, t from '{W}/test_likes.parquet'").df()
users = tl.u.unique()
users = rng.choice(users, min(MAX_PEOPLE, len(users)), replace=False)
tl = tl[tl.u.isin(users)]
out = []
for u, g in tl.groupby("u"):
    warm = np.array([R.pos[t] for t in g.t if t in R.pos])
    if len(warm) < 25:
        continue
    tail = R.little[warm].mean() >= 0.25
    liked = np.zeros(N, bool)
    liked[warm] = True
    for k in (10, 20):
        rev = rng.choice(warm, k, replace=False)
        revealed = np.zeros(N, bool)
        revealed[rev] = True
        hidden = liked & ~revealed
        cf = R.agg(rev, "sum")
        maker = np.asarray((MW @ MB[rev].T).max(1).todense()).ravel()
        words = np.asarray((TX @ TX[rev].T).max(1).todense()).ravel()
        cf_lift = np.bincount(R.idx[rev].ravel(), LIFT[rev].ravel(), minlength=N)
        methods = {"likes only (sum)": cf,
                   "likes, popularity-corrected (sum)": cf_lift,
                   "likes + makers + words, equal": rrf(cf, maker, words),
                   "likes + makers + words, 1/.5/.25": rrf(cf, maker, words, w=[1, .5, .25]),
                   "likes + makers": rrf(cf, maker)}
        if USE_EMB:
            emb = (EM @ EM[rev].T).max(1)
            methods["likes + makers + words + embedding, equal"] = rrf(cf, maker, words, emb)
            methods["likes + makers + embedding, 1/.5/.25"] = rrf(cf, maker, emb, w=[1, .5, .25])
        for seg in R.SEG:
            for name, s in methods.items():
                r = R.recall(R.by_score(s), seg, revealed, hidden)
                if r is not None:
                    out.append((u, tail, k, seg, name, r))

df = pd.DataFrame(out, columns=["u", "long_tail", "k", "segment", "method", "recall"])
df.to_parquet(W / "eval_warm_content.parquet")
pd.set_option("display.width", 220)
for grp, sub in (("all people", df), ("long-tail people", df[df.long_tail])):
    print(f"\n== recall@{R.TOP}, {grp}; people: {sub.u.nunique()}")
    print(sub.pivot_table(index=["segment", "k"], columns="method", values="recall", aggfunc="mean").round(3))
