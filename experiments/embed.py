"""Level 2: embed each title's plot text with a frozen open model, run locally.
Titles already embedded are kept, so a rerun only adds new text."""
import numpy as np
import duckdb
from sentence_transformers import SentenceTransformer

from core import W
from content import plots

MODEL = "Qwen/Qwen3-Embedding-0.6B"

def main():
    p = plots()
    keep = {t for (t,) in duckdb.sql(f"""select t from '{W}/titles.parquet'
        where kind in ('movie','tvSeries','tvMiniSeries') and imdb_votes >= 100""").fetchall()}
    keep |= set(np.load(W / "nb_full.npz")["items"].tolist())
    old_ids, old_E = (np.load(W / "emb.npz")["ids"], np.load(W / "emb.npz")["E"]) if (W / "emb.npz").exists() else (np.zeros(0, np.int64), np.zeros((0, 1024), np.float32))
    done = set(old_ids.tolist())
    todo = sorted((t for t in p if t in keep and t not in done), key=lambda t: len(p[t]))
    print("to embed", len(todo), "already", len(done), flush=True)
    m = SentenceTransformer(MODEL, device="mps")
    m.max_seq_length = 256
    parts = []
    for s in range(0, len(todo), 8192):
        ids = todo[s:s + 8192]
        parts.append(m.encode([p[t][:2000] for t in ids], batch_size=32, normalize_embeddings=True).astype(np.float32))
        print(s + len(ids), flush=True)
    ids = np.concatenate([old_ids, np.array(todo, np.int64)])
    E = np.concatenate([old_E] + parts)
    np.savez(W / "emb.npz", ids=ids, E=E)

if __name__ == "__main__":
    main()
