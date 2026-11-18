"""The taste map: groups of titles that share an audience, found first and
named afterwards (name_clusters.py).

One graph over every film and series with 300 or more IMDb votes. Each title
links to the titles most like it by the best evidence it has:
- by other people's likes: for titles with 30 or more likers, their 20
  strongest links (co-likes over the square root of both titles' likers);
  for other titles, links that two or more people support;
- by content, for every title: its 10 closest titles by shared makers plus
  plot words, scaled so a typical content link weighs the same as a typical
  likes link, and a quarter of that for titles with 30 or more likers (at full
  weight, shared words such as "metal" pulled an unrelated comedy among heavy-metal
  documentaries). Likes alone grouped titles by data set and era (a 2000s DVD
  catalogue, one streaming service's hits); content keeps each cluster one
  kind of thing.
Leiden community detection cuts the graph into clusters; clusters over
MAX_SIZE are cut again on their own subgraph, and clusters under MIN_SIZE join
the cluster they link to most. Closeness between two clusters is the link
weight between them over the square root of each cluster's total.

Usage: python map.py [RESOLUTION]   writes map.parquet and closeness.npy"""
import sys

import duckdb
import igraph as ig
import leidenalg
import numpy as np
import pandas as pd
import scipy.sparse as sp

import content
from core import W

CORE_LIKERS, K_LIKES, K_CONTENT, MIN_SIZE, MAX_SIZE, MIN_VOTES = 30, 20, 10, 8, 150, 300
CORE_CONTENT = 0.25  # content links count a quarter for titles with likes of their own
KINDS = ("movie", "tvSeries", "tvMiniSeries", "tvMovie", "tvSpecial")


def likes_edges(d, pos, is_core):
    """(row, col, weight) for links by other people's likes between graph titles."""
    items, idx, val, cnt = d["items"], d["idx"], d["val"], d["cnt"]
    gpos = np.array([pos.get(t, -1) for t in items])
    rows, cols, w = [], [], []
    for j in np.flatnonzero(gpos >= 0):
        nb, v, c = idx[j], val[j], cnt[j]
        core_j = is_core[gpos[j]]
        ok = (gpos[nb] >= 0) & (c >= (3 if core_j else 2)) & (v > 0)
        if core_j:
            ok &= is_core[np.maximum(gpos[nb], 0)]
        nb, v = nb[ok], v[ok]
        top = np.argsort(-v)[:K_LIKES]
        rows += [gpos[j]] * len(top)
        cols += list(gpos[nb[top]])
        w += list(v[top])
    return np.array(rows), np.array(cols), np.array(w)


def content_edges(src, nodes, k=K_CONTENT):
    """Each src title's k closest graph titles by shared makers plus plot words."""
    mk = duckdb.sql(f"select t, nconst, w from '{W}/makers.parquet'").df()
    mk = mk[mk.t.isin(set(nodes))]
    mcode = {m: i for i, m in enumerate(mk.nconst.unique())}
    npos = {t: i for i, t in enumerate(nodes)}
    M = sp.csr_matrix((mk.w, ([npos[t] for t in mk.t], [mcode[m] for m in mk.nconst])), shape=(len(nodes), len(mcode)))
    tx = content.Text()
    trow = np.array([tx.pos.get(t, -1) for t in nodes])
    X = tx.X[np.maximum(trow, 0)].multiply((trow >= 0)[:, None]).tocsr()
    XT, MT = X.T.tocsc(), M.T.tocsc()
    rows, cols, w = [], [], []
    src_idx = np.array([npos[t] for t in src])
    for s in range(0, len(src_idx), 500):
        r = src_idx[s:s + 500]
        S = (X[r] @ XT).toarray() + (M[r] @ MT).toarray()
        S[np.arange(len(r)), r] = 0
        top = np.argpartition(-S, k, axis=1)[:, :k]
        val = np.take_along_axis(S, top, 1)
        ok = val > 0
        rows += list(np.repeat(r, k)[ok.ravel()])
        cols += list(top.ravel()[ok.ravel()])
        w += list(val.ravel()[ok.ravel()])
    return np.array(rows), np.array(cols), np.array(w)


def cluster(A, resolution):
    src, dst = A.nonzero()
    keep = src < dst
    g = ig.Graph(n=A.shape[0], edges=list(zip(src[keep], dst[keep])), directed=False)
    weights = np.asarray(A[src[keep], dst[keep]]).ravel()
    part = leidenalg.find_partition(g, leidenalg.RBConfigurationVertexPartition, weights=weights,
                                    resolution_parameter=resolution, seed=7, n_iterations=-1)
    return np.array(part.membership)


def merge_small(A, lab):
    for _ in range(3):
        sizes = np.bincount(lab)
        small = np.flatnonzero(sizes < MIN_SIZE)
        if not len(small):
            break
        C = sp.csr_matrix((np.ones(len(lab)), (np.arange(len(lab)), lab)))
        link = (A @ C).toarray()
        for i in np.flatnonzero(np.isin(lab, small)):
            row = link[i].copy()
            row[small] = 0
            if row.max() > 0:
                lab[i] = row.argmax()
    return np.unique(lab, return_inverse=True)[1]


def refine(A, lab):
    """Cut any cluster over MAX_SIZE again on its own subgraph, at rising resolution."""
    lab = lab.copy()
    nxt = lab.max() + 1
    for _ in range(4):
        big = np.flatnonzero(np.bincount(lab) > MAX_SIZE)
        if not len(big):
            break
        for c in big:
            idx = np.flatnonzero(lab == c)
            sub = A[idx][:, idx]
            if not sub.nnz:
                continue
            for r in (2, 4, 8, 16, 32):
                parts = cluster(sub, r)
                if np.bincount(parts).max() <= MAX_SIZE:
                    break
            for p in range(1, parts.max() + 1):
                lab[idx[parts == p]] = nxt
                nxt += 1
    return np.unique(lab, return_inverse=True)[1]


def closeness(A, lab):
    C = sp.csr_matrix((np.ones(len(lab)), (np.arange(len(lab)), lab)))
    B = (C.T @ A @ C).toarray()
    vol = B.sum(1)
    S = B / np.sqrt(np.outer(vol, vol))
    np.fill_diagonal(S, 0)
    return S


def main(resolution):
    d = np.load(W / "nb_full.npz")
    likers = dict(zip(d["items"], d["n"]))
    ti = duckdb.sql(f"select t, kind, imdb_votes from '{W}/titles.parquet'").df().set_index("t")
    has_text = {t for (t,) in duckdb.sql(f"select distinct t from '{W}/plot.parquet'").fetchall()}
    has_maker = {t for (t,) in duckdb.sql(f"select distinct t from '{W}/makers.parquet'").fetchall()}
    ok = ti.kind.isin(KINDS)
    core = {t for t in d["items"] if likers[t] >= CORE_LIKERS and ok.get(t, False)}
    thin = {t for t in ti.index[ok & (ti.imdb_votes >= MIN_VOTES)] if t not in core and (t in has_text or t in has_maker)}
    nodes = np.array(sorted(core | thin))
    pos = {t: i for i, t in enumerate(nodes)}
    is_core = np.array([t in core for t in nodes])
    print("titles", len(nodes), "with 30+ likers", is_core.sum(), flush=True)

    r1, c1, w1 = likes_edges(d, pos, is_core)
    cache = W / "content_edges.npz"
    if cache.exists() and np.array_equal(np.load(cache)["nodes"], nodes):
        z = np.load(cache)
        r2, c2, w2 = z["r"], z["c"], z["w"]
    else:
        r2, c2, w2 = content_edges(nodes, nodes)
        np.savez(cache, nodes=nodes, r=r2, c=c2, w=w2)
    w2 = w2 * (np.median(w1) / np.median(w2)) * np.where(is_core[r2], CORE_CONTENT, 1.0)
    A = sp.csr_matrix((np.r_[w1, w2], (np.r_[r1, r2], np.r_[c1, c2])), shape=(len(nodes), len(nodes)))
    A = A.maximum(A.T).tocsr()
    linked = np.asarray((A > 0).sum(1)).ravel() > 0
    nodes, A, is_core = nodes[linked], A[linked][:, linked], is_core[linked]

    lab = merge_small(A, refine(A, cluster(A, resolution)))
    sizes = np.bincount(lab)
    print("clusters", len(sizes), "size median", int(np.median(sizes)), "max", sizes.max(), flush=True)
    np.save(W / "closeness.npy", closeness(A, lab))

    # How well do makers and plot words alone place a title that has likes?
    rng = np.random.default_rng(1)
    sample = rng.choice(np.flatnonzero(is_core), 3000, replace=False)
    r, c, w = content_edges(nodes[sample], nodes)
    S = np.load(W / "closeness.npy")
    hit = near = 0
    for i in sample:
        m = r == i
        if not m.any():
            continue
        guess = np.bincount(lab[c[m]], w[m]).argmax()
        hit += guess == lab[i]
        near += guess == lab[i] or guess in np.argsort(-S[lab[i]])[:5]
    print(f"placement check: makers and plot words alone put {hit / len(sample):.2f} of 3000 well-rated titles "
          f"in their own cluster, {near / len(sample):.2f} in it or one of its 5 closest", flush=True)

    pd.DataFrame({"t": nodes, "cluster": lab, "placed_by": np.where(is_core, "likes", "few likes")}
                 ).to_parquet(W / "map.parquet")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 40.0)
