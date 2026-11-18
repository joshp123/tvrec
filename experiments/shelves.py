"""Shelves: the map's top level. Fine clusters (map.py) are joined into
shelves by Leiden over the cluster closeness graph (each cluster linked to its
10 closest), at a resolution where a person's liked titles fall on a handful
of shelves. The taste screen shows shelves; picks stay one per fine cluster.

Writes shelves.npy: fine cluster -> shelf."""
import numpy as np
import scipy.sparse as sp

import map as M
from core import W

RESOLUTION, LINKS = 8.0, 10

S = np.load(W / "closeness.npy")
k = S.shape[0]
top = np.argsort(-S, axis=1)[:, :LINKS]
rows = np.repeat(np.arange(k), LINKS)
A = sp.csr_matrix((S[rows, top.ravel()], (rows, top.ravel())), shape=(k, k))
A = A.maximum(A.T).tocsr()
shelf = M.cluster(A, RESOLUTION)
np.save(W / "shelves.npy", shelf)
print("clusters", k, "shelves", shelf.max() + 1, "clusters per shelf, median", int(np.median(np.bincount(shelf))))
