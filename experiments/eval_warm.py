"""Experiment: reveal k of a held-out person's likes, rank every other title, and
count how many of their hidden likes reach the top 50. Series and films are
ranked separately, and little-rated titles (fewer than 500 likers) are also
ranked among themselves, as the niche lane would be.

Also: do film likes predict series likes?"""
import duckdb
import numpy as np
import pandas as pd

from core import W

TOP = 50
LITTLE = 500
KS = (5, 10, 20, 50)
rng = np.random.default_rng(11)

d = np.load(W / "nb_eval.npz")
items, idx, val, n = d["items"], d["idx"], d["val"], d["n"]
N = len(items)
pos = {t: i for i, t in enumerate(items)}
ser = np.zeros(N, bool)
st = dict(duckdb.sql(f"select t, is_series from '{W}/titles.parquet'").fetchall())
ser[:] = [st.get(t, 0) == 1 for t in items]
little = n < LITTLE
tie = 1e-9 * np.log1p(n)
SEG = {"films": ~ser, "films, little-rated": ~ser & little, "series": ser, "series, little-rated": ser & little}
pop_rank = {name: np.flatnonzero(m)[np.argsort(-n[m])] for name, m in SEG.items()}


def agg(seeds, how):
    I, V = idx[seeds].ravel(), val[seeds].ravel()
    s = np.bincount(I, V, minlength=N)
    if how == "sum":
        return s
    m = np.zeros(N)
    np.maximum.at(m, I, V)
    return m if how == "max" else m + 0.1 * (s - m)


def recall(order_fn, seg, revealed, hidden):
    h = hidden & SEG[seg]
    if not h.any():
        return None
    top = order_fn(seg, revealed)
    return h[top].sum() / min(TOP, h.sum())


def by_score(sc):
    def f(seg, revealed):
        x = np.where(SEG[seg] & ~revealed, sc + tie, -np.inf)
        return np.argpartition(-x, TOP)[:TOP]
    return f


def by_pop(seg, revealed):
    o = pop_rank[seg]
    return o[~revealed[o]][:TOP]


def main():
    tl = duckdb.sql(f"select u, t, source from '{W}/test_likes.parquet'").df()
    rows, f2s = [], []
    for u, g in tl.groupby("u"):
        warm = np.array([pos[t] for t in g.t if t in pos])
        if len(warm) < 10:
            continue
        src = g.source.iloc[0]
        tail = little[warm].mean() >= 0.25
        liked = np.zeros(N, bool)
        liked[warm] = True
        for k in KS:
            if len(warm) < k + 5:
                continue
            rev = rng.choice(warm, k, replace=False)
            revealed = np.zeros(N, bool)
            revealed[rev] = True
            hidden = liked & ~revealed
            methods = {"popularity": by_pop}
            for how in ("sum", "max", "max+"):
                methods[how] = by_score(agg(rev, how))
            for seg in SEG:
                for name, f in methods.items():
                    r = recall(f, seg, revealed, hidden)
                    if r is not None:
                        rows.append((u, src, tail, k, seg, name, r))
        # Film likes -> series likes.
        films, series = warm[~ser[warm]], warm[ser[warm]]
        if len(films) >= 20 and len(series) >= 6:
            s5 = rng.choice(series, 5, replace=False)
            f20 = rng.choice(films, 20, replace=False)
            hidden = np.zeros(N, bool)
            hidden[np.setdiff1d(series, s5)] = True
            for name, seeds in {"5 series": s5, "10 films": f20[:10], "20 films": f20, "20 films + 5 series": np.r_[f20, s5]}.items():
                revealed = np.zeros(N, bool)
                revealed[seeds] = True
                for seg in ("series", "series, little-rated"):
                    r = recall(by_score(agg(seeds, "max+")), seg, revealed, hidden)
                    p = recall(by_pop, seg, revealed, hidden)
                    if r is not None:
                        f2s.append((u, tail, seg, name, r, p))

    df = pd.DataFrame(rows, columns=["u", "source", "long_tail", "k", "segment", "method", "recall"])
    df.to_parquet(W / "eval_warm.parquet")
    f2 = pd.DataFrame(f2s, columns=["u", "long_tail", "segment", "seeds", "recall", "pop_recall"])
    f2.to_parquet(W / "eval_film2series.parquet")
    pd.set_option("display.width", 200)
    print("test people used", df.u.nunique(), "long-tail", df[df.long_tail].u.nunique())
    for grp, sub in (("all people", df), ("long-tail people", df[df.long_tail])):
        print(f"\n== recall@{TOP}, {grp} (people per cell in brackets)")
        t = sub.pivot_table(index=["segment", "k"], columns="method", values="recall", aggfunc="mean").round(3)
        t["people"] = sub.groupby(["segment", "k"]).u.nunique()
        print(t[["popularity", "sum", "max", "max+", "people"]])
    print("\n== by data set, k=10, max+")
    print(df[(df.k == 10) & (df.method.isin(["popularity", "max+"]))].pivot_table(index=["source", "segment"], columns="method", values="recall", aggfunc="mean").round(3))
    print(f"\n== film likes -> series likes, recall@{TOP} (max+); people: {f2.u.nunique()}, long-tail {f2[f2.long_tail].u.nunique()}")
    for grp, sub in (("all", f2), ("long-tail", f2[f2.long_tail])):
        print(grp)
        print(sub.groupby(["segment", "seeds"])[["recall", "pop_recall"]].mean().round(3))


if __name__ == "__main__":
    main()
