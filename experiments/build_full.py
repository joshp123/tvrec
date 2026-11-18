"""Level-1 neighbours from everyone's likes, for ranking the household's titles."""
import time, numpy as np
from core import W, likes_table, like_matrix, neighbours

t0 = time.time()
u, t = likes_table()
L, items = like_matrix(u, t)
print("likes", L.nnz, "users", L.shape[0], "titles", L.shape[1], f"{time.time()-t0:.0f}s", flush=True)
idx, val, cnt, n = neighbours(L)
np.savez(W / "nb_full.npz", items=items, idx=idx, val=val, cnt=cnt, n=n)
print(f"done {time.time()-t0:.0f}s")
