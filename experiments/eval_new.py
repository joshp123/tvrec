"""Experiment: titles nobody has rated yet. Every rating of 800 series and 800
films was removed before learning (split.py). For each held-out person, reveal
up to 20 of their likes among rated titles, rank the new titles of each kind,
and count how many of the new titles they liked reach the top 20 of 800.

Level 1 has makers and plain word search over plot text; level 2 adds a
frozen embedding of the same text. "via neighbours" scores a new title by the
level-1 score of the rated titles whose text is closest to it."""
import sys

import duckdb
import numpy as np
import pandas as pd
import scipy.sparse as sp

from core import W
from content import Text, load_embeddings

TOP = 20
REVEAL = 20
NB = 20
rng = np.random.default_rng(5)

d = np.load(W / "nb_eval.npz")
items, idx, val, n, new = d["items"], d["idx"], d["val"], d["n"], d["new"]
N = len(items)
pos = {t: i for i, t in enumerate(items)}
st = dict(duckdb.sql(f"select t, is_series from '{W}/titles.parquet'").fetchall())
votes = dict(duckdb.sql(f"select t, imdb_votes from '{W}/titles.parquet'").fetchall())
new_ser = np.array([st.get(t, 0) == 1 for t in new])
newpos = {t: i for i, t in enumerate(new)}


def cf_scores(seeds):
    return np.bincount(idx[seeds].ravel(), val[seeds].ravel(), minlength=N)


def content_sims(ids, E_rows):
    """(new titles x rated titles) similarity; zero where either has no text."""
    p = {t: i for i, t in enumerate(ids)}
    a = np.array([p.get(t, -1) for t in new])
    b = np.array([p.get(t, -1) for t in items])
    S = np.zeros((len(new), N), np.float32)
    ok_a, ok_b = a >= 0, b >= 0
    block = E_rows(a[ok_a], b[ok_b])
    S[np.ix_(ok_a, ok_b)] = block
    return S


def nearest(S):
    """Each new title's NB closest rated titles and their similarity."""
    top = np.argpartition(-S, NB, axis=1)[:, :NB]
    return top, np.take_along_axis(S, top, 1)


tx = Text()
text_S = content_sims(tx.ids, lambda a, b: (tx.X[a] @ tx.X[b].T).toarray())
text_near = nearest(text_S)
emb_S = None
if "--no-emb" not in sys.argv:
    ids, E = load_embeddings()
    emb_S = content_sims(ids, lambda a, b: E[a] @ E[b].T)
    emb_near = nearest(emb_S)
    have = np.isin(new, ids)
    print(f"new titles with an embedding: {have.sum()} of {len(new)}")

mk = duckdb.sql(f"select t, nconst, w from '{W}/makers.parquet'").df()
mk = mk[mk.t.isin(set(new) | set(items))]
mcode = {m: i for i, m in enumerate(mk.nconst.unique())}
def incidence(ts, weighted):
    p = {t: i for i, t in enumerate(ts)}
    sub = mk[mk.t.isin(p)]
    return sp.csr_matrix(((sub.w.values if weighted else np.ones(len(sub))),
                          ([p[t] for t in sub.t], [mcode[m] for m in sub.nconst])), shape=(len(ts), len(mcode)))
maker_S = np.minimum(1.0, (incidence(new, True) @ incidence(items, False).T).toarray()).astype(np.float32)


def via_neighbours(near, cf):
    top, w = near
    return (w * cf[top]).sum(1)


def rrf(*scores):
    out = np.zeros(len(new))
    for s in scores:
        r = np.empty(len(s))
        r[np.argsort(-s, kind="stable")] = np.arange(len(s))
        out += 1 / (60 + r)
    return out


def signals(seeds):
    cf = cf_scores(seeds)
    sig = {
        "random": rng.random(len(new)),
        "IMDb votes (leaks)": np.array([votes.get(t, 0) for t in new], float),
        "makers": maker_S[:, seeds].max(1),
        "words": text_S[:, seeds].max(1),
        "words via neighbours": via_neighbours(text_near, cf),
    }
    sig["level 1: makers + words"] = rrf(sig["makers"], sig["words"], sig["words via neighbours"])
    if emb_S is not None:
        sig["embedding"] = emb_S[:, seeds].max(1)
        sig["embedding via neighbours"] = via_neighbours(emb_near, cf)
        sig["level 2: level 1 + embedding"] = rrf(sig["makers"], sig["words"], sig["words via neighbours"],
                                                  sig["embedding"], sig["embedding via neighbours"])
        sig["level 2: makers + embedding"] = rrf(sig["makers"], sig["embedding"], sig["embedding via neighbours"])
    return sig


def people():
    """(person, liked new-title positions, revealed rated-title positions)."""
    tl = duckdb.sql(f"select u, t from '{W}/test_likes.parquet'").df()
    for u, g in tl.groupby("u"):
        liked_new = np.array([newpos[t] for t in g.t if t in newpos])
        warm = np.array([pos[t] for t in g.t if t in pos])
        if len(liked_new) == 0 or len(warm) < 5:
            continue
        yield u, liked_new, rng.choice(warm, min(REVEAL, len(warm)), replace=False)


def main():
    rows = []
    for u, liked_new, seeds in people():
        sig = signals(seeds)
        for kind, m in (("series", new_ser), ("films", ~new_ser)):
            h = np.zeros(len(new), bool)
            h[liked_new] = True
            h &= m
            if not h.any():
                continue
            for name, s in sig.items():
                x = np.where(m, s + 1e-12 * rng.random(len(new)), -np.inf)
                top = np.argpartition(-x, TOP)[:TOP]
                rows.append((u, kind, name, h[top].sum() / min(TOP, h.sum())))

    df = pd.DataFrame(rows, columns=["u", "kind", "signal", "recall"])
    df.to_parquet(W / "eval_new.parquet")
    pd.set_option("display.width", 200)
    print(f"recall@{TOP} among {(new_ser).sum()} new series / {(~new_ser).sum()} new films")
    t = df.pivot_table(index="signal", columns="kind", values="recall", aggfunc="mean").round(3)
    t["people (series, films)"] = [tuple(df[(df.signal == s)].groupby("kind").u.nunique().reindex(["series", "films"]).fillna(0).astype(int)) for s in t.index]
    print(t.sort_values("series"))


if __name__ == "__main__":
    main()
