"""Level 2: embed each title's plot text with a frozen open model, run locally.

Each batch of 4,096 titles is saved as soon as it is done, so a stopped run
resumes where it was. The result is emb.npy (float32, read memory-mapped)
and emb_ids.npy; a rerun only adds titles that have no embedding yet."""
import gc
import shutil

import duckdb
import numpy as np

from core import W
from content import plots

MODEL = "Qwen/Qwen3-Embedding-0.6B"
PARTS = W / "emb_parts"
CHUNK = 4096


def done_ids():
    ids = [np.load(W / "emb_ids.npy")] if (W / "emb_ids.npy").exists() else []
    if (W / "emb.npz").exists():
        ids.append(np.load(W / "emb.npz")["ids"])
    ids += [np.load(p)["ids"] for p in sorted(PARTS.glob("*.npz"))]
    return set(np.concatenate(ids).tolist()) if ids else set()


def embed_missing():
    p = plots()
    keep = {t for (t,) in duckdb.sql(f"""select t from '{W}/titles.parquet'
        where kind in ('movie','tvSeries','tvMiniSeries') and imdb_votes >= 100""").fetchall()}
    keep |= set(np.load(W / "nb_full.npz")["items"].tolist())
    done = done_ids()
    todo = sorted((t for t in p if t in keep and t not in done), key=lambda t: len(p[t]))
    texts = {t: p[t][:2000] for t in todo}
    del p
    gc.collect()
    print("to embed", len(todo), "already", len(done), flush=True)
    if not todo:
        return
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(MODEL, device="mps")
    m.max_seq_length = 256
    PARTS.mkdir(exist_ok=True)
    start = len(list(PARTS.glob("*.npz")))
    for k, s in enumerate(range(0, len(todo), CHUNK)):
        ids = np.array(todo[s:s + CHUNK], np.int64)
        E = m.encode([texts[t] for t in ids], batch_size=32, normalize_embeddings=True).astype(np.float32)
        np.savez(PARTS / f"{start + k:05d}.npz", ids=ids, E=E)
        print(s + len(ids), flush=True)
    del m
    gc.collect()


def merge():
    """Old result plus saved batches into one memory-mappable file."""
    srcs = []
    if (W / "emb_ids.npy").exists():
        srcs.append((np.load(W / "emb_ids.npy"), np.load(W / "emb.npy", mmap_mode="r")))
    if (W / "emb.npz").exists():
        z = np.load(W / "emb.npz")
        srcs.append((z["ids"], z["E"]))
    for f in sorted(PARTS.glob("*.npz")):
        z = np.load(f)
        srcs.append((z["ids"], z["E"]))
    if len(srcs) <= 1 and (W / "emb.npy").exists():
        return
    n = sum(len(i) for i, _ in srcs)
    out = np.lib.format.open_memmap(W / "emb.tmp.npy", mode="w+", dtype=np.float32, shape=(n, srcs[0][1].shape[1]))
    r = 0
    for _, E in srcs:
        for s in range(0, len(E), 20000):
            out[r + s:r + min(s + 20000, len(E))] = E[s:s + 20000]
        r += len(E)
    out.flush()
    ids = np.concatenate([i for i, _ in srcs])
    del out, srcs
    np.save(W / "emb_ids.tmp.npy", ids)
    (W / "emb.tmp.npy").rename(W / "emb.npy")
    (W / "emb_ids.tmp.npy").rename(W / "emb_ids.npy")
    (W / "emb.npz").unlink(missing_ok=True)
    shutil.rmtree(PARTS, ignore_errors=True)
    print("merged", n)


if __name__ == "__main__":
    embed_missing()
    merge()
