"""Level-1 neighbours with heavy raters damped (core.like_matrix), for linking
picks to a person's titles: a link should rest on people with a taste, not on
people who rate everything. The co-like counts stay unweighted."""
import time
import numpy as np
import core
from core import W, likes_table, like_matrix

t0 = time.time()
u, t = likes_table()
Lw, items = like_matrix(u, t, damp_heavy=True)
Lb, items_b = like_matrix(u, t)
assert np.array_equal(items, items_b)
idx, val, _, n_w = core.neighbours(Lw, workers=4)
cnt = np.zeros_like(val)
n = np.asarray(Lb.sum(0)).ravel()
Lbt = Lb.T.tocsr()
for s in range(0, len(items), 2000):
    rows = np.arange(s, min(s + 2000, len(items)))
    C = Lbt[rows] @ Lb
    cnt[rows] = np.vstack([np.asarray(C[i - s, idx[i]].todense()).ravel() for i in rows])
np.savez(W / "nb_people.npz", items=items, idx=idx, val=val, cnt=cnt, n=n, n_weighted=n_w)
print(f"done {time.time() - t0:.0f}s")
