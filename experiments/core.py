"""Level 1: which titles go together, learnt from other people's likes.

A like is a rating in the top quarter of the source's scale and at or above
that person's own average. sim(i, j) is the number of people who liked both,
divided by sqrt(likers(i) * likers(j)), shrunk towards zero when few people
support it. Each title keeps its K strongest neighbours."""
import multiprocessing as mp
import pathlib

import duckdb
import numpy as np
import scipy.sparse as sp

W = pathlib.Path(__file__).resolve().parent.parent / "data/work/exp"
K = 400
SHRINK = 5.0


def likes_table(exclude_users=None, exclude_items=None):
    """(u, t) pairs that are likes, as numpy arrays."""
    con = duckdb.connect(config={"memory_limit": "6GB", "threads": 8})
    df = con.execute(f"""
        with m as (select u, t, r, avg(r) over (partition by u) um from '{W}/ratings.parquet')
        select u, t from m where r >= 0.75 and r >= um""").fetchnumpy()
    u, t = df["u"], df["t"]
    keep = np.ones(len(u), bool)
    if exclude_users is not None:
        keep &= ~np.isin(u, exclude_users)
    if exclude_items is not None:
        keep &= ~np.isin(t, exclude_items)
    return u[keep], t[keep]


def like_matrix(u, t, min_likers=3):
    items, ti, counts = np.unique(t, return_inverse=True, return_counts=True)
    keep_item = counts >= min_likers
    m = keep_item[ti]
    u, ti = u[m], ti[m]
    remap = np.cumsum(keep_item) - 1
    ti = remap[ti]
    items = items[keep_item]
    users, ui = np.unique(u, return_inverse=True)
    L = sp.csr_matrix((np.ones(len(ui), np.float32), (ui, ti)), shape=(len(users), len(items)))
    return L, items


_L = _Lt = _n = None


def _chunk(rows):
    C = (_Lt[rows] @ _L).toarray()
    C[np.arange(len(rows)), rows] = 0
    S = C / np.sqrt(np.outer(_n[rows], _n)) * (C / (C + SHRINK))
    k = min(K, S.shape[1] - 1)
    idx = np.argpartition(-S, k, axis=1)[:, :k]
    val = np.take_along_axis(S, idx, 1)
    cnt = np.take_along_axis(C, idx, 1)
    return rows[0], idx.astype(np.int32), val.astype(np.float32), cnt.astype(np.float32)


def neighbours(L, workers=8, chunk=192):
    """For every title j: its K most similar titles i, sim(i, j), and the co-like count."""
    global _L, _Lt, _n
    _L, _Lt = L.tocsr(), L.T.tocsr()
    _n = np.asarray(L.sum(0)).ravel()
    n = L.shape[1]
    starts = [np.arange(s, min(s + chunk, n)) for s in range(0, n, chunk)]
    idx = np.zeros((n, K), np.int32)
    val = np.zeros((n, K), np.float32)
    cnt = np.zeros((n, K), np.float32)
    with mp.get_context("fork").Pool(workers) as pool:
        for s, i, v, c in pool.imap_unordered(_chunk, starts):
            idx[s:s + len(i), :i.shape[1]] = i
            val[s:s + len(i), :i.shape[1]] = v
            cnt[s:s + len(i), :i.shape[1]] = c
    return idx, val, cnt, _n


def score(seeds, idx, val, n_items, how="max", weights=None):
    """Score every title from seed titles (item indices). how: 'sum', 'max' or
    'max+': the strongest link plus a tenth of the rest. Returns the score and,
    for each title, the seed that gave its strongest link."""
    S = np.zeros((len(seeds), n_items), np.float32)
    for r, j in enumerate(seeds):
        S[r, idx[j]] = val[j] * (1.0 if weights is None else weights[r])
    if how == "sum":
        return S.sum(0), S.argmax(0)
    best = S.max(0)
    if how == "max":
        return best, S.argmax(0)
    return best + 0.1 * (S.sum(0) - best), S.argmax(0)
